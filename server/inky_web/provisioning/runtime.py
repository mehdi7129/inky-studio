"""Application-owned provisioning authority; BLE never owns the display/SPI."""
from __future__ import annotations

import asyncio
import logging
import socket
from contextlib import suppress
from pathlib import Path

from inky_web import auth
from inky_web.provisioning import screen
from inky_web.provisioning.bluez import BlueZServer
from inky_web.provisioning.identity import canonical_uuid, load_or_create_identity, validate_token
from inky_web.provisioning.network import NetworkClient, NetworkUnavailable
from inky_web.provisioning.ownership import OwnershipError, OwnershipStore, credential_epoch
from inky_web.provisioning.transport import GATTTransport


class ProvisioningRuntime:
    def __init__(self, directory: Path, credentials, display, identity=None):
        self.directory = directory
        self.credentials = credentials
        self.display = display
        self.identity = identity or load_or_create_identity(directory)
        self.owners = OwnershipStore(directory, self.epoch)
        self.tls_context = self.identity.ssl_context()
        self.network = NetworkClient()
        self.mutation_lock = asyncio.Lock()
        self._screen_lock = asyncio.Lock()
        self.transport = GATTTransport(self.tls_context, self.command)
        self.bluez = BlueZServer(self.transport, self.identity)
        self.available = False
        self._window_task = None
        self._certificate_task = None
        self._claim_limiter = auth.LoginRateLimiter(max_attempts=12)

    def epoch(self):
        # Observe the durable file, including a CLI reset or a crash between
        # password replace and the in-memory credentials assignment.
        if not self.credentials.credentials.path.is_file():
            raise auth.CredentialFormatError()
        credentials = auth.load_or_create_credentials(self.credentials.credentials.path.parent)
        return credential_epoch(credentials.salt, credentials.digest)

    def prepare_rotation(self, replacement, actor_owner_id):
        self.network.cancel_pending_sync()
        self.owners.prepare_password_rotation(
            self.epoch(), credential_epoch(replacement.salt, replacement.digest), actor_owner_id,
        )

    async def start(self):
        if (self.directory / ".adoption-screen").exists():
            await _display_work(screen.restore, self.display, self.directory)
        self._certificate_task = asyncio.create_task(self._renew_certificate())
        await self.bluez.start()
        self.available = True

    async def _renew_certificate(self):
        while True:
            await asyncio.sleep(60 if not self.available else 86400)
            try:
                await self._maintain_certificate()
            except Exception:
                logging.getLogger(__name__).error("Frame Bluetooth/certificate maintenance unavailable; retrying")

    async def _maintain_certificate(self):
        renewed = await asyncio.to_thread(self.identity.refresh_certificate_if_needed)
        changed = renewed.cert_der != self.identity.cert_der
        if changed:
            cert, key = await asyncio.to_thread(renewed.materialize_tls_files)
            self.tls_context.load_cert_chain(cert, key)
            self.identity = renewed
        # Retry failed registration even when renewal already persisted the new
        # certificate. Otherwise a transient radio failure disables BLE forever.
        if changed or not self.available:
            self.available = False
            await self.bluez.stop()
            self.transport = GATTTransport(self.tls_context, self.command)
            self.bluez = BlueZServer(self.transport, self.identity)
            await self.bluez.start()
            self.available = True

    async def begin_adoption(self):
        async with self.mutation_lock:
            if not self.available or self.display.closing:
                raise NetworkUnavailable("bluetooth_unavailable")
            await self.end_adoption()
            async with self._screen_lock:
                token = self.owners.open_window()
                try:
                    # Do not send the QR or token over HTTP, events or a log.
                    await _display_work(screen.show, self.display, self.directory, self.identity.qr_payload(token))
                except BaseException:
                    self.owners.close_window()
                    await _display_work(screen.restore_if_reserved, self.display, self.directory)
                    raise
                self._window_task = asyncio.create_task(self._expire_window())
                return {"expires_in": 600, "frame_id": self.identity.frame_id}

    async def _expire_window(self):
        await asyncio.sleep(600)
        await self.end_adoption()

    async def end_adoption(self):
        # Detach/cancel the old expiry before acquiring the screen lock. A timer
        # already restoring the panel must drain its SPI operation first.
        task, self._window_task = self._window_task, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
        await _complete(self._clear_screen())

    async def _clear_screen(self):
        async with self._screen_lock:
            self.owners.close_window()
            # Shutdown drains existing SPI work but does not start a second
            # refresh. Keep the durable marker: start() restores it next boot.
            if self.display.closing:
                await _display_work(self.display.release, screen.RESERVATION)
            else:
                await _display_work(screen.restore_if_reserved, self.display, self.directory)

    def authorize(self, owner_id, owner_token):
        return self.owners.authenticate(owner_id, owner_token)

    async def command(self, message: dict):
        request_id = None
        try:
            request_id = canonical_uuid(message.get("id"))
            operation = message.get("op")
            common = {"v", "id", "op", "owner_id", "owner_token"}
            extras = {"claim": {"claim_token"}, "status": set(), "wifi.scan": set(),
                      "wifi.begin": {"ssid", "security", "password"},
                      "wifi.status": {"transaction_id"}, "wifi.cancel": {"transaction_id"},
                      "owner.revoke": set()}
            if (type(message.get("v")) is not int or message["v"] != 1
                    or not isinstance(operation, str) or operation not in extras
                    or set(message) != common | extras[operation]):
                raise OwnershipError("invalid_request")
            owner_id = canonical_uuid(message["owner_id"])
            owner_token = validate_token(message["owner_token"])
            async with self.mutation_lock:
                if self.display.closing:
                    raise NetworkUnavailable("service_stopping")
                if operation == "claim":
                    if not self._claim_limiter.record_and_check("adoption"):
                        raise OwnershipError("rate_limited")
                    await asyncio.to_thread(
                        self.owners.claim, message["claim_token"], owner_id,
                        owner_token, request_id, self.epoch(),
                    )
                    await self.end_adoption()
                    result = self._frame_status()
                else:
                    self.authorize(owner_id, owner_token)
                    if operation == "status":
                        result = self._frame_status()
                    elif operation == "wifi.scan":
                        result = await self.network.call("scan", owner_id=owner_id)
                    elif operation == "wifi.begin":
                        result = await self.network.call(
                            "begin", id=request_id, owner_id=owner_id,
                            ssid=message["ssid"], security=message["security"], password=message["password"],
                        )
                    elif operation in {"wifi.status", "wifi.cancel"}:
                        transaction_id = canonical_uuid(message["transaction_id"])
                        result = await self.network.call(
                            "status" if operation == "wifi.status" else "cancel",
                            id=transaction_id, owner_id=owner_id,
                        )
                    else:
                        await self.network.call("cancel_owner", owner_id=owner_id)
                        await asyncio.to_thread(self.owners.revoke, owner_id)
                        result = {"revoked": True}
            return {"v": 1, "id": request_id, "ok": True, "result": result}
        except OwnershipError as exc:
            code = exc.code
        except NetworkUnavailable as exc:
            code = str(exc)
        except (TypeError, ValueError):
            code = "invalid_request"
        except Exception:
            code = "unavailable"
        return {"v": 1, "id": request_id, "ok": False, "error": code}

    def _frame_status(self):
        return {"frame_id": self.identity.frame_id, "https_port": 8443,
                "hostname": socket.gethostname().removesuffix(".local") + ".local"}

    async def confirm(self, owner_id, owner_token, transaction_id):
        async with self.mutation_lock:
            if self.display.closing:
                raise NetworkUnavailable("service_stopping")
            self.authorize(owner_id, owner_token)
            return await self.network.call("confirm", id=canonical_uuid(transaction_id), owner_id=owner_id)

    async def stop(self):
        self.available = False
        if self._certificate_task:
            self._certificate_task.cancel()
            await asyncio.gather(self._certificate_task, return_exceptions=True)
        try:
            # Stop accepting BLE commands before cancelling the helper's single
            # transaction. Otherwise a late begin could follow that cancellation.
            await self.bluez.stop()
        finally:
            try:
                async with self.mutation_lock:
                    try:
                        await _complete(asyncio.to_thread(self.network.cancel_pending_sync))
                    except NetworkUnavailable:
                        # Shutdown still releases hardware. The local reset CLI
                        # independently requires cancellation before writing an
                        # epoch, so an unavailable helper cannot bypass revocation.
                        logging.getLogger(__name__).warning("Pending Wi-Fi cancellation unavailable during shutdown")
            finally:
                try:
                    await self.end_adoption()
                finally:
                    self.owners.close()


async def _display_work(function, *arguments):
    """Cancellation cannot leave a physical refresh running without its owner."""
    return await _complete(asyncio.to_thread(function, *arguments))


async def _complete(awaitable):
    task = asyncio.create_task(awaitable)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        with suppress(BaseException):
            task.result()
        raise
