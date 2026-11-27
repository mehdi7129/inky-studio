"""Run the real fetch/CLI bootstrap stages through stdin, with no sudo or services.

The legacy CLI fixture is byte-for-byte from the distributed v0.4.2 archive,
not a reimplementation. Tests don't need Git history, network access or a Pi.
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
from configparser import ConfigParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LEGACY_CLI = Path(__file__).parent / "fixtures/inky-studio-cli-v0.4.2.sh"
LEGACY_SHA256 = "c335490ea59c0bf8eb6b3cbbbd1ed9850a688c960214566e912abadd8bc86b6c"
LEGACY_LAUNCHER = Path(__file__).parent / "fixtures/inky-studio-launcher-5671.sh"
LEGACY_LAUNCHER_SHA256 = "cce76b87092a9186085ed1ee422437ee208fa478ba527f863134dcaf1e9a0d4e"


def _stage(start, end):
    source = (ROOT / "install.sh").read_text()
    return source[source.index(start):source.index(end)]


def _environment(tmp_path, install_dir, data_dir):
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("INKY_STUDIO_")}
    return {
        **environment, "TEST_REAL_PYTHON": sys.executable,
        "TEST_INSTALL_DIR": str(install_dir), "TEST_DATA_DIR": str(data_dir),
        "TEST_INSTALLED_LAUNCHER": str(tmp_path / "installed-launcher"),
        "TEST_SUDO_LOG": str(tmp_path / "sudo.json"),
        "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}",
    }


def _script(path, source):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    path.chmod(0o755)


def _cli_stage(tmp_path, install_dir, data_dir, repo_slug="fixture/inky", *, environment_overrides=None):
    _script(tmp_path / "bin/sudo", '''#!/usr/bin/env bash
exec "$TEST_REAL_PYTHON" -c 'import json, os, pathlib, shutil, sys
args = sys.argv[1:]
assert args[:7] == ["install", "-o", "root", "-g", "root", "-m", "0755"]
assert args[-1] == "/usr/local/bin/inky-studio"
pathlib.Path(os.environ["TEST_SUDO_LOG"]).write_text(json.dumps(args))
shutil.copyfile(args[-2], os.environ["TEST_INSTALLED_LAUNCHER"])
' "$@"
''')
    script = '''set -euo pipefail
INSTALL_DIR="$TEST_INSTALL_DIR"
DATA_DIR="$TEST_DATA_DIR"
REPO_SLUG="$INKY_STUDIO_REPO_SLUG"
say() { printf '%s\n' "$*"; }
''' + _stage("# ── 10. CLI wrapper", "# ── 11. systemd unit")
    # stdin mirrors curl | bash: no installer path/BASH_SOURCE is available.
    return subprocess.run(
        ["bash"], input=script, cwd=tmp_path,
        env={**_environment(tmp_path, install_dir, data_dir), "INKY_STUDIO_REPO_SLUG": repo_slug,
             **(environment_overrides or {})},
        text=True, capture_output=True,
    )


def test_legacy_release_bootstrap_uses_literal_non_pi_paths_and_stable_dispatch(tmp_path):
    assert hashlib.sha256(LEGACY_CLI.read_bytes()).hexdigest() == LEGACY_SHA256
    special = " ' \" $HOME $(touch EXPANDED) `touch BACKTICKED` # \\\n"
    install_dir = tmp_path / "home/alice" / ("inky studio" + special)
    data_dir = tmp_path / ("data" + special)
    cli = install_dir / "scripts/inky-studio-cli"
    cli.parent.mkdir(parents=True)
    shutil.copyfile(LEGACY_CLI, cli)
    assert not (cli.parent / "inky-studio-launcher").exists()
    _script(install_dir / "server/.venv/bin/python", '''#!/usr/bin/env bash
exec "$TEST_REAL_PYTHON" -c 'import json,os,sys; print(json.dumps({
"install":os.environ["INKY_STUDIO_INSTALL_DIR"],
"data":os.environ["INKY_STUDIO_DATA_DIR"],
"repo":os.environ["INKY_STUDIO_REPO_SLUG"], "args":sys.argv[1:]}))' "$@"
''')
    result = _cli_stage(tmp_path, install_dir, data_dir)
    assert result.returncode == 0, result.stderr
    launcher = tmp_path / "installed-launcher"
    assert not Path(json.loads((tmp_path / "sudo.json").read_text())[-2]).exists()
    environment = _environment(tmp_path, install_dir, data_dir)
    result = subprocess.run(["bash", str(launcher), "update"], env=environment,
                            cwd=tmp_path, text=True, capture_output=True, check=True)
    assert json.loads(result.stdout) == {
        "install": str(install_dir), "data": str(data_dir),
        "repo": "fixture/inky",
        "args": ["-m", "inky_web.services.updater"],
    }
    assert not (tmp_path / "EXPANDED").exists()
    assert not (tmp_path / "BACKTICKED").exists()

    for override in ("another-owner/.github", ""):
        overridden = subprocess.run(
            ["bash", str(launcher), "update"],
            env={**environment, "INKY_STUDIO_REPO_SLUG": override}, cwd=tmp_path,
            text=True, capture_output=True, check=True,
        )
        assert json.loads(overridden.stdout)["repo"] == override

    original = launcher.read_bytes()
    cli.write_text('#!/usr/bin/env bash\nprintf "next-release\\n"\nexit 23\n')
    updated = subprocess.run(["bash", str(launcher), "help"], env=environment,
                             cwd=tmp_path, text=True, capture_output=True)
    assert updated.returncode == 23
    assert updated.stdout == "next-release\n"
    assert launcher.read_bytes() == original


def test_bootstrap_does_not_execute_a_payload_launcher_generator(tmp_path):
    install_dir, data_dir = tmp_path / "app", tmp_path / "data"
    helper = install_dir / "scripts/inky-studio-launcher"
    _script(helper, '#!/usr/bin/env bash\nprintf "payload-generator:%s\\n" "$INKY_STUDIO_REPO_SLUG"\nexit 29\n')
    _script(install_dir / "scripts/inky-studio-cli", '#!/usr/bin/env bash\nexit 0\n')
    result = _cli_stage(tmp_path, install_dir, data_dir)
    assert result.returncode == 0, result.stderr
    assert "payload-generator" not in result.stdout
    assert (tmp_path / "installed-launcher").exists()
    assert (tmp_path / "sudo.json").exists()


@pytest.mark.parametrize("historical", [False, True])
def test_bootstrap_preserves_repository_with_current_or_historical_payload_generator(tmp_path, historical):
    install_dir, data_dir = tmp_path / "app", tmp_path / "data"
    scripts = install_dir / "scripts"
    scripts.mkdir(parents=True)
    assert hashlib.sha256(LEGACY_LAUNCHER.read_bytes()).hexdigest() == LEGACY_LAUNCHER_SHA256
    generator = scripts / "inky-studio-launcher"
    shutil.copyfile(LEGACY_LAUNCHER if historical else ROOT / "scripts/inky-studio-launcher", generator)
    # Reject and record any attempt to delegate to a downloaded generator.
    # The historical fixture itself remains byte-for-byte unchanged.
    _script(tmp_path / "bin/bash", '''#!/bin/bash
if [[ "${1-}" == "$TEST_PAYLOAD_GENERATOR" ]]; then
  printf "unexpected payload generator\\n" > "$TEST_GENERATOR_LOG"
  exit 89
fi
exec /bin/bash "$@"
''')
    generator_log = tmp_path / "payload-generator-executed"
    watchdog = {"TEST_PAYLOAD_GENERATOR": str(generator), "TEST_GENERATOR_LOG": str(generator_log)}
    control = subprocess.run(
        [str(tmp_path / "bin/bash"), str(generator), "--print", str(install_dir), str(data_dir)],
        env={**_environment(tmp_path, install_dir, data_dir), **watchdog},
        text=True, capture_output=True,
    )
    assert control.returncode == 89 and generator_log.exists()
    generator_log.unlink()
    _script(scripts / "inky-studio-cli", '#!/usr/bin/env bash\nprintf "%s\\n" "$INKY_STUDIO_REPO_SLUG"\n')
    result = _cli_stage(tmp_path, install_dir, data_dir, repo_slug="release-owner/.github",
                        environment_overrides=watchdog)
    assert result.returncode == 0, result.stderr
    assert not generator_log.exists()
    launcher = tmp_path / "installed-launcher"
    environment = {**_environment(tmp_path, install_dir, data_dir), **watchdog}
    for override, expected in ((None, "release-owner/.github"), ("override/repo", "override/repo"), ("", "")):
        runtime = environment if override is None else {**environment, "INKY_STUDIO_REPO_SLUG": override}
        run = subprocess.run(["bash", str(launcher), "update"], env=runtime,
                             text=True, capture_output=True, check=True)
        assert run.stdout == expected + "\n"
    original_launcher = launcher.read_bytes()
    _script(scripts / "inky-studio-cli", '#!/usr/bin/env bash\nprintf "next-release:%s\\n" "$INKY_STUDIO_REPO_SLUG"\n')
    updated = subprocess.run(["bash", str(launcher), "update"],
                             env={**environment, **watchdog}, text=True, capture_output=True, check=True)
    assert updated.stdout == "next-release:release-owner/.github\n"
    assert launcher.read_bytes() == original_launcher
    assert not generator_log.exists()
    if historical:
        assert generator.read_bytes() == LEGACY_LAUNCHER.read_bytes()


@pytest.mark.parametrize("repo_slug", [
    None, "", " owner/repo", "owner/repo ", "owner/repo\n", "owner/repo/extra",
    "https://github.com/owner/repo", "owner/repo?token=x", "owner/repo#branch",
    "owner/repo%2Fother", "owner\\repo", "owner name/repo", "owñer/repo",
    "owner/répo", "-owner/repo", "owner-/repo", "own--er/repo", "owner.name/repo",
    "owner_name/repo", "owner/.", "owner/..", "o" * 40 + "/repo", "owner/" + "r" * 101,
    "owner/$(touch EXPANDED)", "owner/`touch BACKTICKED`", 'owner/repo";touch INJECTED',
])
def test_installer_rejects_unconfigured_or_invalid_repository_before_any_external_command(tmp_path, repo_slug):
    log = tmp_path / "external-command"
    for command in ("id", "getent", "sudo", "apt-get", "curl", "git", "install", "tee", "mktemp", "mkdir"):
        _script(tmp_path / "bin" / command,
                '#!/usr/bin/env bash\nprintf "%s\\n" "$0" >> "$TEST_COMMAND_LOG"\nexit 99\n')
    environment = {
        **_environment(tmp_path, tmp_path / "installation", tmp_path / "data"),
        "TEST_COMMAND_LOG": str(log),
    }
    if repo_slug is not None:
        environment["INKY_STUDIO_REPO_SLUG"] = repo_slug
    result = subprocess.run(["bash", str(ROOT / "install.sh")], env=environment,
                            cwd=tmp_path, text=True, capture_output=True)
    assert result.returncode == 2
    assert "INKY_STUDIO_REPO_SLUG" in result.stderr
    assert not log.exists()
    assert not (tmp_path / "installation").exists()
    assert not (tmp_path / "data").exists()
    assert not (tmp_path / "EXPANDED").exists()
    assert not (tmp_path / "BACKTICKED").exists()
    assert not (tmp_path / "INJECTED").exists()


@pytest.mark.parametrize("repo_slug", [
    "o/r", "Owner-1/repository_name.git", "release-owner/.github",
    "o" * 39 + "/" + "r" * 100,
])
def test_installer_accepts_explicit_repository_without_canonicalising(tmp_path, repo_slug):
    source = (ROOT / "install.sh").read_text()
    validation = source[:source.index('CHANNEL="${INKY_STUDIO_CHANNEL')]
    result = subprocess.run(
        ["bash"], input=validation + '\nprintf "%s\\n" "$REPO_SLUG"\n',
        env={**_environment(tmp_path, tmp_path / "app", tmp_path / "data"), "INKY_STUDIO_REPO_SLUG": repo_slug},
        text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == repo_slug + "\n"


@pytest.mark.parametrize("relative", [False, True])
def test_fallback_rejects_missing_cli_or_relative_paths_without_sudo(tmp_path, relative):
    install_dir = Path("relative") if relative else tmp_path / "absent"
    result = _cli_stage(tmp_path, install_dir, tmp_path / "data")
    assert result.returncode == (2 if relative else 1)
    assert not (tmp_path / "sudo.json").exists()


def _fetch_stage(tmp_path, current=None, latest="v0.4.2"):
    install_dir = tmp_path / "home/alice/inky-studio"
    if current is not None:
        module = install_dir / "server/inky_web/__init__.py"
        module.parent.mkdir(parents=True)
        module.write_text(f'__version__ = {current!r}\n'
                          'raise RuntimeError("Installed code must never be imported")\n')
        (install_dir / "keep.txt").write_text("preserve me")
    payload = tmp_path / "payload"
    (payload / "server/inky_web").mkdir(parents=True)
    (payload / "server/inky_web/__init__.py").write_text('__version__ = "0.4.2"\n')
    (payload / "scripts").mkdir()
    shutil.copyfile(LEGACY_CLI, payload / "scripts/inky-studio-cli")
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        output.add(payload, arcname=".")
    curl_stub = tmp_path / "curl.py"
    curl_stub.write_text('''import json,os,pathlib,shutil,sys
args=sys.argv[1:]
with open(os.environ["TEST_FETCH_LOG"],"a") as log: log.write(json.dumps(args)+"\\n")
if args[-1].endswith("/releases/latest"):
 print(json.dumps({"tag_name":os.environ["TEST_LATEST"],"assets":[{
  "name":"inky-studio.tar.gz","browser_download_url":"https://example.test/release.tar.gz"}]}))
elif args[-1] == "https://example.test/release.tar.gz" and "-o" in args:
 shutil.copyfile(os.environ["TEST_ARCHIVE"],args[args.index("-o")+1])
else: raise SystemExit("Unexpected network request")
''')
    _script(tmp_path / "bin/curl", '#!/usr/bin/env bash\nexec "$TEST_REAL_PYTHON" "$TEST_CURL_STUB" "$@"\n')
    _script(tmp_path / "bin/python3", '#!/usr/bin/env bash\nexec "$TEST_REAL_PYTHON" "$@"\n')
    _script(tmp_path / "bin/git", '#!/usr/bin/env bash\nprintf source-fallback > "$TEST_SOURCE_LOG"\nexit 77\n')
    # Even a regression that enters source fallback on a machine with an older
    # Node must never reach real sudo or package installation from this test.
    _script(tmp_path / "bin/sudo", '#!/usr/bin/env bash\nprintf "Unexpected privileged command\\n" >&2\nexit 90\n')
    script = '''set -euo pipefail
INSTALL_DIR="$TEST_INSTALL_DIR"
REPO_SLUG=fixture/inky
REPO_URL=https://example.test/source.git
CHANNEL=release
say() { printf '%s\n' "$*"; }
''' + _stage("# ── 6. Fetch the code", "# ── 7. Python venv")
    environment = {
        **_environment(tmp_path, install_dir, tmp_path / "data"),
        "TEST_CURL_STUB": str(curl_stub), "TEST_ARCHIVE": str(archive),
        "TEST_LATEST": latest, "TEST_FETCH_LOG": str(tmp_path / "fetch.jsonl"),
        "TEST_SOURCE_LOG": str(tmp_path / "source-fallback"),
    }
    result = subprocess.run(["bash"], input=script, cwd=tmp_path, env=environment,
                            text=True, capture_output=True)
    requests = [json.loads(line) for line in (tmp_path / "fetch.jsonl").read_text().splitlines()]
    assert requests[0][-1] == "https://api.github.com/repos/fixture/inky/releases/latest"
    return result, install_dir, requests


@pytest.mark.parametrize("current", ["0.5.0-rc.1", "0.5.0rc1", "0.5.0"])
def test_newer_install_blocks_downgrade_before_copy_without_source_fallback(tmp_path, current):
    result, install_dir, requests = _fetch_stage(tmp_path, current=current)
    assert result.returncode == 1
    assert "refusing to replace" in result.stderr
    assert "No application files were copied" in result.stderr
    assert len(requests) == 1  # Metadata only; no archive download or moving main.
    assert current in (install_dir / "server/inky_web/__init__.py").read_text()
    assert (install_dir / "keep.txt").read_text() == "preserve me"
    assert not (tmp_path / "source-fallback").exists()
    assert not (install_dir / "VERSION").exists()


@pytest.mark.parametrize("current", [None, "0.4.2", "0.4.1"])
def test_fresh_install_same_version_repair_and_upgrade_are_allowed(tmp_path, current):
    result, install_dir, requests = _fetch_stage(tmp_path, current=current)
    assert result.returncode == 0, result.stderr
    assert len(requests) == 2
    assert (install_dir / "VERSION").read_text().strip() == "v0.4.2"
    assert (install_dir / "scripts/inky-studio-cli").read_bytes() == LEGACY_CLI.read_bytes()
    assert not (install_dir / "scripts/inky-studio-launcher").exists()
    assert not (tmp_path / "source-fallback").exists()


@pytest.mark.parametrize("source_url", [None, "https://example.test/explicit-source.git"])
def test_source_fetch_uses_configured_repository_without_default_account(tmp_path, source_url):
    install_dir = tmp_path / "installation"
    environment = {
        **_environment(tmp_path, install_dir, tmp_path / "data"),
        "INKY_STUDIO_REPO_SLUG": "source-owner/inky-studio",
        "INKY_STUDIO_USER": "fixture", "INKY_STUDIO_INSTALL_DIR": str(install_dir),
        "INKY_STUDIO_CHANNEL": "source", "TEST_SOURCE_LOG": str(tmp_path / "source.jsonl"),
    }
    if source_url is not None:
        environment["INKY_STUDIO_REPO"] = source_url
    _script(tmp_path / "bin/id", '#!/usr/bin/env bash\nprintf "fixture\\n"\n')
    _script(tmp_path / "bin/getent", '#!/usr/bin/env bash\nprintf "fixture:x:1000:1000::/home/fixture:/bin/bash\\n"\n')
    _script(tmp_path / "bin/node", '#!/usr/bin/env bash\nexit 0\n')
    _script(tmp_path / "bin/sudo", '#!/usr/bin/env bash\nexit 90\n')
    _script(tmp_path / "bin/git", '''#!/usr/bin/env bash
exec "$TEST_REAL_PYTHON" -c 'import json,os,pathlib,sys
args=sys.argv[1:]
assert args[:2] == ["clone", "--depth=1"]
pathlib.Path(os.environ["TEST_SOURCE_LOG"]).write_text(json.dumps(args))
(pathlib.Path(args[-1])/"client").mkdir(parents=True)
' "$@"
''')
    _script(tmp_path / "bin/npm", '#!/usr/bin/env bash\nexit 0\n')
    source = (ROOT / "install.sh").read_text()
    script = source[:source.index('SERVICE_NAME="inky-studio.service"')]
    script += '\nsay() { :; }\n' + _stage("fetch_source() {", 'if [[ "${CHANNEL}" == "source" ]]')
    script += '\nfetch_source\n'
    result = subprocess.run(["bash"], input=script, env=environment,
                            cwd=tmp_path, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert json.loads((tmp_path / "source.jsonl").read_text()) == [
        "clone", "--depth=1", source_url or "https://github.com/source-owner/inky-studio.git", str(install_dir),
    ]


def test_emitted_service_drains_main_process_without_forced_deadline(tmp_path):
    """Exercise the real heredoc through stdin without writing a host unit."""
    _script(tmp_path / "bin/sudo", '''#!/usr/bin/env bash
if [[ "$1" != tee || "$2" != /etc/systemd/system/inky-studio.service ]]; then
    exit 90
fi
cat > "$TEST_UNIT_OUTPUT"
''')
    environment = {
        **_environment(tmp_path, tmp_path / "app", tmp_path / "data"),
        "TEST_UNIT_OUTPUT": str(tmp_path / "inky-studio.service"),
    }
    script = '''set -euo pipefail
INSTALL_DIR="$TEST_INSTALL_DIR"
DATA_DIR="$TEST_DATA_DIR"
REPO_SLUG=fixture/inky
SERVICE_NAME=inky-studio.service
RUN_USER=fixture
say() { :; }
''' + _stage("# ── 11. systemd unit", "sudo systemctl daemon-reload")
    result = subprocess.run(["bash"], input=script, cwd=tmp_path,
                            env=environment, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    unit = ConfigParser(interpolation=None, strict=False)
    unit.read(tmp_path / "inky-studio.service")
    # ConfigParser keeps only the last Environment= occurrence. Verify all
    # emitted assignments separately, without touching the host's systemd.
    environments = [
        assignment
        for line in (tmp_path / "inky-studio.service").read_text().splitlines()
        if line.startswith("Environment=")
        for assignment in shlex.split(line.partition("=")[2])
    ]
    assert environments == [
        f"INKY_STUDIO_DATA_DIR={tmp_path}/data",
        "INKY_STUDIO_REPO_SLUG=fixture/inky",
        "INKY_STUDIO_DISPLAY_MODE=hardware",
    ]
    service = unit["Service"]
    assert service["ExecStart"] == f"{tmp_path}/app/server/.venv/bin/inky-studio-server"
    assert service["KillSignal"] == "SIGTERM"
    assert service["KillMode"] == "mixed"
    assert service["TimeoutStopSec"] == "infinity"
    assert not service.getboolean("SendSIGKILL")
    assert "ExecStop" not in service  # The main process owns drain completion.
