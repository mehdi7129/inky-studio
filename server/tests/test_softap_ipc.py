"""Closed AP RPC over actual Unix streams and the existing peer-proof lifetime."""
import json
from pathlib import Path

import pytest

from inky_web.provisioning import system_setup_ipc as ipc
from inky_web.provisioning.softap import SoftAPController
from tests.test_system_setup_ipc import BOOT, owner, proof, uid
from tests.test_system_setup_ipc import unix_service as unix_service


def access_point():
    return {"state": "active", "boot_id": BOOT, "ap_id": uid(), "country": "FR",
            "interface": "wlan0", "ssid": "Inky-1234abcd", "passphrase": "a" * 24,
            "host": "192.168.4.1", "port": 9443, "expires_boottime_ns": 1_800_000_000_000}


@pytest.mark.parametrize("operation", ["start", "stop", "status"])
async def test_ap_uses_existing_attested_ipc(unix_service, operation):
    value = access_point()
    if operation == "stop":
        value["state"] = "stopped"
    async def callback(request):
        assert request["op"] == "setup.ap." + operation
        return value
    path, requests = await unix_service(callback)
    events = []
    client = ipc.SystemSetupClient(path, peer_guard=proof(events), boot_id=lambda: BOOT)
    workflow = ipc._workflow(owner())
    assert await getattr(client, "ap_" + operation)(workflow) == value
    assert requests[0]["args"] == {"workflow": workflow}
    assert events == ["entered", "released"]


@pytest.mark.parametrize("patch", [{"extra": True}, {"boot_id": "a" * 36},
    {"state": "committed"}, {"port": True}, {"passphrase": "short"},
    {"host": "evil.example"}, {"country": "US"}, {"ssid": "home"},
    {"expires_boottime_ns": -1}, {"passphrase": None}])
async def test_ap_refuses_malformed_and_stale_records(unix_service, patch):
    async def callback(request):
        return {**access_point(), **patch}
    path, _ = await unix_service(callback)
    events = []
    client = ipc.SystemSetupClient(path, peer_guard=proof(events), boot_id=lambda: BOOT)
    with pytest.raises(ipc.SetupUnavailable):
        await client.ap_start(ipc._workflow(owner()))
    assert events == ["entered", "released"]


async def test_ap_requires_native_peer_proof(unix_service):
    path, requests = await unix_service(lambda _: None)
    with pytest.raises(ipc.SetupUnavailable, match="unavailable"):
        await ipc.SystemSetupClient(path).ap_start(ipc._workflow(owner()))
    assert requests == []


def test_closed_ap_schema_matches_os_canon():
    fixture = json.loads((Path(__file__).parent / "fixtures/softap-system-setup-contract.json").read_text())
    assert fixture["source_sha256"] == "101d169b3eb5a1ecbfd9345e874dbf686095b304efe1db678963ceac16e81a06"
    def schema(rule):
        kind, *args = rule
        if kind == "object":
            return {"type": "object", "additionalProperties": False,
                    "required": sorted(args[0]), "properties": {key: schema(value) for key, value in args[0].items()}}
        if kind == "ref":
            return {"$ref": "#/$defs/" + ("APState" if args[0] == "AccessPoint" else args[0])}
        if kind == "const":
            return {"const": args[0]}
        if kind == "enum":
            return {"enum": list(args[0])}
        if kind == "one":
            return {"oneOf": [schema(value) for value in args[0]]}
        if kind == "string":
            return {"type": "string", **({"pattern": args[0]} if args[0] is not None else {})}
        if kind == "integer":
            return {"type": "integer", **({"minimum": args[0]} if args[0] is not None else {}),
                    **({"maximum": args[1]} if args[1] is not None else {})}
        raise AssertionError(kind)
    def normalize(value):
        if isinstance(value, dict):
            if value == {"type": "null"}:
                return {"const": None}
            return {key: sorted(child) if key == "required" else normalize(child) for key, child in value.items()}
        if isinstance(value, list):
            return [normalize(child) for child in value]
        return value
    for operation in fixture["requests"]:
        assert schema(ipc._REQUESTS[operation]) == normalize(fixture["requests"][operation])
        assert schema(ipc._RESPONSES[operation]) == normalize(fixture["responses"][operation])
    assert schema(ipc._DEFINITIONS["AccessPoint"]) == normalize(fixture["definitions"]["APState"])
    assert schema(ipc._DEFINITIONS["Workflow"]) == normalize(fixture["definitions"]["Workflow"])
    assert schema(ipc._ERROR) == normalize(fixture["error"])


async def test_ap_expiry_cannot_encode_a_new_qr_or_extend_identity():
    class Native:
        def __init__(self):
            self.value = access_point()
        async def ap_start(self, workflow):
            return dict(self.value)
        async def ap_status(self, workflow):
            return dict(self.value)
    native = Native()
    controller = SoftAPController(native)
    await controller.start(ipc._workflow(owner()))
    native.value["state"] = "expired"
    with pytest.raises(ipc.SetupUnavailable, match="expired"):
        await controller.ensure_active()
    with pytest.raises(ipc.SetupUnavailable):
        controller.encode_qr(uid(), "a" * 64, "b" * 64)
    native.value.update(state="active", expires_boottime_ns=1_900_000_000_000)
    with pytest.raises(ipc.SetupUnavailable):
        await controller.start(controller.workflow)
