"""Initial PHOTO access on an explicitly selected LAN-only frame."""
from __future__ import annotations

import asyncio
import json
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from PIL import Image

from inky_web import lan_runtime
from inky_web.lan_runtime import (
    LANPhotoRuntime,
    LANRuntimeError,
    invitation_payload,
    render_lan_welcome,
    validate_lan_origin,
)
from inky_web.photo_access import AccessError, PhotoAccessStore
from inky_web.provisioning.identity import load_or_create_identity
from tests.test_photo_access import claim, enrollment, invitation


def bootstrap_invitation():
    return {key: value for key, value in invitation().items() if key != "ttl_seconds"}


def renew(value, invite):
    return value.renew_lan_bootstrap(invite["invitation_id"], invite["invitation_token"])


def rows(value, table):
    # These closed table names are supplied by this test module only.
    assert table in {"devices", "invitations", "issued_invitations"}
    with value._connection() as connection:
        return [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]


@pytest.fixture
def lan_store(tmp_path):
    clock = SimpleNamespace(wall=1000.0, mono=50.0, epoch="a" * 64)
    value = PhotoAccessStore(
        tmp_path / "lan-access", lambda: clock.epoch, lan_bootstrap=True,
        clock=lambda: clock.wall, monotonic=lambda: clock.mono,
    )
    return value, clock


def test_lan_bootstrap_is_explicitly_opted_in(tmp_path):
    value = PhotoAccessStore(tmp_path / "legacy-access", lambda: "a" * 64)
    with pytest.raises(AccessError):
        value.begin_lan_bootstrap(**bootstrap_invitation())
    assert rows(value, "devices") == rows(value, "invitations") == []


def test_initial_invitation_creates_no_owner_and_persists_only_hashes(lan_store):
    value, clock = lan_store
    invite = bootstrap_invitation()
    result = value.begin_lan_bootstrap(**invite)
    assert result["expires_at"] == clock.wall + 300
    assert rows(value, "devices") == []
    assert len(rows(value, "issued_invitations")) == 1
    row, = rows(value, "invitations")
    assert row["invitation_id"] == invite["invitation_id"]
    assert row["issuer_id"] not in {device["device_id"] for device in rows(value, "devices")}
    assert invite["invitation_token"].encode() not in value.path.read_bytes()


def test_non_lan_process_refuses_an_otherwise_live_bootstrap_record(lan_store, tmp_path):
    value, clock = lan_store
    invite = bootstrap_invitation()
    value.begin_lan_bootstrap(**invite)
    row, = rows(value, "invitations")
    ordinary = PhotoAccessStore(
        tmp_path / "ordinary-access", lambda: clock.epoch,
        clock=lambda: clock.wall, monotonic=lambda: clock.mono,
    )
    # Model a live pending record in an ordinary process. Its lack of LAN
    # startup authority must still deny it, independently of expiry or boot.
    row["boot"] = ordinary._boot
    with ordinary._transaction() as connection:
        columns = ",".join(row)
        slots = ",".join("?" for _ in row)
        connection.execute(f"INSERT INTO invitations ({columns}) VALUES ({slots})", tuple(row.values()))
    with pytest.raises(AccessError):
        ordinary.claim(**claim(invite))
    assert rows(ordinary, "devices") == []


def test_initial_claim_is_media_and_retry_binds_the_exact_device(lan_store):
    value, _ = lan_store
    invite = bootstrap_invitation()
    value.begin_lan_bootstrap(**invite)
    payload = claim(invite)
    principal = value.claim(**payload)
    assert principal.role == "media"
    assert value.authenticate(payload["device_id"], payload["device_token"]) == principal
    assert value.claim(**payload) == principal
    assert [row["role"] for row in rows(value, "devices")] == ["media"]
    for key, replacement in (
        ("device_id", enrollment()["device_id"]),
        ("device_token", "1" * 64),
        ("request_id", enrollment()["request_id"]),
        ("invitation_token", "2" * 64),
    ):
        with pytest.raises(AccessError):
            value.claim(**{**payload, key: replacement})
    with pytest.raises(AccessError):
        value.invite(principal, **invitation())
    with pytest.raises(AccessError):
        value.devices(principal)
    with pytest.raises(AccessError):
        value.begin_lan_bootstrap(**bootstrap_invitation())


def test_two_simultaneous_scans_cannot_create_two_first_devices(lan_store):
    value, _ = lan_store
    invite = bootstrap_invitation()
    value.begin_lan_bootstrap(**invite)
    first, second = claim(invite), claim(invite)

    def attempt(payload):
        try:
            return value.claim(**payload)
        except AccessError:
            return None

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(attempt, [first, second] * 8))
    assert len({result.device_id for result in results if result is not None}) == 1
    assert sum(result is not None for result in results) == 8
    assert [row["role"] for row in rows(value, "devices")] == ["media"]


def test_new_authority_cannot_race_the_unclaimed_initial_invitation(lan_store):
    value, _ = lan_store
    invite = bootstrap_invitation()
    value.begin_lan_bootstrap(**invite)
    value.enroll(**enrollment())
    with pytest.raises(AccessError):
        value.claim(**claim(invite))
    before, = rows(value, "invitations")
    assert renew(value, invite) is False
    after, = rows(value, "invitations")
    assert after["expires_at"] == before["expires_at"]
    assert after["revoked"]
    assert len(rows(value, "devices")) == 1


def test_renewal_keeps_one_qr_and_one_antireplay_receipt(lan_store):
    value, clock = lan_store
    invite = bootstrap_invitation()
    value.begin_lan_bootstrap(**invite)
    before, = rows(value, "invitations")
    issued = rows(value, "issued_invitations")
    clock.wall += 240
    clock.mono += 240
    assert renew(value, invite) is True
    after, = rows(value, "invitations")
    assert after["expires_at"] == clock.wall + 300
    assert after["expires_mono"] == clock.mono + 300
    assert after["invitation_id"] == before["invitation_id"]
    assert after["token_hash"] == before["token_hash"]
    assert rows(value, "issued_invitations") == issued
    # The same physically rendered QR remains usable after its original expiry.
    clock.wall += 61
    clock.mono += 61
    assert value.claim(**claim(invite)).role == "media"


def test_renewal_stops_without_extending_the_claim_receipt(lan_store):
    value, clock = lan_store
    invite = bootstrap_invitation()
    value.begin_lan_bootstrap(**invite)
    payload = claim(invite)
    principal = value.claim(**payload)
    before, = rows(value, "invitations")
    clock.wall += 30
    clock.mono += 30
    assert renew(value, invite) is False
    after, = rows(value, "invitations")
    assert after["expires_at"] == before["expires_at"]
    assert after["expires_mono"] == before["expires_mono"]
    assert value.claim(**payload) == principal


@pytest.mark.parametrize("change", ["wall_expiry", "mono_expiry", "backwards", "mono_backwards", "nan", "epoch"])
def test_expiry_or_uncertain_clock_cannot_renew_or_remint(lan_store, change):
    value, clock = lan_store
    invite = bootstrap_invitation()
    value.begin_lan_bootstrap(**invite)
    if change == "wall_expiry":
        clock.wall += 300
    elif change == "mono_expiry":
        clock.mono += 300
    elif change == "backwards":
        clock.wall -= 1
    elif change == "mono_backwards":
        clock.mono -= 1
    elif change == "nan":
        clock.wall = float("nan")
    else:
        clock.epoch = "b" * 64
    with pytest.raises(AccessError):
        renew(value, invite)
    # Correcting the observation never silently recreates first-pairing authority.
    if change in {"backwards", "mono_backwards", "nan"}:
        clock.wall, clock.mono = 1100.0, 150.0
    elif change in {"wall_expiry", "mono_expiry"}:
        clock.wall, clock.mono = 1400.0, 450.0
    with pytest.raises(AccessError):
        value.begin_lan_bootstrap(**bootstrap_invitation())
    with pytest.raises(AccessError):
        value.claim(**claim(invite))


def test_revoked_first_device_cannot_replay_or_restart_pairing(lan_store):
    value, _ = lan_store
    invite = bootstrap_invitation()
    value.begin_lan_bootstrap(**invite)
    payload = claim(invite)
    principal = value.claim(**payload)
    with value._transaction() as connection:
        connection.execute("UPDATE devices SET revoked=1 WHERE device_id=?", (principal.device_id,))
    assert not value.valid(principal)
    with pytest.raises(AccessError):
        value.claim(**payload)
    with pytest.raises(AccessError):
        value.begin_lan_bootstrap(**bootstrap_invitation())


def test_restart_invalidates_old_qr_but_allows_fresh_unpaired_boot(lan_store):
    value, clock = lan_store
    old = bootstrap_invitation()
    value.begin_lan_bootstrap(**old)
    restarted = PhotoAccessStore(
        value.directory, lambda: clock.epoch, lan_bootstrap=True,
        clock=lambda: clock.wall, monotonic=lambda: clock.mono,
    )
    with pytest.raises(AccessError):
        restarted.claim(**claim(old))
    fresh = bootstrap_invitation()
    restarted.begin_lan_bootstrap(**fresh)
    assert restarted.claim(**claim(fresh)).role == "media"
    assert rows(restarted, "devices")[0]["role"] == "media"


def test_restart_preserves_photo_credential_and_cannot_repair_as_new(lan_store):
    value, clock = lan_store
    invite = bootstrap_invitation()
    value.begin_lan_bootstrap(**invite)
    payload = claim(invite)
    principal = value.claim(**payload)
    restarted = PhotoAccessStore(
        value.directory, lambda: clock.epoch, lan_bootstrap=True,
        clock=lambda: clock.wall, monotonic=lambda: clock.mono,
    )
    assert restarted.authenticate(payload["device_id"], payload["device_token"]) == principal
    with pytest.raises(AccessError):
        restarted.begin_lan_bootstrap(**bootstrap_invitation())
    with pytest.raises(AccessError):
        restarted.claim(**payload)


def test_existing_device_tombstone_also_blocks_initial_pairing(lan_store):
    value, _ = lan_store
    owner = value.enroll(**enrollment())
    value.revoke_device(owner, owner.device_id)
    with pytest.raises(AccessError):
        value.begin_lan_bootstrap(**bootstrap_invitation())


@pytest.mark.parametrize("capacity", ["MAX_INVITATIONS", "MAX_ISSUED_INVITATIONS"])
def test_initial_invitation_respects_existing_capacity(lan_store, monkeypatch, capacity):
    from inky_web import photo_access

    value, _ = lan_store
    monkeypatch.setattr(photo_access, capacity, 0)
    with pytest.raises(AccessError):
        value.begin_lan_bootstrap(**bootstrap_invitation())
    assert rows(value, "devices") == rows(value, "invitations") == []


class DisplayFixture:
    """Inert panel port; require real locking and private temporary PNGs."""

    def __init__(self):
        self.closing = False
        self.images = []
        self.paths = []
        self.operation_depth = 0
        self.on_enter = None
        self.entered_push = threading.Event()
        self.allow_push = threading.Event()
        self.allow_push.set()

    @contextmanager
    def operation(self):
        self.operation_depth += 1
        try:
            if self.on_enter is not None:
                self.on_enter()
            yield
        finally:
            self.operation_depth -= 1

    def require_available(self):
        assert not self.closing

    def info(self):
        return {"width": 800, "height": 480}

    def reserve(self, _owner):
        raise AssertionError("PHOTO welcome must not reserve Bluetooth adoption")

    def display_image(self, path, *, saturation):
        assert self.operation_depth == 1
        assert saturation == 0
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        self.entered_push.set()
        assert self.allow_push.wait(timeout=5), "test never released inert panel write"
        with Image.open(path) as image:
            self.images.append(image.copy())
        self.paths.append(path)


@pytest.fixture
async def runtime_frame(lan_store, tmp_path, monkeypatch):
    value, clock = lan_store
    count = [0]
    monkeypatch.setattr(lan_runtime.history, "count", lambda: count[0])
    identity = load_or_create_identity(tmp_path / "identity")
    display = DisplayFixture()
    app = SimpleNamespace(state=SimpleNamespace(
        photo_access=value, display=display, frame_identity=identity,
        auth_service=SimpleNamespace(), bus=SimpleNamespace(broadcast=lambda *_: None),
    ))
    runtime = LANPhotoRuntime(app, "https://inky-test.local:8443", identity.ssl_context())
    try:
        yield SimpleNamespace(runtime=runtime, store=value, clock=clock, display=display,
                              history=count, app=app)
    finally:
        display.allow_push.set()
        await runtime.stop()


@pytest.mark.parametrize("origin", [
    "https://inky-test.local:8443", "https://192.168.1.50:8443", "https://[fd00::1]:8443",
])
def test_photo_locator_is_canonical_https(origin):
    assert validate_lan_origin(origin) == origin


@pytest.mark.parametrize("origin", [
    "http://inky-test.local:8000", "https://inky-test.local", "https://inky-test.local:443",
    "https://inky-test.local:8443/", "https://inky-test.local:8443/photo",
    "https://user:secret@inky-test.local:8443", "https://inky-test.local:8443?token=x",
    "https://inky-test.local:8443#secret", "https://Inky-test.local:8443",
    "https://inky-test.local.:8443", "https://inky_test.local:8443", None,
])
def test_photo_locator_refuses_ambiguous_or_non_https_origin(origin):
    with pytest.raises(LANRuntimeError, match="lan_runtime_unavailable") as error:
        validate_lan_origin(origin)
    assert error.value.exit_status == 78


def test_photo_qr_uses_existing_closed_ios_invitation_contract(tmp_path):
    identity = load_or_create_identity(tmp_path / "identity")
    invite = bootstrap_invitation()
    raw = invitation_payload(identity, "https://inky-test.local:8443",
                             invite["invitation_id"], invite["invitation_token"])
    assert len(raw.encode()) <= 1024
    assert json.loads(raw) == {
        "v": 1, "p": "invite", "id": identity.frame_id, "k": identity.spki_sha256,
        "url": "https://inky-test.local:8443", "i": invite["invitation_id"],
        "t": invite["invitation_token"],
    }
    assert "password" not in raw and "ssid" not in raw and "owner" not in raw
    image = render_lan_welcome(800, 480, raw)
    assert image.mode == "RGB" and image.size == (800, 480)
    # A real QR has substantial black area, while the light welcome retains
    # a white background; avoid testing a second copy of the renderer geometry.
    colors = image.getcolors(maxcolors=800 * 480)
    assert colors is not None
    assert sum(count for count, rgb in colors if rgb == (0, 0, 0)) > 10000
    assert sum(count for count, rgb in colors if rgb == (255, 255, 255)) > 150000


async def test_lan_start_renders_one_private_qr_and_stop_does_not_repaint(runtime_frame):
    frame = runtime_frame
    await frame.runtime.start()
    assert len(frame.display.images) == 1
    assert frame.display.images[0].size == (800, 480)
    assert rows(frame.store, "devices") == []
    assert frame.runtime._payload is not None
    assert all(not path.exists() for path in frame.display.paths)
    await frame.runtime.start()
    await frame.runtime.stop()
    assert len(frame.display.images) == 1
    assert frame.display.operation_depth == 0
    assert frame.runtime._payload is None
    assert frame.runtime._invitation_token is None
    assert all(task.done() for task in frame.runtime._tasks)


async def test_renewal_keeps_printed_qr_and_stops_after_claim(runtime_frame):
    frame = runtime_frame
    await frame.runtime.start()
    raw = frame.runtime._payload
    issued = rows(frame.store, "issued_invitations")
    before, = rows(frame.store, "invitations")
    frame.clock.wall += 240
    frame.clock.mono += 240
    assert await frame.runtime._maintenance_once() is True
    assert frame.runtime._payload == raw
    assert len(frame.display.images) == 1
    assert rows(frame.store, "issued_invitations") == issued
    invite = json.loads(raw)
    frame.store.claim(**claim({"invitation_id": invite["i"], "invitation_token": invite["t"]}))
    claimed, = rows(frame.store, "invitations")
    assert claimed["expires_at"] > before["expires_at"]
    assert await frame.runtime._maintenance_once() is False
    assert frame.runtime._payload is None
    assert rows(frame.store, "invitations")[0]["expires_at"] == claimed["expires_at"]
    assert len(frame.display.images) == 1


@pytest.mark.parametrize("reason", ["existing_photo", "associated"])
async def test_reboot_never_repaints_an_existing_photo_or_association(runtime_frame, reason):
    frame = runtime_frame
    if reason == "existing_photo":
        frame.history[0] = 1
    else:
        invite = bootstrap_invitation()
        frame.store.begin_lan_bootstrap(**invite)
        frame.store.claim(**claim(invite))
        # Reopen as a new process would, so the device row rather than the
        # previous object's one-mint flag closes the welcome path.
        frame.store = PhotoAccessStore(
            frame.store.directory, lambda: frame.clock.epoch, lan_bootstrap=True,
            clock=lambda: frame.clock.wall, monotonic=lambda: frame.clock.mono,
        )
        frame.app.state.photo_access = frame.store
    await frame.runtime.start()
    assert frame.display.images == []
    assert frame.runtime._payload is None


async def test_history_is_rechecked_inside_the_panel_operation(runtime_frame):
    frame = runtime_frame
    frame.display.on_enter = lambda: frame.history.__setitem__(0, 1)
    await frame.runtime.start()
    assert frame.display.images == []
    assert frame.runtime._payload is None
    assert frame.display.operation_depth == 0


async def test_photo_appearing_during_welcome_stops_renewal_without_repaint(runtime_frame):
    frame = runtime_frame
    await frame.runtime.start()
    before, = rows(frame.store, "invitations")
    frame.history[0] = 1
    frame.clock.wall += 60
    frame.clock.mono += 60
    assert await frame.runtime._maintenance_once() is False
    assert frame.runtime._payload is None
    assert rows(frame.store, "invitations")[0]["expires_at"] == before["expires_at"]
    assert len(frame.display.images) == 1


async def test_cancelling_start_drains_the_admitted_panel_write(runtime_frame):
    frame = runtime_frame
    frame.display.allow_push.clear()
    starting = asyncio.create_task(frame.runtime.start())
    assert await asyncio.to_thread(frame.display.entered_push.wait, 3)
    starting.cancel()
    # Yield the loop so cancellation reaches the shield; the SPI fixture stays
    # blocked and must still be owned rather than abandoned.
    await asyncio.sleep(0)
    assert not starting.done()
    frame.display.allow_push.set()
    with pytest.raises(asyncio.CancelledError):
        await starting
    assert len(frame.display.images) == 1
    assert frame.display.operation_depth == 0
    assert all(task.done() for task in frame.runtime._tasks)


async def test_concurrent_stop_waits_for_panel_write_and_closes_further_start(runtime_frame):
    frame = runtime_frame
    frame.display.allow_push.clear()
    starting = asyncio.create_task(frame.runtime.start())
    assert await asyncio.to_thread(frame.display.entered_push.wait, 3)
    pending = {"invitation_id": frame.runtime._invitation_id,
               "invitation_token": frame.runtime._invitation_token}
    assert all(pending.values())
    stopping = asyncio.create_task(frame.runtime.stop())
    try:
        await frame.runtime._stop.wait()
        # No wall-clock wait: let the stop/certificate callback chain drain.
        # The panel event is still closed, so stop must remain pending even
        # after all ready event-loop callbacks had an opportunity to run.
        for _ in range(8):
            await asyncio.sleep(0)
        assert not stopping.done()
        assert not starting.done()
    finally:
        frame.display.allow_push.set()
        await asyncio.gather(starting, stopping)
    assert len(frame.display.images) == 1
    assert frame.display.operation_depth == 0
    assert frame.runtime._payload is None
    assert frame.runtime._invitation_token is None
    record, = rows(frame.store, "invitations")
    assert record["invitation_id"] == pending["invitation_id"]
    assert record["revoked"] == 1
    with pytest.raises(AccessError):
        frame.store.claim(**claim(pending))
    issued = rows(frame.store, "issued_invitations")
    await frame.runtime.start()
    assert len(frame.display.images) == 1
    assert rows(frame.store, "issued_invitations") == issued
    assert all(task.done() for task in frame.runtime._tasks)
