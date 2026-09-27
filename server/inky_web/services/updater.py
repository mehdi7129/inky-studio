"""Self-update from prebuilt GitHub releases.

The Pi runs *prebuilt* releases — the frontend is built in CI, not on the
device — so updating is just: download the release tarball, extract it over the
install directory (preserving the venv, node_modules and data), refresh the
Python deps, and restart the systemd service.

Progress is reported through an ``emit(stage, message, **extra)`` callback so
the same routine can drive both:
  * the in-app one-click update (``emit`` broadcasts ``system_update`` events
    over the WebSocket EventBus — see :mod:`inky_web.api.system`), and
  * the ``inky-studio update`` CLI (``python -m inky_web.services.updater`` — ``emit``
    prints to stdout).

Restarting the service requires root; the installer grants the service user a
tightly-scoped passwordless sudo rule for ``systemctl restart/stop/start
inky-studio.service`` only (see ``install.sh``).
"""
from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import shutil
import tarfile
import tempfile
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

from inky_web import __version__

logger = logging.getLogger(__name__)

REPO_SLUG = os.environ.get("INKY_STUDIO_REPO_SLUG", "mehdi7129/inky-studio")
SERVICE_NAME = os.environ.get("INKY_STUDIO_SERVICE", "inky-studio.service")
# server/inky_web/services/updater.py → parents[3] == install dir (repo root)
INSTALL_DIR = Path(__file__).resolve().parents[3]

_API_LATEST = f"https://api.github.com/repos/{REPO_SLUG}/releases/latest"
_USER_AGENT = "inky-studio-updater"
_CACHE_TTL = 600.0  # seconds — don't hammer the GitHub API
_NEVER_OVERWRITE = {".venv", "node_modules", "data", ".git", ".env", ".env.local"}
_MAX_ARCHIVE_BYTES = 512 * 1024 * 1024

EmitFn = Callable[..., None]

_status_cache: dict[str, Any] = {"at": 0.0, "value": None}


# ── version + release metadata ───────────────────────────────────────────────
def _http_json(url: str, timeout: float = 10.0) -> Any:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — fixed https URL
        return json.loads(resp.read().decode("utf-8"))


def _parse_version(v: str | None) -> tuple[int, ...]:
    if not v:
        return ()
    v = v.lstrip("vV").split("-")[0].split("+")[0]
    parts: list[int] = []
    for chunk in v.split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            break
    return tuple(parts)


def _fetch_latest_release() -> dict[str, Any] | None:
    try:
        return _http_json(_API_LATEST)
    except Exception as exc:  # noqa: BLE001 — network/parse errors must never crash the app
        logger.warning("Could not fetch latest release: %s", exc)
        return None


def _is_newer_release(current: str, latest: str | None) -> bool:
    """Use the same version decision for discovery and the actual installation.

    Keep the historical different-label fallback for unversioned development
    builds (for example ``dev``/``unknown``), which have no ordered version.
    Published releases use numeric versions and cannot downgrade or reinstall
    the same stable version. A candidate can advance to its matching final.
    """
    if not latest:
        return False
    cur_t, lat_t = _parse_version(current), _parse_version(latest)
    if cur_t and lat_t:
        current_candidate = "-" in current.split("+")[0]
        latest_stable = "-" not in latest.split("+")[0]
        return lat_t > cur_t or (
            lat_t == cur_t and current_candidate and latest_stable
        )
    return latest != current


def get_status(*, use_cache: bool = True) -> dict[str, Any]:
    """Return ``{current, latest, update_available}`` (latest may be ``None``)."""
    now = time.time()
    cached = _status_cache["value"]
    if use_cache and cached is not None and now - _status_cache["at"] < _CACHE_TTL:
        return cached

    release = _fetch_latest_release()
    latest = (release.get("tag_name") or "").lstrip("vV") or None if release else None

    current = __version__
    update_available = _is_newer_release(current, latest)

    value = {"current": current, "latest": latest, "update_available": update_available}
    _status_cache.update(at=now, value=value)
    return value


def _pick_tarball_asset(release: dict[str, Any]) -> dict[str, Any] | None:
    for asset in release.get("assets", []):
        if str(asset.get("name", "")).endswith(".tar.gz"):
            return asset
    return None


# ── filesystem helpers ───────────────────────────────────────────────────────
def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/octet-stream"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp, dest.open("wb") as fh:  # noqa: S310
        shutil.copyfileobj(resp, fh)


def _safe_extract(tarball: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest.resolve()
    with tarfile.open(tarball, "r:gz") as tf:
        members = tf.getmembers()
        if len(members) > 10000 or sum(m.size for m in members) > _MAX_ARCHIVE_BYTES:
            raise RuntimeError("Release archive is too large")
        for member in members:
            path = PurePosixPath(member.name)
            target = (dest / member.name).resolve()
            if path.is_absolute() or ".." in path.parts or not target.is_relative_to(dest_resolved):
                raise RuntimeError(f"Unsafe path in archive: {member.name}")
            if not (member.isfile() or member.isdir()):
                raise RuntimeError(f"Unsupported archive entry: {member.name}")
        # Copy only regular files/directories. No links, devices, ownership or
        # setuid permissions from the archive are ever applied (also on 3.11).
        for member in members:
            target = dest / member.name
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                source = tf.extractfile(member)
                assert source is not None
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)


def _resolve_payload_root(extracted: Path) -> Path:
    """Releases are tarred flat (server/, client/, …). Descend into a single
    wrapper directory if one is present."""
    entries = list(extracted.iterdir())
    if len(entries) == 1 and entries[0].is_dir() and (entries[0] / "server").is_dir():
        return entries[0]
    return extracted


def _merge_dir(src: Path, dest: Path) -> None:
    """Recursively copy ``src`` into ``dest``, overwriting files but never
    touching entries listed in ``_NEVER_OVERWRITE`` (so the venv survives)."""
    dest.mkdir(parents=True, exist_ok=True)
    for child in src.iterdir():
        if child.name in _NEVER_OVERWRITE:
            continue
        target = dest / child.name
        if target.is_symlink():
            raise RuntimeError(f"Refusing to overwrite symlink: {target}")
        if child.is_dir():
            _merge_dir(child, target)
        else:
            shutil.copy2(child, target)


def _apply(src_root: Path, install_dir: Path) -> None:
    for item in src_root.iterdir():
        if item.name in _NEVER_OVERWRITE:
            continue
        dest = install_dir / item.name
        if dest.is_symlink():
            raise RuntimeError(f"Refusing to overwrite symlink: {dest}")
        if item.is_dir():
            _merge_dir(item, dest)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)


_BACKUP_ITEMS = (
    "server", "client", "shared", "scripts", "install.sh", "VERSION",
    "README.md", "LICENSE", "CHANGELOG.md",
)


def _validate_payload(src_root: Path) -> None:
    required = ("server/pyproject.toml", "server/inky_web/main.py", "client/dist/index.html")
    if any(not (src_root / name).is_file() for name in required) or not (src_root / "client/dist/assets").is_dir():
        raise RuntimeError("Incomplete release payload")
    if any(item.name not in _BACKUP_ITEMS for item in src_root.iterdir()):
        raise RuntimeError("Unexpected files at release root")
    if any(p.name in _NEVER_OVERWRITE or p.is_symlink() for p in src_root.rglob("*")):
        raise RuntimeError("Release contains protected runtime files or links")


def _prune_new_files(current: Path, backup: Path) -> None:
    """Remove files introduced by a failed update, preserving runtime data."""
    if current.is_dir() and not current.is_symlink():
        for child in current.iterdir():
            if child.name not in _NEVER_OVERWRITE:
                _prune_new_files(child, backup / child.name)
        if not backup.exists() and not any(current.iterdir()):
            current.rmdir()
    elif current.exists() and not backup.exists():
        current.unlink()


def _restore(backup_dir: Path, install_dir: Path) -> None:
    for name in _BACKUP_ITEMS:
        _prune_new_files(install_dir / name, backup_dir / name)
    _apply(backup_dir, install_dir)


def _backup_current(install_dir: Path, backup_dir: Path) -> None:
    backup_dir.mkdir(parents=True, exist_ok=True)
    for name in _BACKUP_ITEMS:
        src = install_dir / name
        if not src.exists():
            continue
        if src.is_dir():
            _merge_dir(src, backup_dir / name)
        else:
            shutil.copy2(src, backup_dir / name)


# ── progress + subprocess ────────────────────────────────────────────────────
def _emit(emit: EmitFn, stage: str, message: str = "", **extra: Any) -> None:
    emit(stage, message, **extra)
    if message:
        logger.info("update[%s] %s", stage, message)


async def _run_streaming(emit: EmitFn, stage: str, *cmd: str, cwd: Path | None = None) -> int:
    """Run a subprocess, streaming each stdout line as a progress event."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    assert proc.stdout is not None
    async for raw in proc.stdout:
        line = raw.decode("utf-8", "replace").rstrip()
        if line:
            _emit(emit, stage, line)
    return await proc.wait()


# ── main update routine ──────────────────────────────────────────────────────
async def perform_update(emit: EmitFn, *, install_dir: Path | None = None) -> bool:
    """Download the latest release, swap it in, refresh deps, restart.

    Returns True if the restart was triggered (the process will be killed
    shortly after), False on failure. Progress flows through ``emit``.
    """
    install_dir = install_dir or INSTALL_DIR
    lock = (install_dir / ".inky-update.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        _emit(emit, "error", "Une mise à jour est déjà en cours.")
        return False
    tmp_root = Path(tempfile.mkdtemp(prefix="inky-update-"))
    backup_dir = tmp_root / "backup"
    applied = False
    try:
        _emit(emit, "checking", "Recherche de la dernière version…")
        release = await asyncio.to_thread(_fetch_latest_release)
        if not release:
            _emit(emit, "error", "Impossible de contacter GitHub.")
            return False
        tag = str(release.get("tag_name") or "")
        version = tag.lstrip("vV")
        # The authenticated POST route calls this function directly, and Latest
        # can change after a prior status check. Check the release just fetched
        # before downloading or mutating code, dependencies and the service.
        if not _is_newer_release(__version__, version):
            _emit(
                emit, "error",
                f"Aucune mise à jour plus récente à installer (actuelle : {__version__} ; "
                f"dernière disponible : {version or 'inconnue'}). Le cadre est inchangé.",
            )
            return False
        asset = _pick_tarball_asset(release)
        if not asset:
            _emit(emit, "error", "Aucune archive (.tar.gz) dans la release.")
            return False

        _emit(emit, "downloading", f"Téléchargement de {tag}…", version=version)
        tarball = tmp_root / "release.tar.gz"
        await asyncio.to_thread(_download, asset["browser_download_url"], tarball)

        _emit(emit, "extracting", "Extraction de l'archive…", version=version)
        extracted = tmp_root / "extracted"
        await asyncio.to_thread(_safe_extract, tarball, extracted)
        src_root = _resolve_payload_root(extracted)
        _validate_payload(src_root)

        _emit(emit, "installing", "Sauvegarde de la version actuelle…", version=version)
        await asyncio.to_thread(_backup_current, install_dir, backup_dir)
        _emit(emit, "installing", "Application des nouveaux fichiers…", version=version)
        applied = True
        await asyncio.to_thread(_apply, src_root, install_dir)

        _emit(emit, "installing", "Mise à jour des dépendances Python…", version=version)
        pip = install_dir / "server" / ".venv" / "bin" / "pip"
        rc = await _run_streaming(
            emit, "installing", str(pip), "install", "--quiet", "-e",
            f"{install_dir / 'server'}[pi]",
        )
        if rc != 0:
            raise RuntimeError(f"pip install failed (exit {rc})")

        _emit(emit, "restarting", f"Redémarrage sur {tag}…", version=version)
        await asyncio.sleep(0.5)  # let the 'restarting' event flush to clients first
        # --no-block so systemctl returns before systemd tears down our cgroup.
        proc = await asyncio.create_subprocess_exec(
            "sudo", "systemctl", "--no-block", "restart", SERVICE_NAME,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        # A *negative* return code means the process was killed by a signal —
        # expected here, because the restart tears down our own cgroup and
        # SIGTERMs the sudo child. Only a *positive* exit code (e.g. sudo denied
        # = 1) is a genuine restart failure worth rolling back for.
        if proc.returncode and proc.returncode > 0:
            raise RuntimeError(
                f"service restart failed (exit {proc.returncode}): "
                f"{(out or b'').decode('utf-8', 'replace').strip()}"
            )
        return True  # systemd will kill+respawn us momentarily
    except Exception as exc:  # noqa: BLE001 — surface any failure to the UI, never crash
        logger.exception("Update failed")
        _emit(emit, "error", f"Échec de la mise à jour : {exc}")
        try:
            if applied:
                await asyncio.to_thread(_restore, backup_dir, install_dir)
                _emit(emit, "error", "Fichiers précédents restaurés. Vérifiez les dépendances Python avant de redémarrer.")
        except Exception:  # noqa: BLE001
            logger.exception("Rollback failed")
        return False
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
        lock.close()


def bus_emitter(bus: Any) -> EmitFn:
    """Build an ``emit`` callback that broadcasts ``system_update`` WS events."""

    def emit(stage: str, message: str = "", **extra: Any) -> None:
        payload: dict[str, Any] = {"stage": stage}
        if message:
            payload["message"] = message
        payload.update(extra)
        bus.broadcast("system_update", payload)

    return emit


# ── CLI entry point: `python -m inky_web.services.updater` (used by `inky-studio update`)
def main() -> int:
    def emit(stage: str, message: str = "", **extra: Any) -> None:
        version = extra.get("version")
        prefix = f"[{stage}]"
        if version and stage in {"downloading", "restarting"}:
            prefix = f"[{stage} {version}]"
        print(f"{prefix} {message}".rstrip(), flush=True)

    status = get_status(use_cache=False)
    if not status["update_available"]:
        print(
            f"Already up to date (v{status['current']}; "
            f"latest: {status['latest'] or 'unknown'})."
        )
        return 0
    print(f"Updating v{status['current']} → v{status['latest']}…")
    ok = asyncio.run(perform_update(emit))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
