"""Nonce-bound TLS identity proof using an existing physical LAN QR secret.

Only the nonce travels over unauthenticated HTTP. This endpoint neither grants
access nor creates trust when the client has already lost that QR secret.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from uuid import UUID

import anyio
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError, field_validator

from inky_web import auth
from inky_web.api.photo_access import public_identity

PROOF_PATH = "/api/auth/legacy-tls-proof"
MAX_BODY_BYTES = 2048
UNAVAILABLE = "Preuve HTTPS indisponible"
limiter = auth.LoginRateLimiter(max_attempts=30)
router = APIRouter(prefix="/auth", tags=["auth"])


class ProofRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: int = Field(strict=True, ge=1, le=1)
    nonce: StrictStr = Field(min_length=64, max_length=64)

    @field_validator("nonce")
    @classmethod
    def canonical_nonce(cls, value: str) -> str:
        if re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError("Nonce invalide")
        return value


def _message(nonce: str, identity: dict[str, str]) -> bytes:
    url = identity["url"].encode("utf-8")
    return (b"inky-legacy-tls-proof-v1\0" + bytes.fromhex(nonce)
            + UUID(identity["frame_id"]).bytes + bytes.fromhex(identity["spki_sha256"])
            + len(url).to_bytes(2, "big") + url)


def _proof(secret: str, nonce: str, identity: dict[str, str]) -> str:
    return hmac.new(secret.encode("utf-8"), _message(nonce, identity), hashlib.sha256).hexdigest()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Requête invalide")
        result[key] = value
    return result


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status,
                        headers={"Cache-Control": "no-store"})


@router.post("/legacy-tls-proof")
async def legacy_tls_proof(request: Request):
    # One fixed key keeps both history and cardinality bounded, irrespective of
    # forged source/forwarded addresses. No cookie is read or issued here.
    if not limiter.record_and_check("global"):
        return _error(429, "Trop de tentatives — réessaye dans une minute")
    if auth.auth_disabled():
        return _error(409, "L’authentification du cadre est désactivée")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_BODY_BYTES:
            return _error(413, "Requête trop volumineuse")
        body.extend(chunk)
    try:
        payload = ProofRequest.model_validate(json.loads(body, object_pairs_hook=_unique_object))
    except (ValueError, UnicodeError, ValidationError, RecursionError):
        # Do not echo values, attacker-controlled field names or validation ctx.
        return _error(422, "Requête invalide")

    def operation():
        service = request.app.state.auth_service
        with service._lock:
            current = service.credentials
            secret = current.bootstrap_password
            if not isinstance(secret, str) or re.fullmatch(r"[A-Za-z0-9]{16}", secret) is None:
                raise ValueError(UNAVAILABLE)
            # Read only. Never load/create/migrate/chmod credentials or identity.
            durable, expected = auth._read_record(current.path), current.record()
            if (durable.keys() != expected.keys()
                    or any(type(durable[key]) is not type(expected[key])
                           or durable[key] != expected[key] for key in expected)):
                raise ValueError(UNAVAILABLE)
            identity = public_identity(request, with_url=True)
            proof = _proof(secret, payload.nonce, identity)
            return {"v": 1, "nonce": payload.nonce, "identity": identity, "proof": proof}

    try:
        result = await anyio.to_thread.run_sync(operation)
    except (HTTPException, OSError, ValueError, AttributeError, TypeError):
        return _error(503, UNAVAILABLE)
    return JSONResponse(result, headers={"Cache-Control": "no-store"})
