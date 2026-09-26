"""Exercise the installed wrapper with harmless stub executables."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


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
