"""Explicit installed SoftAP policy; OS remains the sole radio authority."""
from __future__ import annotations

from . import softap_wire
from .system_setup_ipc import SetupUnavailable


class SoftAPController:
    def __init__(self, system_setup):
        self.system_setup = system_setup
        self.workflow = None
        self.snapshot = None

    async def start(self, workflow, *, channel=None):
        self.workflow = dict(workflow)
        snapshot = (await self.system_setup.ap_start(workflow) if channel is None else
                    await channel.call("setup.ap.start", workflow=workflow))
        self._accept(snapshot)
        if snapshot["state"] != "active":
            raise SetupUnavailable("unavailable")
        return self.snapshot

    def _accept(self, snapshot):
        if self.snapshot is not None:
            fields = {"boot_id", "ap_id", "country", "interface", "ssid", "passphrase",
                      "host", "port", "expires_boottime_ns"}
            if any(snapshot[key] != self.snapshot[key] for key in fields):
                raise SetupUnavailable("unavailable")
        self.snapshot = snapshot

    async def ensure_active(self):
        self._accept(await self.system_setup.ap_status(self.workflow))
        if self.snapshot["state"] != "active":
            raise SetupUnavailable("expired")

    def encode_qr(self, frame_id, pin, token):
        if self.snapshot is None or self.snapshot["state"] != "active":
            raise SetupUnavailable("unavailable")
        return softap_wire.encode_qr(frame_id, pin, token, self.snapshot["ssid"],
                                     self.snapshot["passphrase"])

    async def stop(self, *, channel=None):
        if self.workflow is not None:
            self._accept(await self.system_setup.ap_stop(self.workflow) if channel is None else
                         await channel.call("setup.ap.stop", workflow=self.workflow))
            if self.snapshot["state"] not in {"stopped", "expired"}:
                raise SetupUnavailable("unavailable")
