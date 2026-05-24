"""Auth endpoints: login, logout, and a public status probe."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from inky_web import auth

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=64)


class AuthStatus(BaseModel):
    authenticated: bool
    auth_required: bool


@router.get("/status", response_model=AuthStatus)
async def status(request: Request) -> AuthStatus:
    if auth.auth_disabled():
        return AuthStatus(authenticated=True, auth_required=False)
    sessions = request.app.state.sessions
    is_authed = sessions.validate(auth.get_session_token(request))
    return AuthStatus(authenticated=is_authed, auth_required=True)


@router.post("/login")
async def login(request: Request, payload: LoginRequest, response: Response) -> AuthStatus:
    if auth.auth_disabled():
        return AuthStatus(authenticated=True, auth_required=False)

    ip = (request.client.host if request.client else "unknown") or "unknown"
    limiter = request.app.state.login_limiter
    if not limiter.record_and_check(ip):
        raise HTTPException(
            status_code=429,
            detail="Trop de tentatives — réessaye dans une minute",
        )

    creds = request.app.state.credentials
    if payload.password != creds.password:
        logger.warning("Bad login attempt from %s", ip)
        raise HTTPException(status_code=401, detail="Mot de passe incorrect")

    sessions = request.app.state.sessions
    token = sessions.create()
    auth.set_session_cookie(response, token)
    logger.info("Login success from %s", ip)
    return AuthStatus(authenticated=True, auth_required=True)


@router.post("/logout")
async def logout(request: Request, response: Response) -> AuthStatus:
    if auth.auth_disabled():
        return AuthStatus(authenticated=True, auth_required=False)
    sessions = request.app.state.sessions
    sessions.invalidate(auth.get_session_token(request))
    auth.clear_session_cookie(response)
    return AuthStatus(authenticated=False, auth_required=True)
