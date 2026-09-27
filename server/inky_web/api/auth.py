"""Auth endpoints: login, logout, and a public status probe."""
from __future__ import annotations

import logging
from urllib.parse import urlsplit

import anyio
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

from inky_web import auth

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=64)

    @field_validator("password")
    @classmethod
    def valid_unicode(cls, value: str) -> str:
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("Le mot de passe contient des caractères Unicode non valides") from None
        return value


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=64)
    new_password: str = Field(min_length=8, max_length=64)

    @field_validator("current_password", "new_password")
    @classmethod
    def valid_unicode(cls, value: str) -> str:
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("Le mot de passe contient des caractères Unicode non valides") from None
        return value


class AuthStatus(BaseModel):
    authenticated: bool
    auth_required: bool
    password_change_supported: bool = True


@router.get("/status", response_model=AuthStatus)
async def status(request: Request) -> AuthStatus:
    if auth.auth_disabled():
        return AuthStatus(authenticated=True, auth_required=False, password_change_supported=False)
    sessions = request.app.state.sessions
    is_authed = sessions.validate(auth.get_session_token(request))
    return AuthStatus(authenticated=is_authed, auth_required=True)


@router.post("/login")
async def login(request: Request, payload: LoginRequest, response: Response) -> AuthStatus:
    if auth.auth_disabled():
        return AuthStatus(authenticated=True, auth_required=False, password_change_supported=False)

    ip = (request.client.host if request.client else "unknown") or "unknown"
    limiter = request.app.state.login_limiter
    if not limiter.record_and_check(ip):
        raise HTTPException(
            status_code=429,
            detail="Trop de tentatives — réessaye dans une minute",
        )

    # AnyIO waits for a started worker on cancellation: do not abandon a mutation
    # or let scrypt block the event loop and idle WebSocket revocation.
    token = await anyio.to_thread.run_sync(request.app.state.auth_service.login, payload.password)
    auth.set_session_cookie(response, token, secure=request.url.scheme == "https")
    logger.info("Login success from %s", ip)
    return AuthStatus(authenticated=True, auth_required=True)


@router.post("/password", response_model=AuthStatus)
async def change_password(request: Request, payload: PasswordChangeRequest, response: Response) -> AuthStatus:
    if auth.auth_disabled():
        raise HTTPException(status_code=409, detail="L’authentification est désactivée sur ce cadre")
    auth.require_auth(request)
    # Native clients omit Origin. Browsers must call their own origin; an
    # authenticated page on another port must not silently rotate this secret.
    origin = request.headers.get("origin")
    if origin is not None:
        actual = urlsplit(str(request.url))
        if origin != f"{actual.scheme}://{actual.netloc}":
            raise HTTPException(status_code=403, detail="Origine de la requête non autorisée")
    ip = (request.client.host if request.client else "unknown") or "unknown"
    if not request.app.state.password_change_limiter.record_and_check(ip):
        raise HTTPException(status_code=429, detail="Trop de tentatives — réessaye dans une minute")
    token = await anyio.to_thread.run_sync(
        request.app.state.auth_service.change_password,
        auth.get_session_token(request), payload.current_password, payload.new_password,
    )
    auth.set_session_cookie(response, token, secure=request.url.scheme == "https")
    return AuthStatus(authenticated=True, auth_required=True)


@router.post("/logout")
async def logout(request: Request, response: Response) -> AuthStatus:
    if auth.auth_disabled():
        return AuthStatus(authenticated=True, auth_required=False, password_change_supported=False)
    sessions = request.app.state.sessions
    sessions.invalidate(auth.get_session_token(request))
    auth.clear_session_cookie(response)
    return AuthStatus(authenticated=False, auth_required=True)
