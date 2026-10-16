"""HTTPS-only individual PHOTO access. Never reuse BLE/bootstrap credentials."""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from functools import partial
from urllib.parse import urlsplit

import anyio
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator

from inky_web import auth
from inky_web.photo_access import AccessError, Principal, token, uuid

router = APIRouter(prefix="/auth", tags=["photo-access"])


class DeviceCredential(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: StrictStr = Field(min_length=36, max_length=36)
    device_token: StrictStr = Field(min_length=64, max_length=64, repr=False)

    @field_validator("device_id")
    @classmethod
    def canonical_id(cls, value):
        return uuid(value)

    @field_validator("device_token")
    @classmethod
    def canonical_token(cls, value):
        return token(value)


class Enrollment(DeviceCredential):
    request_id: StrictStr = Field(min_length=36, max_length=36)

    @field_validator("request_id")
    @classmethod
    def canonical_request(cls, value):
        return uuid(value)


class Invitation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invitation_id: StrictStr = Field(min_length=36, max_length=36)
    invitation_token: StrictStr = Field(min_length=64, max_length=64, repr=False)
    request_id: StrictStr = Field(min_length=36, max_length=36)
    ttl_seconds: int = Field(default=300, ge=1, le=300, strict=True)

    @field_validator("invitation_id", "request_id")
    @classmethod
    def canonical_id(cls, value):
        return uuid(value)

    @field_validator("invitation_token")
    @classmethod
    def canonical_token(cls, value):
        return token(value)


class Claim(Enrollment):
    invitation_id: StrictStr = Field(min_length=36, max_length=36)
    invitation_token: StrictStr = Field(min_length=64, max_length=64, repr=False)

    @field_validator("invitation_id")
    @classmethod
    def canonical_invitation(cls, value):
        return uuid(value)

    @field_validator("invitation_token")
    @classmethod
    def canonical_invitation_token(cls, value):
        return token(value)


def require_https(request: Request):
    # serve() disables Uvicorn proxy headers. No forwarded header is consulted.
    if request.scope.get("scheme") != "https":
        raise HTTPException(403, "Une connexion HTTPS au cadre est requise")
    if auth.auth_disabled():
        raise HTTPException(409, "L’authentification du cadre est désactivée")
    origin = request.headers.get("origin")
    if origin is not None and origin != f"https://{request.url.netloc}":
        raise HTTPException(403, "Origine non autorisée")


def store(request):
    require_https(request)
    value = getattr(request.app.state, "photo_access", None)
    if value is None:
        raise HTTPException(503, "Accès individuel indisponible")
    return value


def actor(request) -> Principal:
    sessions = request.app.state.sessions
    session = auth.get_session_token(request)
    if not sessions.validate(session):
        raise HTTPException(401, "Authentification requise")
    principal = sessions.principal(session)
    if principal is None or principal.role != "owner":
        raise HTTPException(403, "Autorisation du propriétaire requise")
    return principal


def public_identity(request, *, with_url=False):
    identity = getattr(request.app.state, "frame_identity", None)
    if identity is None:
        raise HTTPException(503, "Identité HTTPS du cadre indisponible")
    # Use only the already-loaded public certificate, never identity.json/key_pem.
    cert = x509.load_pem_x509_certificate(identity.cert_pem)
    spki = cert.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    result = {"frame_id": uuid(identity.frame_id), "spki_sha256": hashlib.sha256(spki).hexdigest()}
    if with_url:
        raw = os.environ.get("INKY_STUDIO_PHOTO_ACCESS_URL", "")
        try:
            parsed = urlsplit(raw)
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                    or parsed.password is not None or parsed.query or parsed.fragment
                    or parsed.path not in ("", "/") or len(parsed.netloc) > 259
                    or not re.fullmatch(r"[a-zA-Z0-9.\[\]:-]+", parsed.netloc)
                    or (parsed.port is not None and not 1 <= parsed.port <= 65535)):
                raise ValueError
            result["url"] = f"https://{parsed.netloc}"
        except ValueError:
            raise HTTPException(503, "Adresse HTTPS de partage non configurée") from None
    return result


async def call(function, *args):
    try:
        return await anyio.to_thread.run_sync(partial(function, *args))
    except AccessError as exc:
        code = {"unauthorized": 401, "forbidden": 403, "conflict": 409, "capacity": 409}.get(exc.code, 409)
        raise HTTPException(code, "Accès individuel invalide ou indisponible") from None
    except ValueError:
        raise HTTPException(422, "Identifiant invalide") from None
    except (OSError, sqlite3.Error):
        raise HTTPException(503, "Stockage des accès indisponible") from None


def throttle(request):
    if not request.app.state.photo_access_limiter.record_and_check("global"):
        raise HTTPException(429, "Trop de tentatives — réessaye dans une minute")


@router.post("/devices/enroll")
async def enroll(request: Request, payload: Enrollment):
    value = store(request)
    identity = public_identity(request)
    # Do not promote a media/device cookie. Only the existing password-login
    # session is a migration authority, and it must still be alive at commit.
    def operation():
        with request.app.state.auth_service._lock:
            sessions = request.app.state.sessions
            with sessions._lock:
                session = auth.get_session_token(request)
                if not sessions.validate(session):
                    raise AccessError()
                if sessions.principal(session) is not None:
                    raise AccessError("forbidden")
                current = request.app.state.auth_service.credentials
                ram_epoch = hashlib.sha256(b"inky-photo-epoch-v1\0" + current.salt + current.digest).hexdigest()
                if ram_epoch != value._epoch():
                    raise AccessError()
                return value.enroll(payload.device_id, payload.device_token, payload.request_id)
    principal = await call(operation)
    # Preserve the legacy cookie so a timed-out enrollment can retry identically.
    # The client then calls device-session using its pre-saved credential.
    return {"device_id": principal.device_id, "role": principal.role, "identity": identity}


@router.post("/device-session")
async def device_session(request: Request, payload: DeviceCredential, response: Response):
    value = store(request)
    throttle(request)
    identity = public_identity(request)
    def operation():
        with request.app.state.auth_service._lock:
            principal = value.authenticate(payload.device_id, payload.device_token)
            return principal, request.app.state.sessions.create(principal)
    principal, session = await call(operation)
    auth.set_session_cookie(response, session, secure=True)
    return {"authenticated": True, "device_id": principal.device_id, "role": principal.role, "identity": identity}


@router.post("/invitations")
async def create_invitation(request: Request, payload: Invitation):
    value = store(request)
    principal = actor(request)
    identity = public_identity(request, with_url=True)
    result = await call(value.invite, principal, payload.invitation_id, payload.invitation_token,
                        payload.request_id, payload.ttl_seconds)
    return {**result, "role": "media", "identity": identity}


@router.post("/invitations/claim")
async def claim_invitation(request: Request, payload: Claim, response: Response):
    value = store(request)
    throttle(request)
    identity = public_identity(request)
    def operation():
        with request.app.state.auth_service._lock:
            principal = value.claim(payload.invitation_id, payload.invitation_token,
                                    payload.device_id, payload.device_token, payload.request_id)
            return principal, request.app.state.sessions.create(principal)
    principal, session = await call(operation)
    auth.set_session_cookie(response, session, secure=True)
    return {"authenticated": True, "device_id": principal.device_id, "role": principal.role, "identity": identity}


@router.delete("/invitations/{invitation_id}")
async def revoke_invitation(request: Request, invitation_id: str):
    await call(store(request).revoke_invitation, actor(request), invitation_id)
    return {"revoked": True}


@router.get("/devices")
async def list_devices(request: Request):
    return {"devices": await call(store(request).devices, actor(request))}


@router.get("/devices/{device_id}")
async def get_device(request: Request, device_id: str):
    result = await call(store(request).devices, actor(request), device_id)
    if not result:
        raise HTTPException(404, "Appareil inconnu")
    return result[0]


@router.delete("/devices/{device_id}")
async def revoke_device(request: Request, device_id: str):
    await call(store(request).revoke_device, actor(request), device_id)
    request.app.state.sessions.invalidate_device(device_id)
    return {"revoked": True}
