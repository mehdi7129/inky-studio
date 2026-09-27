"""Exercise the installed wrapper with harmless stub executables."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from inky_web import auth


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
    return subprocess.run(
        ["bash", str(root / "scripts/inky-studio-cli"), command],
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
