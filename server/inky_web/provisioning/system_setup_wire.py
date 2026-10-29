"""Closed RPC v2 system-setup grammar; this module grants no authority."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from . import bootstrap_wire as legacy

CAPABILITIES = (
    "system_setup.challenge", "system_setup.apply", "system_setup.status", "system_setup.continue",
)
OPERATIONS = frozenset((*CAPABILITIES, "system_setup.negotiate"))
ERRORS = frozenset({
    "invalid_request", "unsupported_version", "negotiation_required", "unauthorized",
    "request_not_found", "request_conflict", "epoch_changed", "rate_limited",
    "service_stopping", "recovery_required", "unavailable",
})
STATES = frozenset({
    "challenge_issued", "applying", "uncertain", "setup_ready", "tls_ready",
    "wifi_pending", "complete", "refused",
})
NEXT_STEPS = frozenset({"apply", "status", "recover_explicit", "continue", "wifi",
                        "wait_origin", "photo_enroll"})
_AUTH = {"v", "id", "op", "owner_id", "owner_token", "claim_request_id"}
_EXTRAS = {
    "system_setup.negotiate": {"versions"},
    "system_setup.challenge": {"op_id", "supersedes_op_id"},
    "system_setup.apply": {"op_id", "challenge_id", "nonce", "utc_seconds", "country"},
    "system_setup.status": {"op_id"},
    "system_setup.continue": {"op_id"},
}

WireError = legacy.WireError
parse_json = legacy.parse_json
request_id = legacy.request_id


def _closed(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise WireError()


def _nullable_uuid(value):
    if value is not None:
        legacy._uuid(value)


def _integer(value, minimum=0, maximum=2**63 - 1):
    legacy._integer(value, minimum=minimum, maximum=maximum)


def origin(value):
    if type(value) is not str or len(value.encode("utf-8")) > 267:
        raise WireError()
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise WireError() from None
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.path or parsed.query or parsed.fragment
            or not re.fullmatch(r"[a-zA-Z0-9.\[\]:-]+", parsed.netloc)
            or port is not None and not 1 <= port <= 65535):
        raise WireError()
    return value


def validate_request(value):
    operation = value.get("op") if type(value) is dict else None
    if type(operation) is not str or operation not in _EXTRAS:
        raise WireError()
    _closed(value, _AUTH | _EXTRAS[operation])
    legacy._integer(value["v"], 2)
    for key in ("id", "owner_id", "claim_request_id"):
        legacy._uuid(value[key])
    legacy._token(value["owner_token"])
    if operation == "system_setup.negotiate":
        if type(value["versions"]) is not list or len(value["versions"]) != 1:
            raise WireError()
        legacy._integer(value["versions"][0], 2)
    else:
        legacy._uuid(value["op_id"])
    if operation == "system_setup.challenge":
        _nullable_uuid(value["supersedes_op_id"])
        if value["supersedes_op_id"] == value["op_id"]:
            raise WireError()
    elif operation == "system_setup.apply":
        legacy._uuid(value["challenge_id"])
        legacy._token(value["nonce"])
        _integer(value["utc_seconds"], 1767225600, 4102444799)
        if type(value["country"]) is not str or re.fullmatch(r"[A-Z]{2}", value["country"]) is None:
            raise WireError()
    if operation == "system_setup.apply":
        value = {**value, "utc_seconds": int(value["utc_seconds"])}
    return value


def decode_request(raw):
    return validate_request(parse_json(raw))


def error(rpc_id, code):
    return {"v": 2, "id": rpc_id, "ok": False,
            "error": code if code in ERRORS else "unavailable"}


def response(rpc_id, result):
    return {"v": 2, "id": rpc_id, "ok": True, "result": result}


def _identity(value, context):
    _closed(value, {"frame_id", "spki_sha256", "publication_op_id"})
    legacy._uuid(value["frame_id"])
    legacy._uuid(value["publication_op_id"])
    legacy._token(value["spki_sha256"])
    for key in ("frame_id", "spki_sha256"):
        if context.get(key) is not None and value[key] != context[key]:
            raise WireError("identity_mismatch")


def validate_response(value, *, operation, context):
    if type(value) is not dict:
        raise WireError()
    legacy._integer(value.get("v"), 2)
    if type(value.get("ok")) is not bool:
        raise WireError()
    _nullable_uuid(value.get("id"))
    if value.get("id") != context.get("rpc_id"):
        raise WireError()
    if not value["ok"]:
        _closed(value, {"v", "id", "ok", "error"})
        if type(value["error"]) is not str or value["error"] not in ERRORS:
            raise WireError()
        return value
    _closed(value, {"v", "id", "ok", "result"})
    if value["id"] is None:
        raise WireError()
    result = value["result"]
    if operation == "system_setup.negotiate":
        _closed(result, {"selected_version", "latest_operation_id", "capabilities"})
        legacy._integer(result["selected_version"], 2)
        _nullable_uuid(result["latest_operation_id"])
        if result["capabilities"] != list(CAPABILITIES):
            raise WireError()
    elif operation == "system_setup.challenge":
        _closed(result, {"op_id", "challenge_id", "nonce", "boot_id", "issued_boottime_ns",
                         "expires_boottime_ns"})
        for key in ("op_id", "challenge_id", "boot_id"):
            legacy._uuid(result[key])
        legacy._token(result["nonce"])
        _integer(result["issued_boottime_ns"])
        _integer(result["expires_boottime_ns"])
        if result["expires_boottime_ns"] - result["issued_boottime_ns"] != 30_000_000_000:
            raise WireError()
    elif operation == "system_setup.apply":
        _closed(result, {"op_id", "state", "submission", "durability", "frame_id", "owner_id",
                         "claim_request_id", "next_step"})
        if (result["state"], result["submission"], result["durability"], result["next_step"]) != (
                "applying", "registered", "not_confirmed", "status"):
            raise WireError()
    else:
        keys = {"op_id", "state", "frame_id", "owner_id", "claim_request_id", "normal_identity",
                "https_origin", "completion_id", "next_step"}
        if operation == "system_setup.continue":
            keys.add("action")
        _closed(result, keys)
        if (type(result["state"]) is not str or result["state"] not in STATES
                or type(result["next_step"]) is not str or result["next_step"] not in NEXT_STEPS):
            raise WireError()
        if result["normal_identity"] is not None:
            _identity(result["normal_identity"], context)
        _nullable_uuid(result["completion_id"])
        if result["https_origin"] is not None:
            origin(result["https_origin"])
        if result["state"] in {"tls_ready", "wifi_pending", "complete"}:
            if result["normal_identity"] is None:
                raise WireError()
            expected_next = ("wait_origin" if result["https_origin"] is None else
                             "photo_enroll" if result["state"] == "complete" else "wifi")
            if result["next_step"] != expected_next:
                raise WireError()
        if (result["completion_id"] is not None) != (result["state"] == "complete"):
            raise WireError()
        if operation == "system_setup.continue":
            expected_state = {"publication_finalized": "tls_ready", "wifi_pending": "wifi_pending",
                              "completion_finalized": "complete", "already_complete": "complete"}
            if type(result["action"]) is not str or expected_state.get(result["action"]) != result["state"]:
                raise WireError()
    for key in ("op_id", "frame_id", "owner_id", "claim_request_id"):
        if key in result:
            legacy._uuid(result[key])
            if context.get(key) is not None and result[key] != context[key]:
                raise WireError()
    return value


def decode_response(raw, *, operation, context):
    return validate_response(parse_json(raw), operation=operation, context=context)
