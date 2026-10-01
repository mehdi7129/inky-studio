"""Abrupt process loss at ownership commit boundaries, without app/runtime I/O."""
from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from inky_web.provisioning.factory import (
    FactoryIdentity,
    FactoryState,
    InitializationReceipt,
)
from inky_web.provisioning.ownership import OwnershipError, OwnershipStore

# Deliberately synthetic values shared with the isolated subprocess. No OS
# receipt, identity key, real QR, app password, network or display is involved.
RECEIPT = InitializationReceipt("00000000-0000-4000-8000-000000000001", "a" * 64)
IDENTITY = FactoryIdentity("00000000-0000-4000-8000-000000000002", "b" * 64)
OWNER = "00000000-0000-4000-8000-000000000003"
REQUEST = "00000000-0000-4000-8000-000000000004"
OWNER_TOKEN = "c" * 64
QR_TOKEN = "d" * 64
EPOCH = "e" * 64

CRASH_CHILD = r"""
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from inky_web.provisioning.factory import FactoryIdentity, InitializationReceipt
from inky_web.provisioning.ownership import OwnershipStore

directory, point = Path(sys.argv[1]), sys.argv[2]
receipt = InitializationReceipt("00000000-0000-4000-8000-000000000001", "a" * 64)
identity = FactoryIdentity("00000000-0000-4000-8000-000000000002", "b" * 64)
store = OwnershipStore.create_factory(directory, lambda: "e" * 64,
    receipt=receipt, expected_identity=identity)
store.mark_factory_ready(identity)
with patch("inky_web.provisioning.ownership.secrets.token_hex", return_value="d" * 64):
    qr = store.open_factory_window()

original_connection = store._connection
def interrupt(statement):
    if point == "before_state" and statement.startswith("UPDATE factory_initialization"):
        os._exit(73)
    if point == "before_commit" and statement == "COMMIT":
        os._exit(73)

@contextmanager
def traced_connection():
    with original_connection() as connection:
        connection.set_trace_callback(interrupt)
        yield connection

store._connection = traced_connection
store.claim(qr, "00000000-0000-4000-8000-000000000003", "c" * 64,
    "00000000-0000-4000-8000-000000000004", "e" * 64)
if point == "after_commit":
    os._exit(73)  # Process ends before it could send a success response.
raise AssertionError("Expected crash boundary was not reached")
"""


@pytest.mark.parametrize("point", ["before_state", "before_commit", "after_commit"])
def test_process_loss_preserves_atomic_first_claim(tmp_path: Path, point: str):
    directory = tmp_path / "factory-authority"
    result = subprocess.run(
        [sys.executable, "-c", CRASH_CHILD, str(directory), point],
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 73, result.stderr

    # A fresh process authority triggers SQLite's actual journal recovery.
    store = OwnershipStore.reopen_factory(
        directory, lambda: EPOCH, receipt=RECEIPT, expected_identity=IDENTITY,
    )
    with sqlite3.connect(directory / "ownership.sqlite3") as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        owner_count = connection.execute("SELECT count(*) FROM owners").fetchone()[0]
        epoch_count = connection.execute("SELECT count(*) FROM allowed_epochs").fetchone()[0]
        request_count = connection.execute("SELECT count(*) FROM requests").fetchone()[0]

    if point == "after_commit":
        status = store.factory_status()
        assert status.state == FactoryState.ADOPTED
        assert status.first_owner_id == OWNER
        assert (owner_count, epoch_count, request_count) == (1, 1, 1)
        assert store.claim(QR_TOKEN, OWNER, OWNER_TOKEN, REQUEST, EPOCH).owner_id == OWNER
        assert store.status(OWNER, OWNER_TOKEN, REQUEST).claimed
        with pytest.raises(OwnershipError, match="factory_unavailable"):
            store.open_factory_window()
    else:
        assert store.factory_status().state == FactoryState.FACTORY
        assert (owner_count, epoch_count, request_count) == (0, 0, 0)
        # Restart has invalidated the old window; a fresh physical window is
        # needed even though the uncommitted owner writes were rolled back.
        with pytest.raises(OwnershipError, match="qr_unavailable"):
            store.claim(QR_TOKEN, OWNER, OWNER_TOKEN, REQUEST, EPOCH)
        assert store.open_factory_window().value != QR_TOKEN
