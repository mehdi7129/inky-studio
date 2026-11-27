#!/usr/bin/env python3
"""Produce an offline candidate from a Git commit and prebuilt local inputs.

No install, backend import, service or network access. This packages declared
compatibility; only a separate target installation can demonstrate it.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import tarfile
import tempfile
import tomllib
from pathlib import Path, PurePosixPath

from offline_wheels import build_wheelhouse

MAX_FILE = 128 * 1024 * 1024
MAX_CONTENT = 512 * 1024 * 1024
MAX_FILES = 10000
TOP_FILES = {"install.sh", "README.md", "LICENSE", "CHANGELOG.md"}
EXCLUDED = {"tests", "__pycache__", ".venv", ".env", ".env.local", ".git", "data", "node_modules"}


def git(repo: Path, *args: str) -> bytes:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    return subprocess.check_output(["git", "--no-replace-objects", "--no-lazy-fetch", "-C", str(repo), *args],
                                   env=env, stderr=subprocess.PIPE)


def read_regular(name: str, directory: int) -> bytes:
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE:
            raise ValueError("Frontend requires bounded regular files")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            data = stream.read(MAX_FILE + 1)
        after = os.fstat(descriptor)
        if len(data) > MAX_FILE or len(data) != before.st_size or (
            before.st_size, before.st_mtime_ns, before.st_ctime_ns
        ) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("Frontend changed during read")
        return data
    finally:
        os.close(descriptor)


def source_files(repo: Path, commit: str) -> dict[str, tuple[bytes, int]]:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("A full immutable source commit is required")
    if git(repo, "rev-parse", f"{commit}^{{commit}}").decode().strip() != commit:
        raise ValueError("Source does not identify a commit")
    result = {}
    total = 0
    for entry in git(repo, "ls-tree", "-r", "-z", commit).split(b"\0"):
        if not entry:
            continue
        header, raw_path = entry.split(b"\t", 1)
        mode, kind, blob = header.decode().split()
        name = raw_path.decode("utf-8")
        path = PurePosixPath(name)
        if path.parts[0] not in {"server", "shared", "scripts"} and name not in TOP_FILES:
            continue
        if any(part in EXCLUDED or part.endswith(".egg-info") for part in path.parts):
            continue
        if mode not in {"100644", "100755"} or kind != "blob":
            raise ValueError(f"Unsupported source entry: {name}")
        if path.is_absolute() or ".." in path.parts or str(path) != name:
            raise ValueError("Unsafe source path")
        size = int(git(repo, "cat-file", "-s", blob))
        total += size
        if size > MAX_FILE or total > MAX_CONTENT or len(result) >= MAX_FILES:
            raise ValueError("Source payload exceeds limits")
        result[name] = (git(repo, "cat-file", "blob", blob), 0o755 if mode == "100755" else 0o644)
    required = {"server/pyproject.toml", "server/README.md", "server/inky_web/__init__.py",
                "server/inky_web/main.py", "scripts/inky-studio-cli", "scripts/inky-studio-launcher",
                "scripts/inky-network-helper.py", "scripts/install-bluetooth.sh", "install.sh", "LICENSE"}
    if not required <= result.keys():
        raise ValueError(f"Incomplete application source: {sorted(required - result.keys())}")
    return result


def frontend_files(dist: Path) -> dict[str, tuple[bytes, int]]:
    if dist.is_symlink() or not dist.is_dir():
        raise ValueError("Frontend must be a regular directory")
    result = {}
    total = 0
    def fail(error):
        raise error

    for parent, dirs, files, directory in os.fwalk(dist, follow_symlinks=False, onerror=fail):
        if any(name in EXCLUDED or name.startswith(".env.") for name in dirs + files):
            raise ValueError("Frontend contains protected runtime files")
        for name in dirs:
            if (Path(parent) / name).is_symlink():
                raise ValueError("Frontend symlinks are not permitted")
        for name in files:
            path = Path(parent) / name
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("Frontend requires regular files")
            data = read_regular(name, directory)
            total += len(data)
            if total > MAX_CONTENT or len(result) >= MAX_FILES:
                raise ValueError("Frontend exceeds limits")
            result[f"client/dist/{path.relative_to(dist).as_posix()}"] = (data, 0o644)
    if "client/dist/index.html" not in result or not any(name.startswith("client/dist/assets/") for name in result):
        raise ValueError("Built frontend index.html or assets are missing")
    return result


def application_archive(files: dict[str, tuple[bytes, int]], path: Path, epoch: int) -> None:
    if len(files) > MAX_FILES or sum(len(data) for data, _ in files.values()) > MAX_CONTENT:
        raise ValueError("Application archive exceeds limits")
    # Fixed metadata and gzip header: same inputs produce identical bytes.
    with path.open("xb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for name, (data, mode) in sorted(files.items()):
                member = tarfile.TarInfo(name)
                member.size = len(data)
                member.mode = mode
                member.mtime = epoch
                archive.addfile(member, io.BytesIO(data))


def build_bundle(repo: Path, commit: str, dist: Path, frontend_commit: str,
                 wheels: Path, provenance: Path, output: Path) -> Path:
    if frontend_commit != commit:
        raise ValueError("Frontend and application must come from the same commit")
    if output.exists() or output.is_symlink():
        raise ValueError("Output already exists")
    files = source_files(repo, commit)
    project = tomllib.loads(files["server/pyproject.toml"][0].decode())
    module = files["server/inky_web/__init__.py"][0].decode()
    match = re.search(r'^__version__ = "([^"]+)"$', module, re.M)
    if not match or not re.fullmatch(r"\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.\d+)?", match[1]):
        raise ValueError("Unsupported application release version")
    version = match[1]
    pep_version = re.sub(r"-(alpha|beta|rc)\.(\d+)$",
                         lambda m: {"alpha": "a", "beta": "b", "rc": "rc"}[m[1]] + m[2], version)
    if project["project"]["version"] != pep_version:
        raise ValueError("API and package versions disagree")
    epoch = int(git(repo, "show", "-s", "--format=%ct", commit))
    files.update(frontend_files(dist))
    files["VERSION"] = (f"v{version}\n".encode(), 0o644)
    # Older installed updaters allow only known top-level paths.
    files["server/SOURCE_COMMIT"] = (f"{commit}\n".encode(), 0o644)
    output.parent.mkdir(parents=True, exist_ok=True)
    # The public directory appears only after all validation succeeds.
    with tempfile.TemporaryDirectory(prefix=".inky-offline-", dir=output.parent) as temporary:
        stage = Path(temporary) / "bundle"
        stage.mkdir()
        project_input = Path(temporary) / "pyproject.toml"
        project_input.write_bytes(files["server/pyproject.toml"][0])
        wheelhouse, lock = build_wheelhouse(wheels, provenance, project_input, stage, commit, epoch)
        application = stage / f"inky-studio-v{version}.tar.gz"
        application_archive(files, application, epoch)
        assets = [{"role": role, "filename": asset.name, "size_bytes": asset.stat().st_size,
                   "sha256": hashlib.sha256(asset.read_bytes()).hexdigest()}
                  for role, asset in (("application", application), ("wheelhouse", wheelhouse), ("python_lock", lock))]
        contracts = {"http_contract": "server/inky_web",
                     "ble_contract": "docs/ios/BLE-PROTOCOL-V1.md",
                     "network_helper_contract": "scripts/inky-network-helper.py"}
        manifest = {"schema_version": 1, "application_version": version, "source_commit": commit,
                    "assets": assets, "compatibility": {"architecture": "arm64", "python_minor": "3.13",
                    "debian_release": "trixie", **{key: f"git:{commit}#{value}" for key, value in contracts.items()}},
                    "qualification": {"evidence": []}}
        (stage / "inky-studio-manifest-v1.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        if output.exists() or output.is_symlink():
            raise ValueError("Output appeared during packaging")
        stage.rename(output)
    return output / "inky-studio-manifest-v1.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--client-dist", type=Path, required=True)
    parser.add_argument("--frontend-source-commit", required=True,
                        help="Commit of the separately built frontend; producer declaration, not a build attestation")
    parser.add_argument("--wheel-dir", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build_bundle(args.repo, args.source_commit, args.client_dist, args.frontend_source_commit,
                              args.wheel_dir, args.provenance, args.output)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Packaging refused: {exc}\n")
    print(result)
    print("Candidate integrity only; target installation and physical qualification are separate.")


if __name__ == "__main__":
    main()
