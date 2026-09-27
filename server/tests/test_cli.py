"""Exercise the installed wrapper with harmless stub executables."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from inky_web import auth


def _generate_launcher(tmp_path, install_dir, data_dir):
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["bash", str(root / "scripts/inky-studio-launcher"), "--print", str(install_dir), str(data_dir)],
        text=True, capture_output=True, check=True,
    )
    launcher = tmp_path / "inky-studio"
    launcher.write_text(result.stdout)
    launcher.chmod(0o755)
    return launcher


def _launcher_environment(**overrides):
    environment = {key: value for key, value in os.environ.items()
                   if key not in {"INKY_STUDIO_INSTALL_DIR", "INKY_STUDIO_DATA_DIR"}}
    return {**environment, "TEST_REAL_PYTHON": sys.executable, **overrides}


def _write_reporting_cli(directory, *, version="one", status=0):
    cli = directory / "scripts/inky-studio-cli"
    cli.parent.mkdir(parents=True, exist_ok=True)
    cli.write_text(
        '#!/usr/bin/env bash\n'
        '"$TEST_REAL_PYTHON" -c \'import json, os, sys; print(json.dumps({'
        '"install": os.environ["INKY_STUDIO_INSTALL_DIR"], '
        '"data": os.environ["INKY_STUDIO_DATA_DIR"], "args": sys.argv[1:]}))\' "$@"\n'
        f'printf "%s\\n" "{version}"\nexit {status}\n'
    )
    # The dispatcher intentionally invokes Bash, so a restored payload only needs
    # to be readable; no execute bit or shell interpretation of its path is needed.
    cli.chmod(0o644)
    return cli


def test_stable_launcher_preserves_literal_paths_arguments_and_future_updates(tmp_path):
    special = " ' \" $HOME $(touch EXPANDED) `touch BACKTICKED` # \\\n"
    install_dir = tmp_path / ("installation" + special)
    data_dir = tmp_path / ("données" + special)
    _write_reporting_cli(install_dir)
    launcher = _generate_launcher(tmp_path, install_dir, data_dir)
    original_launcher = launcher.read_bytes()
    arguments = ["reset-password", "two words", "", "--", "$(touch ARGUMENT_EXPANDED)"]
    result = subprocess.run(
        ["bash", str(launcher), *arguments], cwd=tmp_path,
        env=_launcher_environment(), text=True, capture_output=True, check=True,
    )
    assert json.loads(result.stdout.splitlines()[0]) == {
        "install": str(install_dir), "data": str(data_dir), "args": arguments,
    }
    assert result.stdout.splitlines()[1] == "one"
    assert not (tmp_path / "EXPANDED").exists()
    assert not (tmp_path / "BACKTICKED").exists()
    assert not (tmp_path / "ARGUMENT_EXPANDED").exists()

    # Model a future release replacing the repo script, without touching /usr/local.
    _write_reporting_cli(install_dir, version="two", status=23)
    result = subprocess.run(
        ["bash", str(launcher), "help"], cwd=tmp_path,
        env=_launcher_environment(), text=True, capture_output=True,
    )
    assert result.returncode == 23
    assert result.stdout.splitlines()[1] == "two"
    assert launcher.read_bytes() == original_launcher


def test_stable_launcher_keeps_environment_overrides_and_reports_missing_payload(tmp_path):
    default_install = tmp_path / "missing-default"
    default_data = tmp_path / "default-data"
    override_install = tmp_path / "custom install"
    override_data = tmp_path / "custom data"
    _write_reporting_cli(override_install)
    launcher = _generate_launcher(tmp_path, default_install, default_data)
    result = subprocess.run(
        ["bash", str(launcher), "password"], text=True, capture_output=True, check=True,
        env=_launcher_environment(INKY_STUDIO_INSTALL_DIR=str(override_install), INKY_STUDIO_DATA_DIR=str(override_data)),
    )
    assert json.loads(result.stdout.splitlines()[0]) == {
        "install": str(override_install), "data": str(override_data), "args": ["password"],
    }
    missing = subprocess.run(
        ["bash", str(launcher), "reset-password"], env=_launcher_environment(),
        text=True, capture_output=True,
    )
    assert missing.returncode == 127
    assert str(default_install / "scripts/inky-studio-cli") in missing.stderr
    assert "No service was changed" in missing.stderr
    assert not default_install.exists()
    assert not default_data.exists()


def test_launcher_install_uses_root_owned_permissions_without_running_cli_or_services(tmp_path):
    root = Path(__file__).resolve().parents[2]
    install_dir = tmp_path / "install 'quoted'"
    data_dir = tmp_path / "data with spaces"
    _write_reporting_cli(install_dir)
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    sudo = fake_bin / "sudo"
    # Observe the privileged command and redirect the copy into this test's tree.
    # This is the only fake privileged command; no real sudo or systemctl runs.
    sudo.write_text(
        '#!/usr/bin/env bash\n'
        'exec "$TEST_REAL_PYTHON" -c \'import json, os, pathlib, shutil, sys; '
        'args = sys.argv[1:]; '
        'pathlib.Path(os.environ["TEST_SUDO_LOG"]).write_text(json.dumps(args)); '
        'assert args[:7] == ["install", "-o", "root", "-g", "root", "-m", "0755"]; '
        'assert args[-1] == "/usr/local/bin/inky-studio"; '
        'shutil.copyfile(args[-2], os.environ["TEST_INSTALLED_LAUNCHER"]); '
        'os.chmod(os.environ["TEST_INSTALLED_LAUNCHER"], 0o755)\' "$@"\n'
    )
    sudo.chmod(0o755)
    installed = tmp_path / "installed-launcher"
    log = tmp_path / "sudo.json"
    result = subprocess.run(
        ["bash", str(root / "scripts/inky-studio-launcher"), "--install", str(install_dir), str(data_dir)],
        env=_launcher_environment(PATH=f"{fake_bin}:{os.environ['PATH']}", TEST_SUDO_LOG=str(log),
                                  TEST_INSTALLED_LAUNCHER=str(installed)),
        text=True, capture_output=True, check=True,
    )
    assert "Installed stable" in result.stdout
    command = json.loads(log.read_text())
    assert not Path(command[-2]).exists(), "Private staging file must be removed after installation."
    report = subprocess.run(
        ["bash", str(installed), "help"], env=_launcher_environment(),
        text=True, capture_output=True, check=True,
    )
    assert json.loads(report.stdout.splitlines()[0]) == {
        "install": str(install_dir), "data": str(data_dir), "args": ["help"],
    }


@pytest.mark.parametrize("arguments", [[], ["--other", "/install", "/data"], ["--print", "relative", "/data"]])
def test_launcher_generator_rejects_invalid_usage(tmp_path, arguments):
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["bash", str(root / "scripts/inky-studio-launcher"), *arguments], cwd=tmp_path,
        text=True, capture_output=True,
    )
    assert result.returncode == 2
    assert result.stderr


def test_update_uses_existing_module(tmp_path):
    root = Path(__file__).resolve().parents[2]
    python = tmp_path / "server/.venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
    python.chmod(0o755)
    result = subprocess.run(
        ["bash", str(root / "scripts/inky-studio-cli"), "update"],
        env={**os.environ, "INKY_STUDIO_INSTALL_DIR": str(tmp_path)},
        text=True, capture_output=True, check=True,
    )
    assert result.stdout.splitlines() == ["-m", "inky_web.services.updater"]


def test_failed_welcome_restarts_service(tmp_path):
    root = Path(__file__).resolve().parents[2]
    python = tmp_path / "server/.venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\nexit 7\n")
    python.chmod(0o755)
    sudo = tmp_path / "sudo"
    sudo.write_text('#!/bin/sh\nprintf "%s\\n" "$*"\n')
    sudo.chmod(0o755)
    result = subprocess.run(
        ["bash", str(root / "scripts/inky-studio-cli"), "welcome"],
        env={**os.environ, "INKY_STUDIO_INSTALL_DIR": str(tmp_path), "PATH": f"{tmp_path}:{os.environ['PATH']}"},
        text=True, capture_output=True,
    )
    assert result.returncode == 7
    assert result.stdout.splitlines() == [
        "systemctl stop inky-studio.service", "systemctl start inky-studio.service",
    ]


def test_previously_installed_updater_entrypoint_delegates_without_network():
    root = Path(__file__).resolve().parents[2]
    code = """
import runpy
from inky_web.services import updater

def fake_main():
    print("delegated to current updater")
    return 7

updater.main = fake_main
runpy.run_module("inky_web.updater", run_name="__main__")
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=root / "server",
        text=True, capture_output=True,
    )
    assert result.returncode == 7
    assert result.stdout.strip() == "delegated to current updater"


def _password_cli(tmp_path, command, *, fail_python=False):
    root = Path(__file__).resolve().parents[2]
    python = tmp_path / "install/server/.venv/bin/python"
    python.parent.mkdir(parents=True, exist_ok=True)
    if fail_python:
        python.write_text("#!/bin/sh\nexit 7\n")
        python.chmod(0o755)
    else:
        python.write_text('#!/bin/sh\nexec "$TEST_REAL_PYTHON" "$@"\n')
        python.chmod(0o755)
    sudo = tmp_path / "sudo"
    sudo.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$TEST_SERVICE_LOG"\n')
    sudo.chmod(0o755)
    cli = tmp_path / "install/scripts/inky-studio-cli"
    cli.parent.mkdir(parents=True, exist_ok=True)
    cli.write_bytes((root / "scripts/inky-studio-cli").read_bytes())
    launcher = _generate_launcher(tmp_path, tmp_path / "install", tmp_path / "data")
    return subprocess.run(
        ["bash", str(launcher), command],
        env={**os.environ, "INKY_STUDIO_INSTALL_DIR": str(tmp_path / "install"),
             "INKY_STUDIO_DATA_DIR": str(tmp_path / "data"),
             "TEST_SERVICE_LOG": str(tmp_path / "service.log"),
             "TEST_REAL_PYTHON": sys.executable,
             "PATH": f"{tmp_path}:{os.environ['PATH']}",
             "PYTHONPATH": str(root / "server")},
        cwd=root / "server", text=True, capture_output=True,
    )


@pytest.mark.parametrize("stored", ["bootstrap", "personalized", "legacy", "missing"])
def test_password_cli_reads_without_rewriting_or_resetting(tmp_path, stored):
    directory = tmp_path / "data"
    path = directory / "credentials.json"
    if stored == "bootstrap":
        expected = auth.reset_credentials(directory).bootstrap_password
    elif stored == "personalized":
        directory.mkdir()
        auth._write_credentials(auth._new_credentials(directory, "private-password"))
        expected = "non consultable"
    elif stored == "legacy":
        directory.mkdir()
        path.write_text('{"password":"existing-secret"}')
        expected = "existing-secret"
    before = path.read_bytes() if path.exists() else None
    result = _password_cli(tmp_path, "password")
    assert result.returncode == (1 if stored == "missing" else 0)
    if stored == "missing":
        assert not directory.exists()
    else:
        assert expected in result.stdout
        assert path.read_bytes() == before
        if stored == "personalized":
            assert "private-password" not in result.stdout
    assert not (tmp_path / "service.log").exists()


def test_reset_cli_stops_writes_atomically_and_restarts(tmp_path):
    initial = auth.reset_credentials(tmp_path / "data")
    result = _password_cli(tmp_path, "reset-password")
    assert result.returncode == 0, result.stderr
    replacement = auth.load_or_create_credentials(tmp_path / "data")
    assert result.stdout.strip() == replacement.bootstrap_password
    assert not replacement.verify(initial.bootstrap_password)
    assert (tmp_path / "service.log").read_text().splitlines() == [
        "systemctl stop inky-studio.service", "systemctl start inky-studio.service",
    ]


def test_failed_reset_cli_keeps_credentials_and_restarts_service(tmp_path):
    initial = auth.reset_credentials(tmp_path / "data")
    before = initial.path.read_bytes()
    result = _password_cli(tmp_path, "reset-password", fail_python=True)
    assert result.returncode == 7
    assert initial.path.read_bytes() == before
    assert (tmp_path / "service.log").read_text().splitlines() == [
        "systemctl stop inky-studio.service", "systemctl start inky-studio.service",
    ]
