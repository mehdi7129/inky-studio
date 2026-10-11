"""Strict lot A grammar; no ownership, radio or initialization authority.

JSON integers retain their original lexeme. Value equality cannot turn 1.0,
1e0 or true into a protocol version. Errors never reflect private input.
"""
from __future__ import annotations

import json
import math

from .identity import canonical_uuid, validate_token
from .transport import MAX_MESSAGE, _check_depth, _unique_object

PUBLIC_ERRORS = frozenset({
    "invalid_request", "unauthorized", "qr_unavailable", "request_conflict",
    "request_not_found", "epoch_changed", "owner_capacity", "rate_limited",
    "service_stopping", "recovery_required", "unavailable",
})


class WireError(ValueError):
    def __init__(self, reason: str = "invalid_request"):
        self.reason = reason
        super().__init__(reason)


class JsonInteger(int):
    def __new__(cls, lexeme):
        result = int.__new__(cls, lexeme)
        result.lexeme = lexeme
        return result


def _float(lexeme):
    value = float(lexeme)
    if not math.isfinite(value):
        raise WireError()
    return value


def _constant(_):
    raise WireError()


def parse_json(raw: bytes, *, limit: int = MAX_MESSAGE) -> dict:
    if type(raw) is not bytes or not 1 <= len(raw) <= limit:
        raise WireError("size_limit")
    try:
        source = raw.decode("utf-8")
    except UnicodeError:
        raise WireError("invalid_encoding") from None
    try:
        value = json.loads(source, object_pairs_hook=_unique_object,
                           parse_int=JsonInteger, parse_float=_float,
                           parse_constant=_constant)
        _check_depth(value)
        if type(value) is not dict:
            raise WireError()
        # JSON permits escaped unpaired surrogates; they are not valid UTF-8
        # application strings and must not leak into responses or storage.
        pending = [value]
        while pending:
            item = pending.pop()
            if isinstance(item, dict):
                pending.extend(item.keys())
                pending.extend(item.values())
            elif isinstance(item, list):
                pending.extend(item)
            elif isinstance(item, str):
                item.encode("utf-8")
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise WireError() from None


def _integer(value, expected=None, *, minimum=None, maximum=None):
    # Plain ints are allowed for trusted local producers; parsed floats/bools
    # remain different types. JsonInteger preserves the exact wire lexeme.
    if type(value) not in (int, JsonInteger):
        raise WireError()
    if isinstance(value, JsonInteger) and value.lexeme != str(int(value)):
        raise WireError()
    if expected is not None and value != expected:
        raise WireError()
    if minimum is not None and value < minimum or maximum is not None and value > maximum:
        raise WireError()


def _uuid(value):
    if type(value) is not str:
        raise WireError()
    try:
        return canonical_uuid(value)
    except (ValueError, TypeError):
        raise WireError() from None


def _token(value):
    if type(value) is not str:
        raise WireError()
    try:
        return validate_token(value)
    except (ValueError, TypeError):
        raise WireError() from None


def request_id(message: dict) -> str | None:
    try:
        return _uuid(message.get("id"))
    except (WireError, AttributeError):
        return None


def decode_qr(raw: bytes) -> dict:
    value = parse_json(raw, limit=512)
    if value.get("v") == 1 and set(value) == {"v", "id", "k", "t"}:
        _integer(value["v"], 1)
    else:
        if set(value) != {"v", "p", "id", "k", "t"} or value.get("p") != "bootstrap":
            raise WireError()
        _integer(value["v"], 2)
    _uuid(value["id"])
    _token(value["k"])
    _token(value["t"])
    return value


def decode_metadata(raw: bytes) -> dict:
    value = parse_json(raw, limit=128)
    if set(value) != {"v", "p", "id", "cert_length"} or value.get("p") != "bootstrap":
        raise WireError()
    _integer(value["v"], 2)
    _uuid(value["id"])
    certificate_parts(value["cert_length"])
    return value


def validate_request(value: dict) -> dict:
    if type(value) is not dict:
        raise WireError()
    op = value.get("op")
    extras = {"bootstrap.claim": "claim_token", "bootstrap.status": "claim_request_id"}
    if type(op) is not str or op not in extras:
        raise WireError()
    extra = extras[op]
    if set(value) != {"v", "id", "op", "owner_id", "owner_token", extra}:
        raise WireError()
    _integer(value["v"], 1)
    _uuid(value["id"])
    _uuid(value["owner_id"])
    _token(value["owner_token"])
    (_token if op == "bootstrap.claim" else _uuid)(value[extra])
    return value


def decode_request(raw: bytes) -> dict:
    return validate_request(parse_json(raw))


def decode_response(raw: bytes, *, context: dict) -> dict:
    value = parse_json(raw)
    _integer(value.get("v"), 1)
    if type(value.get("ok")) is not bool or "id" not in value:
        raise WireError()
    if value["id"] is not None:
        _uuid(value["id"])
        if value["id"] != context.get("rpc_id"):
            raise WireError()
    if value["ok"]:
        if set(value) != {"v", "id", "ok", "result"} or value["id"] is None:
            raise WireError()
        result = value["result"]
        if type(result) is not dict or set(result) != {
            "frame_id", "owner_id", "claim_request_id", "factory_state", "next_step",
        }:
            raise WireError()
        for key in ("frame_id", "owner_id", "claim_request_id"):
            _uuid(result[key])
            if result[key] != context.get(key):
                raise WireError("identity_mismatch" if key == "frame_id" else "invalid_request")
        if result["factory_state"] != "adopted" or result["next_step"] != "system_setup":
            raise WireError()
    elif (set(value) != {"v", "id", "ok", "error"}
          or type(value["error"]) is not str or value["error"] not in PUBLIC_ERRORS):
        raise WireError()
    return value


def certificate_parts(length: int) -> tuple[int, int]:
    _integer(length, minimum=1, maximum=960)
    return min(480, length), max(0, length - 480)


def att_capacity(mtu: int) -> int:
    if type(mtu) is not int or mtu < 23:
        raise WireError()
    return min(244, mtu - 3)


def check_profile(qr: str, service: str, tls: str, alpn: str | None) -> bool:
    return ((qr, service, tls, alpn) == ("bootstrap", "bootstrap", "bootstrap", "inky-bootstrap/1")
            or (qr, service, tls, alpn) == ("normal-v1", "normal-v1", "normal-v1", None))


def encode_qr(frame_id: str, pin: str, token: str) -> str:
    value = {"v": 2, "p": "bootstrap", "id": _uuid(frame_id), "k": _token(pin), "t": _token(token)}
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True)
