"""Closed SoftAP QR and untrusted certificate preface; neither grants authority."""
from __future__ import annotations

import base64
import json
import struct

from . import bootstrap_wire as wire

ENDPOINT = "tcp://192.168.4.1:9443"
MAX_PREFACE = 4096
MAX_CERTIFICATE = 2048


def _network(ssid, password):
    if (type(ssid) is not str or not 1 <= len(ssid.encode("utf-8")) <= 32
            or any(ord(char) < 32 or ord(char) == 127 for char in ssid)
            or type(password) is not str or not 8 <= len(password) <= 63
            or any(not 32 <= ord(char) <= 126 for char in password)):
        raise wire.WireError()


def encode_qr(frame_id, pin, token, ssid, password):
    _network(ssid, password)
    value = {"v": 3, "p": "softap", "id": wire._uuid(frame_id), "k": wire._token(pin),
             "t": wire._token(token), "s": ssid, "w": password, "u": ENDPOINT}
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True)


def decode_qr(raw):
    value = wire.parse_json(raw, limit=1024)
    if set(value) != {"v", "p", "id", "k", "t", "s", "w", "u"}:
        raise wire.WireError()
    wire._integer(value["v"], 3)
    if value["p"] != "softap" or value["u"] != ENDPOINT:
        raise wire.WireError()
    wire._uuid(value["id"])
    wire._token(value["k"])
    wire._token(value["t"])
    _network(value["s"], value["w"])
    return value


def encode_preface(frame_id, certificate, *, bootstrap):
    if type(certificate) is not bytes or not 1 <= len(certificate) <= MAX_CERTIFICATE:
        raise wire.WireError()
    if type(bootstrap) is not bool:
        raise wire.WireError()
    raw = json.dumps({"v": 1, "p": "bootstrap" if bootstrap else "normal",
                      "id": wire._uuid(frame_id), "c": base64.b64encode(certificate).decode("ascii")},
                     separators=(",", ":")).encode("ascii")
    if len(raw) > MAX_PREFACE:
        raise wire.WireError()
    return struct.pack("!I", len(raw)) + raw
