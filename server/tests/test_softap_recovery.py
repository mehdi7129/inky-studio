"""Reboot preserves ownership and never creates a fresh factory claim window."""
from uuid import uuid4

import pytest

from inky_web.provisioning.factory_continuation import FactoryContinuationRuntime
from inky_web.provisioning.ownership import OwnershipError
from tests.test_bootstrap_runtime import FakeBlueZ
from tests.test_factory_system_setup import (
    FakeDisplay,
    Network,
    Normal,
    apply,
    complete,
)
from tests.test_factory_system_setup import adopted as adopted
from tests.test_softap_flow import AP


@pytest.mark.parametrize("published", [False, True])
async def test_adopted_reboot_recovery_qr_has_no_claim_authority(adopted, monkeypatch, published):
    v = adopted
    if published:
        await apply(v)
    await v.runtime.stop()
    v.result.ownership.close()
    reopened = v.coordinator.initialize(resume_consumed=True)
    def forbidden(*args, **kwargs):
        pytest.fail("ADOPTED recovery reopened a claim window")
    monkeypatch.setattr(reopened.ownership, "open_factory_window", forbidden)
    monkeypatch.setattr(reopened.ownership, "open_window", forbidden)
    ap = AP([])
    runtime = FactoryContinuationRuntime(reopened, v.epoch, FakeDisplay(), v.directory,
        system_setup=v.native, network=Network(), softap=ap, server_factory=FakeBlueZ,
        normal_service_factory=Normal)
    try:
        await runtime.start()
        assert ap.qr is not None and ap.qr["v"] == 3
        assert runtime.identity is not None if published else runtime.identity is None
        assert reopened.ownership.status(v.owner, "b" * 64, request_id=v.claim_id).owner_id == v.owner
        with pytest.raises(OwnershipError, match="qr_unavailable"):
            reopened.ownership.claim(ap.qr["t"], str(uuid4()), "c" * 64, str(uuid4()), v.epoch())
    finally:
        await runtime.stop()
        reopened.ownership.close()


async def test_completed_healthy_lan_reboot_preserves_photo_and_does_not_start_ap(adopted):
    v = adopted
    await complete(v)
    photo = v.directory.parent / "last-photo.png"
    photo.write_bytes(b"existing photo")
    await v.runtime.stop()
    v.result.ownership.close()
    reopened = v.coordinator.initialize(resume_consumed=True)
    calls, display = [], FakeDisplay()
    runtime = FactoryContinuationRuntime(reopened, v.epoch, display, v.directory,
        system_setup=v.native, network=Network(), softap=AP(calls), server_factory=FakeBlueZ,
        normal_service_factory=Normal)
    try:
        await runtime.start()
        assert calls == [] and not display.images
        assert runtime.historical_completed() and runtime.https_origin() is not None
        assert photo.read_bytes() == b"existing photo"
    finally:
        await runtime.stop()
        reopened.ownership.close()
