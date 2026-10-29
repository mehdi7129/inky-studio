"""Small HTTP surface: physical QR display and pinned-HTTPS confirmation."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from inky_web import auth
from inky_web.provisioning.network import NetworkUnavailable
from inky_web.provisioning.ownership import OwnershipError

router = APIRouter(prefix="/provisioning", tags=["provisioning"])
CONFIRM_PATH = "/api/provisioning/wifi/confirm"


class Confirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transaction_id: str = Field(min_length=36, max_length=36)


def runtime(request):
    value = getattr(request.app.state, "provisioning", None)
    if value is None:
        raise HTTPException(status_code=503, detail="Bluetooth indisponible sur cette version du cadre")
    return value


def same_origin(request):
    origin = request.headers.get("origin")
    if origin is not None and origin != f"{request.url.scheme}://{request.url.netloc}":
        raise HTTPException(status_code=403, detail="Origine non autorisée")


def owner_headers(request):
    if request.url.scheme != "https":
        raise HTTPException(status_code=403, detail="Une connexion HTTPS au cadre est requise")
    owner_id = request.headers.get("x-inky-owner-id")
    token = request.headers.get("x-inky-owner-token")
    if owner_id is None or token is None or len(owner_id) != 36 or len(token) != 64:
        raise HTTPException(status_code=401, detail="Autorisation du téléphone requise")
    return owner_id, token


@router.get("/capabilities")
async def capabilities(request: Request):
    value = getattr(request.app.state, "provisioning", None)
    ready = False
    if value and value.available:
        try:
            health = await value.network.call("health")
            ready = health.get("ready") is True and health.get("protocol") == 1
        except NetworkUnavailable:
            pass
    return {"bluetooth": ready, "protocol": 1,
            "https_port": 8443 if value else None}


@router.post("/adoption/window")
async def adoption_window(request: Request):
    auth.require_auth(request)
    same_origin(request)
    value = runtime(request)
    try:
        return await value.begin_adoption()
    except NetworkUnavailable:
        raise HTTPException(status_code=503, detail="Bluetooth indisponible sur ce cadre") from None


@router.delete("/adoption/window")
async def close_window(request: Request):
    auth.require_auth(request)
    same_origin(request)
    value = runtime(request)
    async with value.mutation_lock:
        await value.end_adoption()
    return {"closed": True}


@router.post("/wifi/confirm")
async def confirm(request: Request, payload: Confirmation):
    # This route deliberately does not require a previous cookie: the new LAN
    # may make that origin unreachable. Its owner credential is mandatory and
    # the same TLS identity is validated by the iPhone before sending it.
    same_origin(request)
    owner_id, token = owner_headers(request)
    try:
        result = await runtime(request).confirm(owner_id, token, payload.transaction_id)
        return {"ok": True, "result": result}
    except OwnershipError:
        raise HTTPException(status_code=401, detail="Autorisation du téléphone révoquée ou invalide") from None
    except (ValueError, NetworkUnavailable):
        raise HTTPException(status_code=409, detail="La configuration Wi-Fi ne peut plus être confirmée") from None
