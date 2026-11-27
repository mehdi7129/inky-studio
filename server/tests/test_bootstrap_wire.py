"""Shared raw proposal vectors: grammar proof only, no TLS/hardware claim."""
import json
from pathlib import Path

import pytest

from inky_web.provisioning import bootstrap_wire as wire

VECTORS = json.loads((Path(__file__).resolve().parents[2] /
                     "docs/inkyos/bootstrap-wire-proposal/vectors.json").read_text())


@pytest.mark.parametrize("case", VECTORS["raw_cases"], ids=lambda case: case["name"])
def test_shared_raw_grammar(case):
    raw = bytes.fromhex(case["input_utf8_hex"])
    stage = case["stage"]
    decoder = {"qr": wire.decode_qr, "metadata": wire.decode_metadata,
               "claim": wire.decode_request, "status": wire.decode_request}.get(stage)
    expected = case["expected"]

    def decode():
        return decoder(raw) if decoder else wire.decode_response(raw, context=case["context"])

    if expected["accept"]:
        value = decode()
        if "profile" in expected:
            assert ("bootstrap" if value.get("p") == "bootstrap" else "normal-v1") == expected["profile"]
    else:
        with pytest.raises(wire.WireError) as error:
            decode()
        assert error.value.reason == expected["reason"]


@pytest.mark.parametrize("case", VECTORS["profile_matrix"])
def test_shared_profile_crossings(case):
    assert wire.check_profile(case["qr"], case["service"], case["tls"],
                              case["negotiated_alpn"]) is case["allowed"]


@pytest.mark.parametrize("case", [case for case in VECTORS["binary_recipes"]
                                  if case["kind"] in ("certificate_lengths", "att_capacity")])
def test_shared_binary_bounds(case):
    if case["kind"] == "certificate_lengths":
        assert wire.certificate_parts(case["cert_length"]) == (case["part0"], case["part1"])
    else:
        assert wire.att_capacity(case["mtu"]) == case["expected_capacity"]
        assert wire.att_capacity(case["mtu"]) - 5 == case["expected_tls_bytes"]


@pytest.mark.parametrize("raw", [
    b'{"v":NaN}', b'{"v":Infinity}', b'{"v":1e999}', b'{"v":"\\ud800"}',
    b'{"v":' + b'[' * 33 + b'0' + b']' * 33 + b'}',
    '{"v":1}'.encode("utf-16"), b'[]', b'null',
])
def test_invalid_application_encoding_and_depth(raw):
    with pytest.raises(wire.WireError):
        wire.parse_json(raw)


@pytest.mark.parametrize("mtu", [22, 0, -1, True, 23.0])
def test_att_capacity_requires_real_integer_minimum(mtu):
    with pytest.raises(wire.WireError):
        wire.att_capacity(mtu)


def test_request_id_never_echoes_an_invalid_value():
    assert wire.request_id({"id": "private bad value"}) is None
    assert wire.request_id({"id": False}) is None


def test_integer_lexeme_survives_parse():
    value = wire.parse_json(b'{"v":1,"other":1.0}')
    assert value["v"].lexeme == "1"
    assert type(value["other"]) is float


def response_context():
    return {"rpc_id": "00000000-0000-4000-8000-000000000004",
            "frame_id": "00000000-0000-4000-8000-000000000001",
            "owner_id": "00000000-0000-4000-8000-000000000002",
            "claim_request_id": "00000000-0000-4000-8000-000000000003"}


def success_response(context):
    return {"v": 1, "id": context["rpc_id"], "ok": True, "result": {
        **{key: context[key] for key in ("frame_id", "owner_id", "claim_request_id")},
        "factory_state": "adopted", "next_step": "system_setup",
    }}


@pytest.mark.parametrize("rpc_id", [None, "00000000-0000-4000-8000-000000000004"])
def test_null_id_cannot_acknowledge_success_even_with_matching_owner_receipt(rpc_id):
    context = {**response_context(), "rpc_id": rpc_id}
    response = {**success_response(response_context()), "id": None}
    with pytest.raises(wire.WireError, match="^invalid_request$"):
        wire.decode_response(json.dumps(response).encode(), context=context)


def test_null_error_is_readable_but_cannot_correlate_a_pending_claim():
    context = response_context()
    response = {"v": 1, "id": None, "ok": False, "error": "unauthorized"}
    parsed = wire.decode_response(json.dumps(response).encode(), context=context)
    assert parsed["ok"] is False
    assert parsed["id"] is None and parsed["id"] != context["rpc_id"]


@pytest.mark.parametrize("field", ["frame_id", "owner_id", "claim_request_id"])
def test_success_must_match_all_bound_identities(field):
    context = response_context()
    response = success_response(context)
    response["result"][field] = "00000000-0000-4000-8000-000000000009"
    reason = "identity_mismatch" if field == "frame_id" else "invalid_request"
    with pytest.raises(wire.WireError, match=f"^{reason}$"):
        wire.decode_response(json.dumps(response).encode(), context=context)


def test_failure_canonical_id_must_match_current_rpc():
    response = {"v": 1, "id": "00000000-0000-4000-8000-000000000009",
                "ok": False, "error": "unauthorized"}
    with pytest.raises(wire.WireError, match="^invalid_request$"):
        wire.decode_response(json.dumps(response).encode(), context=response_context())
