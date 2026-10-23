"""Initial PHOTO access for the explicit, preconfigured-LAN entrypoint.

The OS owns Wi-Fi and the published hostname. This module owns only a normal
TLS identity and a local media invitation; it never creates Bluetooth owners,
configures radio, or exposes the invitation secret in API responses or logs.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import re
import secrets
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from PIL import Image, ImageDraw

from inky_web.db import data_dir
from inky_web.photo_access import AccessError, token, uuid
from inky_web.services import history
from inky_web.welcome import _draw_centered, _fit_font, _login_qr

INVITATION_RENEW_SECONDS = 60
CERTIFICATE_RENEW_SECONDS = 86400
logger = logging.getLogger(__name__)


class LANRuntimeError(Exception):
    code = "lan_runtime_unavailable"
    exit_status = 78

    def __init__(self):
        super().__init__(self.code)


def validate_lan_origin(raw: str) -> str:
    """Accept a canonical, explicitly supplied HTTPS locator on port8443."""
    try:
        if type(raw) is not str or len(raw) > 512 or not raw.startswith("https://"):
            raise ValueError
        parsed = urlsplit(raw)
        host = parsed.hostname
        if (not host or parsed.username is not None or parsed.password is not None
                or parsed.path or parsed.query or parsed.fragment or parsed.port != 8443):
            raise ValueError
        try:
            address = ipaddress.ip_address(host)
            locator = f"[{address}]" if address.version == 6 else str(address)
        except ValueError:
            if (len(host) > 253 or host != host.lower() or not all(
                    re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                    for label in host.split("."))):
                raise ValueError from None
            locator = host
        if raw != f"https://{locator}:8443":
            raise ValueError
        return raw
    except (ValueError, TypeError, AttributeError):
        raise LANRuntimeError() from None


def invitation_payload(identity, origin: str, invitation_id: str, invitation_token: str) -> str:
    """Return the existing iOS15 PHOTO invitation envelope, never a URL token."""
    try:
        value = {"v": 1, "p": "invite", "id": uuid(identity.frame_id),
                 "k": token(identity.spki_sha256), "url": validate_lan_origin(origin),
                 "i": uuid(invitation_id), "t": token(invitation_token)}
        result = json.dumps(value, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
        if len(result.encode("utf-8")) > 1024:
            raise ValueError
        return result
    except (ValueError, TypeError, AttributeError):
        raise LANRuntimeError() from None


def render_lan_welcome(width: int, height: int, payload: str) -> Image.Image:
    """A light Bento welcome with a large QR, and no IP/password/SSID cards."""
    if type(width) is not int or type(height) is not int or width < 600 or height < 400:
        raise LANRuntimeError()
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    margin = max(12, height // 30)
    gap = max(12, height // 32)
    title_font = _fit_font(draw, "Inky Studio", height * 0.11, width - 2 * margin, bold=True)
    title_bottom = _draw_centered(draw, "Inky Studio", margin, title_font, width, "black")
    top, bottom = title_bottom + gap, height - margin
    card_height = bottom - top
    qr_width = int((width - 2 * margin - gap) * 0.57)
    # The QR already includes its four-module quiet zone. Avoid a second large
    # padding that would unnecessarily reduce its integer module scale.
    qr_padding = max(4, height // 160)
    qr = _login_qr(payload, min(qr_width - 2 * qr_padding, card_height - 2 * qr_padding))
    if qr is None:
        raise LANRuntimeError()
    radius, stroke = max(12, height // 30), max(2, height // 160)
    draw.rounded_rectangle((margin, top, margin + qr_width, bottom),
                           radius=radius, outline="black", width=stroke)
    image.paste(qr, (margin + (qr_width - qr.width) // 2,
                     top + (card_height - qr.height) // 2))
    text_x, text_width = margin + qr_width + gap, width - 2 * margin - qr_width - gap
    draw.rounded_rectangle((text_x, top, text_x + text_width, bottom),
                           radius=radius, outline="black", width=stroke)
    lines = [("Prêt pour", True), ("vos photos", True), ("", False),
             ("Ouvrez Inky Studio", False), ("sur votre iPhone", False),
             ("et scannez ce QR.", False)]
    line_height = max(22, int(height * 0.075))
    y = top + max(gap, (card_height - len(lines) * line_height) // 2)
    for text, bold in lines:
        if text:
            font = _fit_font(draw, text, height * (0.075 if bold else 0.049),
                             text_width - 2 * gap, bold=bold)
            _draw_centered(draw, text, y, font, text_width, "black", x=text_x)
        y += line_height
    return image


async def _owned_work(function, *args):
    """Do not abandon an admitted display/store operation on task cancellation."""
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except BaseException:
            break
    result = task.result()
    if cancelled:
        raise asyncio.CancelledError
    return result


class LANPhotoRuntime:
    def __init__(self, app, origin: str, tls_context):
        self.app = app
        self.origin = validate_lan_origin(origin)
        self.tls_context = tls_context
        self._stop = asyncio.Event()
        self._started = False
        self._tasks = []
        self._work_tasks = set()
        self._invitation_id = self._invitation_token = self._payload = None

    async def _work(self, function, *args):
        if self._stop.is_set():
            raise LANRuntimeError()
        task = asyncio.create_task(_owned_work(function, *args))
        self._work_tasks.add(task)
        try:
            return await task
        finally:
            self._work_tasks.discard(task)

    async def start(self):
        if self._started or self._stop.is_set():
            return
        self._started = True
        store = getattr(self.app.state, "photo_access", None)
        if store is None or not store._lan_bootstrap_enabled:
            raise LANRuntimeError()
        self._tasks.append(asyncio.create_task(self._certificate_loop()))
        try:
            if await self._work(history.count) != 0:
                return
            if not await self._work(store.lan_bootstrap_available):
                return
            self._invitation_id, self._invitation_token = str(uuid4()), secrets.token_hex(32)
            try:
                await self._work(store.begin_lan_bootstrap, self._invitation_id,
                                  self._invitation_token, str(uuid4()))
            except AccessError:
                # A device can have enrolled between the read and transaction.
                if await self._work(store.lan_bootstrap_completed):
                    self._clear_invitation()
                    return
                raise
            self._payload = invitation_payload(self.app.state.frame_identity, self.origin,
                                               self._invitation_id, self._invitation_token)
            shown = await self._work(self._show_welcome)
            if shown and not self._stop.is_set():
                self._tasks.append(asyncio.create_task(self._invitation_loop()))
            elif not self._stop.is_set():
                self._clear_invitation()
        except BaseException as error:
            await self.stop()
            if isinstance(error, asyncio.CancelledError):
                raise
            raise LANRuntimeError() from None

    def _clear_invitation(self):
        self._invitation_id = self._invitation_token = self._payload = None

    def _show_welcome(self):
        display = self.app.state.display
        with display.operation():
            # The photo result and welcome selection share the hardware lock.
            if history.count() != 0 or self._stop.is_set():
                return False
            display.require_available()
            if not self.app.state.photo_access.renew_lan_bootstrap(
                    self._invitation_id, self._invitation_token):
                return False
            info = display.info()
            image = render_lan_welcome(info["width"], info["height"], self._payload)
            path = None
            try:
                with tempfile.NamedTemporaryFile(dir=data_dir(), prefix=".lan-welcome-",
                                                  suffix=".png", delete=False) as stream:
                    path = Path(stream.name)
                    os.fchmod(stream.fileno(), 0o600)
                    image.save(stream, format="PNG")
                display.display_image(path, saturation=0)
            finally:
                if path is not None:
                    path.unlink(missing_ok=True)
            return True

    async def _maintenance_once(self) -> bool:
        if self._invitation_id is None or await self._work(history.count) != 0:
            self._clear_invitation()
            return False
        renewed = await self._work(self.app.state.photo_access.renew_lan_bootstrap,
                                    self._invitation_id, self._invitation_token)
        if not renewed:
            self._clear_invitation()
        return renewed

    async def _invitation_loop(self):
        try:
            while not self._stop.is_set():
                try:
                    await asyncio.wait_for(self._stop.wait(), INVITATION_RENEW_SECONDS)
                    return
                except TimeoutError:
                    if not await self._maintenance_once():
                        return
        except Exception:
            # No replacement authority after expiry/storage/clock uncertainty.
            self._clear_invitation()
            logger.error("Initial PHOTO invitation unavailable; frame restart required")

    def _maintain_certificate(self):
        identity = self.app.state.frame_identity
        renewed = identity.refresh_certificate_if_needed()
        if (renewed.frame_id != identity.frame_id
                or renewed.spki_sha256 != identity.spki_sha256):
            raise LANRuntimeError()
        if renewed.cert_der != identity.cert_der:
            cert, key = renewed.materialize_tls_files()
            self.tls_context.load_cert_chain(cert, key)
            self.app.state.frame_identity = renewed

    async def _certificate_loop(self):
        delay = CERTIFICATE_RENEW_SECONDS
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), delay)
                return
            except TimeoutError:
                try:
                    await self._work(self._maintain_certificate)
                    delay = CERTIFICATE_RENEW_SECONDS
                except Exception:
                    logger.error("LAN TLS certificate maintenance unavailable; retrying")
                    delay = 3600

    async def stop(self):
        self._stop.set()
        cancelled = False
        waiting = asyncio.gather(*self._tasks, return_exceptions=True)
        while not waiting.done():
            try:
                await asyncio.shield(waiting)
            except asyncio.CancelledError:
                cancelled = True
        waiting.result()
        # start() may currently own a display write even when it has not yet
        # installed periodic tasks. Completed tasks are pruned explicitly so
        # synchronous gather completion cannot starve their done callbacks.
        while self._work_tasks:
            pending = tuple(task for task in self._work_tasks if not task.done())
            self._work_tasks.difference_update(tuple(task for task in self._work_tasks if task.done()))
            if not pending:
                break
            work = asyncio.gather(*pending, return_exceptions=True)
            while not work.done():
                try:
                    await asyncio.shield(work)
                except asyncio.CancelledError:
                    cancelled = True
            work.result()
        if self._invitation_id is not None:
            try:
                await _owned_work(self.app.state.photo_access.end_lan_bootstrap,
                                  self._invitation_id, self._invitation_token)
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                logger.error("Initial PHOTO invitation cleanup unavailable")
        self._clear_invitation()
        if cancelled:
            raise asyncio.CancelledError
