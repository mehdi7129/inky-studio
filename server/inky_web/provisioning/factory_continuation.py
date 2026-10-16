"""Admitted factory -> system setup -> normal TLS with one hardware owner.

All privileged effects are delegated through the attested OS IPC client. Local
journals are retry data, never an OS grant. This module has no installed bypass.
"""
from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from inky_web import auth

from . import bootstrap_wire
from . import system_setup_wire as wire
from .bootstrap_identity import (
    BootstrapIdentityRecoveryRequired,
    ClockResult,
    PreparedFactoryIdentity,
    _atomic_json,
    _lock,
    _read_json,
)
from .bootstrap_runtime import (
    BootstrapApplicationPeer,
    BootstrapPublicIdentity,
    BootstrapRuntime,
)
from .factory import FactoryRecoveryRequired, FactoryState
from .network import NetworkUnavailable
from .ownership import OwnershipError
from .runtime import ProvisioningRuntime
from .system_setup_ipc import SetupUnavailable
from .transport import BOOTSTRAP_PROFILE, GATTTransport, TLSPeer


@dataclass(eq=False)
class SetupSession:
    """Server-local authority lifetime, unrelated to client RESET bytes."""

    session_id: str = field(default_factory=lambda: str(uuid4()))
    generation: int = 0
    active: bool = True
    negotiated: bool = False
    channel: object | None = None
    binding: dict | None = None
    opening: asyncio.Lock = field(default_factory=asyncio.Lock)

    def close(self):
        self.active = self.negotiated = False
        if self.channel is not None:
            self.channel.close()


class _NormalPeer(TLSPeer):
    def _decode_message(self, payload):
        parsed = bootstrap_wire.parse_json(payload)
        # v1 retains its exact existing Python int API after strict JSON parse.
        return json.loads(payload) if parsed.get("v") == 1 else parsed

    async def _dispatch(self, message):
        if message.get("v") == 2:
            return await BootstrapApplicationPeer._dispatch(self, message)
        return await super()._dispatch(message)


class SetupIntents:
    """Bounded exact retry bytes, containing no owner token or Wi-Fi secret."""

    def __init__(self, directory):
        self.path = Path(directory) / "system-setup-intents.json"
        self.lock = Path(directory) / ".system-setup-intents.lock"

    def remember(self, operation_id, value):
        with _lock(self.lock):
            try:
                record = _read_json(self.path, 128 * 1024)
                if (type(record) is not dict or set(record) != {"v", "intents"}
                        or type(record["v"]) is not int or record["v"] != 1
                        or type(record["intents"]) is not dict or len(record["intents"]) > 64):
                    raise ValueError
            except FileNotFoundError:
                record = {"v": 1, "intents": {}}
            old = record["intents"].get(operation_id)
            if old is not None:
                if old != value:
                    raise OwnershipError("request_conflict")
                return
            if len(record["intents"]) >= 64:
                raise OwnershipError("unavailable")
            record["intents"][operation_id] = value
            _atomic_json(self.path, record, exclusive=False)


class FactoryContinuationRuntime(BootstrapRuntime):
    def __init__(self, result, verify_epoch, display, directory, *, system_setup, network,
                 server_factory=None, normal_service_factory=None, monotonic=None):
        kwargs = {}
        if server_factory is not None:
            kwargs["server_factory"] = server_factory
        if monotonic is not None:
            kwargs["monotonic"] = monotonic
        super().__init__(result, verify_epoch, display, directory, **kwargs)
        if system_setup is None or network is None:
            raise TypeError("Attested system and network clients are required")
        self.system_setup, self.network = system_setup, network
        self.normal_service_factory = normal_service_factory
        self.normal_service = None
        self.provisioning = None
        self.identity = None
        self.snapshot = None
        self._historical_completion = None
        self._sessions = set()
        self._session_generation = 0
        self._apply_tasks = {}
        self._challenges = {}
        self._loop = None
        self._normal_lock = asyncio.Lock()
        self._request_stop = self._fail_closed
        self.intents = SetupIntents(directory)
        receipt = self.owners._factory_receipt
        if receipt is None:
            raise FactoryRecoveryRequired()
        prepared = result.prepared_identity
        self.workflow = {
            "initialization_intent": prepared.initialization_intent,
            "initialization_receipt_digest": receipt.digest,
            "frame_id": prepared.frame_id, "spki_sha256": prepared.binding.spki_sha256,
        }

    def bind_stop(self, callback):
        self._request_stop = callback

    def request_stop(self):
        self._fail_closed()
        self._request_stop()

    def prepare_rotation(self, replacement, actor_owner_id):
        # CredentialService calls this under its rotation lock, before durable
        # password replacement. EOF invalidates OS sub-effect admission NOW.
        closed = threading.Event()
        def invalidate():
            try:
                for session in tuple(self._sessions):
                    session.close()
                    if session.channel is not None:
                        self.operations.create(session.channel.drain())
            finally:
                closed.set()
        try:
            same_loop = asyncio.get_running_loop() is self._loop
        except RuntimeError:
            same_loop = False
        if same_loop:
            invalidate()
        else:
            if self._loop is None or not self._loop.is_running():
                raise NetworkUnavailable("service_stopping")
            self._loop.call_soon_threadsafe(invalidate)
            closed.wait()
        self.provisioning.prepare_rotation(replacement, actor_owner_id)

    def historical_completed(self):
        # This value is set only from a validated root completion, never from a
        # client argument, absence of data, epoch or number of active owners.
        return self._historical_completion is not None

    def _verify(self):
        epoch = self._verified_epoch()
        prepared = PreparedFactoryIdentity.reopen(
            self.directory, expected_intent=self.workflow["initialization_intent"],
            expected_binding=self.result.prepared_identity.binding,
        )
        prepared.verify_current_or_unpublished()
        status = self.owners.factory_status()
        if status.identity != prepared.binding or status.state not in (FactoryState.FACTORY, FactoryState.ADOPTED):
            raise FactoryRecoveryRequired()
        return prepared, status, epoch

    def _authorize(self, session, message, *, negotiated=True):
        if not session.active or self._stopping or self.display.closing:
            raise OwnershipError("service_stopping")
        try:
            prepared, status, epoch = self._verify()
        except Exception:
            session.close()
            raise
        if status.state != FactoryState.ADOPTED or status.first_owner_id != message["owner_id"]:
            raise OwnershipError("unauthorized")
        try:
            self.owners.status(message["owner_id"], message["owner_token"],
                               request_id=message["claim_request_id"])
        except OwnershipError:
            session.close()
            raise
        if negotiated and not session.negotiated:
            raise OwnershipError("negotiation_required")
        if session.binding is not None and session.binding["credential_epoch"] != epoch:
            session.close()
            raise OwnershipError("epoch_changed")
        return prepared, epoch

    def _owner_binding(self, session, message, epoch):
        return {**self.workflow, "credential_epoch": epoch, "owner_id": message["owner_id"],
                "claim_request_id": message["claim_request_id"], "session_id": session.session_id}

    async def _channel(self, session, message):
        async with session.opening:
            _, epoch = await asyncio.to_thread(self._authorize, session, message)
            binding = self._owner_binding(session, message, epoch)
            if session.binding is not None and session.binding != binding:
                session.close()
                raise OwnershipError("unauthorized")
            if session.channel is None:
                channel = await self.system_setup.open(binding)
                if not session.active:
                    channel.close()
                    await channel.drain()
                    raise OwnershipError("service_stopping")
                session.channel, session.binding = channel, binding
            return session.channel

    def _peer_factory(self, *, normal=False):
        runtime = self
        base = _NormalPeer if normal else BootstrapApplicationPeer

        class Peer(base):
            def __init__(self, context, handler):
                runtime._session_generation += 1
                self.session = SetupSession(generation=runtime._session_generation)
                runtime._sessions.add(self.session)

                async def dispatch(message):
                    return await runtime.session_command(self.session, message, handler)
                super().__init__(context, dispatch)

            def close(self):
                self.session.close()
                if self.session.channel is not None:
                    runtime.operations.create(self.session.channel.drain())
                runtime._sessions.discard(self.session)
                super().close()

        return Peer

    async def _start(self):
        self._loop = asyncio.get_running_loop()
        prepared, status, _ = await asyncio.to_thread(self._verify)
        if status.state == FactoryState.ADOPTED:
            snapshot = await self.system_setup.inspect(self.workflow)
            snapshot = self._accept_snapshot(snapshot)
            if snapshot["completion"] is not None:
                self._accept_completion(snapshot["completion"], prepared, status)
                # resume is an explicit startup OS policy operation; it never
                # replays historical clock or needs the old phone to be present.
                try:
                    self._accept_snapshot(await self.system_setup.resume(
                        snapshot["completion"]["completion_id"]))
                except SetupUnavailable:
                    # Retain NORMAL + photo while WLAN remains closed by OS.
                    self.snapshot = {**snapshot, "live": {**snapshot["live"],
                        "readiness": "wlan_closed", "https_origin": None}}
                await self._start_normal(prepared.load_current_identity())
                return
            current = prepared.verify_current_or_unpublished()
            if current is not None:
                await self._start_normal(current)
                return
        # Fresh factory is the only branch that may paint/reopen a QR. An
        # adopted continuation never overwrites a last photo on reboot.
        await asyncio.to_thread(self.screen.reserve)
        context = await asyncio.to_thread(prepared.bootstrap_tls_context)
        public = BootstrapPublicIdentity(prepared.frame_id, prepared.bootstrap_certificate_der)
        self.transport = GATTTransport(context, self.command, profile=BOOTSTRAP_PROFILE,
                                       peer_factory=self._peer_factory())
        self.bluez = self.server_factory(self.transport, public, profile=BOOTSTRAP_PROFILE)
        if status.state == FactoryState.FACTORY:
            epoch = await asyncio.to_thread(self._verified_epoch)
            token = await asyncio.to_thread(self.owners.open_factory_window, expected_epoch=epoch)
            payload = bootstrap_wire.encode_qr(prepared.frame_id, prepared.binding.spki_sha256, token.value)
            await asyncio.to_thread(self.screen.show_qr, payload)
            self._window_task = asyncio.create_task(self._expire_window(self.monotonic() + 600))
        await asyncio.to_thread(self._verified_epoch)
        if not self._stopping:
            await self.bluez.start()
            self.available = self._admitting = True

    def _accept_snapshot(self, snapshot):
        # inspect, status and resume deliberately have different closed shapes.
        # Only add local indexing fields; never manufacture a root observation.
        snapshot = dict(snapshot)
        if "workflow" in snapshot and snapshot["workflow"] != self.workflow:
            raise FactoryRecoveryRequired()
        snapshot.setdefault("workflow", self.workflow)
        snapshot.setdefault("operation", None if self.snapshot is None else self.snapshot["operation"])
        operation, completion = snapshot["operation"], snapshot["completion"]
        if operation is not None:
            binding = operation["binding"]
            if any(binding[key] != value for key, value in self.workflow.items()):
                raise FactoryRecoveryRequired()
        snapshot.setdefault("latest_operation_id", operation["operation_id"] if operation else
                            completion["operation_id"] if completion else None)
        snapshot.setdefault("state", "completed" if completion is not None and operation is not None
                            and completion["operation_id"] == operation["operation_id"] else
                            operation["state"] if operation else "not_started")
        self.snapshot = snapshot
        return snapshot

    def _accept_completion(self, completion, prepared, status):
        publication = prepared.initial_publication()
        if (completion["workflow"] != self.workflow or completion["owner_id"] != status.first_owner_id
                or publication is None or completion["publication"] != publication):
            raise FactoryRecoveryRequired()
        prepared.load_current_identity()  # Same UUID/key, current DER may renew.
        self._historical_completion = completion

    async def _start_normal(self, identity):
        async with self._normal_lock:
            if self.normal_service is not None:
                return
            await asyncio.to_thread(self._verify)
            self._admitting = False
            self._cancel_window_timer()
            # No active setup channel survives a transport/profile transition.
            channels = {session.channel for session in self._sessions if session.channel is not None}
            for session in tuple(self._sessions):
                session.close()
            if self.transport is not None:
                self.transport.close()
            if self.bluez is not None:
                await self.bluez.stop()
            for channel in channels:
                await channel.drain()
            await asyncio.to_thread(self.screen.release)
            self.identity = identity
            path = self.directory.parent / "credentials.json"
            credentials = auth.CredentialService(auth._parse_record(path, auth._read_record(path)), auth.SessionStore())
            self.provisioning = ProvisioningRuntime(
                self.directory, credentials, self.display, identity, owners=self.owners,
                network=self.network, peer_factory=self._peer_factory(normal=True),
                frame_status=self._frame_status, network_admission=self._network_admission,
                adoption_admission=self._adoption_admission,
                owns_store=False, server_factory=self.server_factory,
                # Renewals require a current time policy; the old completion is
                # not such an attestation. Maintenance is enabled after real setup.
                renew_certificate=False,
            )
            if self.normal_service_factory is None:
                from inky_web.main import FactoryNormalService
                factory = FactoryNormalService
            else:
                factory = self.normal_service_factory
            self.normal_service = factory(self)
            await self.normal_service.start()
            self.available = self._admitting = True

    def https_origin(self):
        if self.snapshot is None:
            return None
        live = self.snapshot["live"]
        if live["readiness"] != "network_ready" or live["origin_status"] != "avahi_current":
            return None
        return live["https_origin"]

    def _frame_status(self):
        origin = self.https_origin()
        return {"frame_id": self.identity.frame_id, "https_port": 8443,
                "hostname": None if origin is None else origin.removeprefix("https://").removesuffix(":8443")}

    async def _adoption_admission(self):
        await asyncio.to_thread(self._verify)
        if not self.historical_completed():
            raise NetworkUnavailable("not_ready")

    async def _network_admission(self, *, lan=False):
        await asyncio.to_thread(self._verify)
        try:
            snapshot = await self.system_setup.inspect(self.workflow)
        except SetupUnavailable:
            raise NetworkUnavailable("not_ready") from None
        self._accept_snapshot(snapshot)
        live = snapshot["live"]
        if live["readiness"] not in {"country_radio_ready", "network_ready"}:
            raise NetworkUnavailable("not_ready")
        if not self.historical_completed() and live["clock_status"] != "owner_asserted_current_boot":
            raise NetworkUnavailable("not_ready")
        if lan and self.https_origin() is None:
            raise NetworkUnavailable("not_ready")

    async def session_command(self, session, message, normal_handler):
        if type(message) is dict and (message.get("v") == 2 or str(message.get("op", "")).startswith("system_setup.")):
            return await self._setup_command(session, message)
        return await normal_handler(message)

    async def _setup_command(self, session, raw):
        rpc_id = wire.request_id(raw)
        try:
            message = wire.validate_request(raw)
            if not self._admitting or self._stopping:
                raise OwnershipError("service_stopping")
            operation = message["op"]
            await asyncio.to_thread(self._authorize, session, message,
                                    negotiated=operation != "system_setup.negotiate")
            if operation == "system_setup.negotiate":
                snapshot = await self.system_setup.inspect(self.workflow)
                self._accept_snapshot(snapshot)
                op = snapshot["operation"]
                latest = snapshot["latest_operation_id"]
                if snapshot["state"] == "challenged" and op is None:
                    # An in-memory challenge is scoped to its vanished channel,
                    # not a durable submitted intention discoverable by status.
                    latest = None
                if latest is not None and (op is None or op["binding"]["owner_id"] != message["owner_id"]
                        or op["binding"]["claim_request_id"] != message["claim_request_id"]):
                    raise OwnershipError("unauthorized")
                session.negotiated = True
                result = {"selected_version": 2, "latest_operation_id": latest,
                          "capabilities": list(wire.CAPABILITIES)}
            elif operation == "system_setup.challenge":
                if message["op_id"] not in self._challenges and len(self._challenges) >= 64:
                    raise OwnershipError("unavailable")
                async def issue_challenge():
                    await asyncio.to_thread(self._authorize, session, message)
                    channel = await self._channel(session, message)
                    return await channel.call("setup.challenge", operation_id=message["op_id"],
                        supersedes_operation_id=message["supersedes_op_id"])
                async with self.mutation_lock:
                    if self.provisioning is None:
                        challenge = await issue_challenge()
                    else:
                        # An already admitted normal Wi-Fi call retains its
                        # owner. Drain it before OS closes WLAN for recovery.
                        async with self.provisioning.mutation_lock:
                            challenge = await issue_challenge()
                self._challenges[message["op_id"]] = (session, challenge)
                result = {"op_id": message["op_id"], "challenge_id": challenge["challenge_id"],
                    "nonce": challenge["nonce"], "boot_id": challenge["binding"]["boot_id"],
                    "issued_boottime_ns": challenge["issued_boottime_ns"],
                    "expires_boottime_ns": challenge["expires_boottime_ns"]}
            elif operation == "system_setup.apply":
                self._register_apply(session, message)
                result = {"op_id": message["op_id"], "state": "applying", "submission": "registered",
                    "durability": "not_confirmed", "frame_id": self.workflow["frame_id"],
                    "owner_id": message["owner_id"], "claim_request_id": message["claim_request_id"],
                    "next_step": "status"}
            elif operation == "system_setup.status":
                snapshot = self._accept_snapshot(await self.system_setup.status(message["op_id"]))
                result = self._status_result(message, snapshot)
            else:
                result = await self._continue(session, message)
            await asyncio.to_thread(self._authorize, session, message,
                                    negotiated=operation != "system_setup.negotiate")
            if operation == "system_setup.continue" and result.get("action") == "publication_finalized":
                identity = self.result.prepared_identity.load_current_identity()
                # Registration follows the last delivery guard; the peer can
                # serialize its reply before the handoff task gets the loop.
                self.operations.create(self._start_normal(identity))
            return wire.response(rpc_id, result)
        except wire.WireError:
            code = "invalid_request"
        except OwnershipError as exc:
            code = exc.code
        except SetupUnavailable as exc:
            code = {"not_found": "request_not_found", "conflict": "request_conflict",
                    "uncertain": "recovery_required", "permission_denied": "unauthorized"}.get(exc.code, "unavailable")
        except (FactoryRecoveryRequired, BootstrapIdentityRecoveryRequired):
            code = "recovery_required"
        except Exception:
            code = "unavailable"
        return wire.error(rpc_id, code)

    def _register_apply(self, session, message):
        op_id = message["op_id"]
        old = self._apply_tasks.get(op_id)
        intent = {key: message[key] for key in ("op_id", "challenge_id", "nonce", "utc_seconds", "country",
                                               "owner_id", "claim_request_id")}
        if old is not None:
            if old[0] != intent:
                raise OwnershipError("request_conflict")
            return
        if len(self.operations.tasks) >= 4 or len(self._apply_tasks) >= 64:
            raise OwnershipError("unavailable")
        pair = self._challenges.get(op_id)
        if pair is None or pair[0] is not session:
            raise OwnershipError("request_not_found")
        challenge = pair[1]
        if challenge["challenge_id"] != message["challenge_id"] or challenge["nonce"] != message["nonce"]:
            raise OwnershipError("request_conflict")
        # No await between ownership registration and returning the quick ACK.
        task = self.operations.create(self._apply(session, dict(message), challenge))
        self._apply_tasks[op_id] = (intent, task)

    async def _apply(self, session, message, challenge):
        try:
            await asyncio.to_thread(self._authorize, session, message)
            channel = await self._channel(session, message)
            intent = {key: message[key] for key in ("op_id", "challenge_id", "nonce", "utc_seconds", "country",
                                                   "owner_id", "claim_request_id")}
            intent["supersedes_op_id"] = challenge["supersedes_operation_id"]
            await asyncio.to_thread(self.intents.remember, message["op_id"], intent)
            await asyncio.to_thread(self._authorize, session, message)
            operation = await channel.call("setup.apply", operation_id=message["op_id"],
                supersedes_operation_id=challenge["supersedes_operation_id"],
                challenge_id=message["challenge_id"], nonce=message["nonce"],
                utc_seconds=message["utc_seconds"], country=message["country"])
            await asyncio.to_thread(self._authorize, session, message)
            receipt = operation["receipt"]
            if operation["state"] != "effects_completed" or receipt is None:
                raise FactoryRecoveryRequired()
            if receipt["binding"] != challenge["binding"] or receipt["clock"]["utc_seconds"] != message["utc_seconds"]:
                raise FactoryRecoveryRequired()
            if receipt["binding"]["session_id"] != session.session_id:
                raise FactoryRecoveryRequired()
            prepared, _, _ = await asyncio.to_thread(self._verify)
            if prepared.initial_publication() is None:
                # Only this live apply response, not status/history, creates a
                # new candidate from the current-boot measured native result.
                clock = ClockResult(message["op_id"], message["utc_seconds"])
                def publish():
                    self._authorize(session, message)
                    return prepared.publish_initial(operation_id=message["op_id"], clock_result=clock)
                await asyncio.to_thread(publish)
            self._accept_snapshot(await self.system_setup.status(message["op_id"]))
            await self._start_normal(prepared.load_current_identity())
        finally:
            # Registry observes failures; status reads OS truth, never a local
            # completed boolean. Loss after an effect stays uncertain/recoverable.
            pass

    def _status_result(self, message, snapshot):
        operation = snapshot["operation"]
        completion = snapshot["completion"]
        if operation is not None:
            if (operation["operation_id"] != message["op_id"]
                    or operation["binding"]["owner_id"] != message["owner_id"]
                    or operation["binding"]["claim_request_id"] != message["claim_request_id"]):
                raise OwnershipError("unauthorized")
        elif completion is None or completion["operation_id"] != message["op_id"]:
            raise OwnershipError("request_not_found")
        prepared = self.result.prepared_identity
        current = prepared.verify_current_or_unpublished()
        provenance = prepared.initial_publication()
        normal = None if current is None else {
            "frame_id": prepared.frame_id, "spki_sha256": prepared.binding.spki_sha256,
            "publication_op_id": provenance["publication_operation_id"],
        }
        origin = self.https_origin()
        if completion is not None and completion["operation_id"] == message["op_id"]:
            self._accept_completion(completion, prepared, self.owners.factory_status())
            state, next_step = "complete", "photo_enroll" if origin else "wait_origin"
        elif operation and operation["state"] in {"pending", "uncertain", "superseded"}:
            state = "applying" if operation["state"] == "pending" else "uncertain"
            next_step = "status" if state == "applying" else "recover_explicit"
        elif current is not None:
            state, next_step = "wifi_pending", "wifi" if origin else "wait_origin"
        elif provenance is not None:
            state, next_step = "setup_ready", "continue"
        else:
            state, next_step = "uncertain", "recover_explicit"
        return {"op_id": message["op_id"], "state": state, "frame_id": prepared.frame_id,
            "owner_id": message["owner_id"], "claim_request_id": message["claim_request_id"],
            "normal_identity": normal, "https_origin": origin,
            "completion_id": completion["completion_id"] if state == "complete" else None, "next_step": next_step}

    async def _continue(self, session, message):
        async with self.mutation_lock:
            snapshot = self._accept_snapshot(await self.system_setup.status(message["op_id"]))
            result = self._status_result(message, snapshot)
            prepared, _ = await asyncio.to_thread(self._authorize, session, message)
            status = await asyncio.to_thread(self.owners.factory_status)
            if result["state"] == "complete":
                return {**result, "action": "already_complete"}
            if snapshot["operation"] is None or snapshot["operation"]["state"] != "effects_completed":
                raise FactoryRecoveryRequired()
            if prepared.initial_publication() is None:
                raise FactoryRecoveryRequired()
            await asyncio.to_thread(prepared.continue_initial_publication)
            await asyncio.to_thread(prepared.load_current_identity)
            network = snapshot["live"]["network"]
            if network is not None and network["state"] == "committed" and self.https_origin() is not None:
                channel = await self._channel(session, message)
                completion = await channel.call("setup.complete", operation_id=message["op_id"],
                    publication=prepared.initial_publication(), network_transaction_id=network["id"])
                self._accept_completion(completion, prepared, status)
                snapshot = self._accept_snapshot(await self.system_setup.status(message["op_id"]))
                result = self._status_result(message, snapshot)
                return {**result, "action": "completion_finalized"}
            action = "publication_finalized" if self.normal_service is None else "wifi_pending"
            result = self._status_result(message, snapshot)
            result["state"] = "tls_ready" if action == "publication_finalized" else "wifi_pending"
            result["next_step"] = "wifi" if result["https_origin"] else "wait_origin"
            return {**result, "action": action}

    async def authorize_photo(self, owner_id, owner_token, claim_request_id, setup_op_id):
        # The HTTP route holds CredentialService's rotation lock for the actual
        # PHOTO transaction and rechecks this authorization before enrollment.
        await self._network_admission(lan=True)
        prepared, status, _ = await asyncio.to_thread(self._verify)
        self.owners.status(owner_id, owner_token, request_id=claim_request_id)
        completion = self.snapshot["completion"]
        if (completion is None or self.snapshot["latest_operation_id"] != completion["operation_id"]
                or completion["operation_id"] != setup_op_id
                or completion["owner_id"] != owner_id or completion["claim_request_id"] != claim_request_id
                or status.first_owner_id != owner_id):
            raise OwnershipError("unauthorized")
        self._accept_completion(completion, prepared, status)
        return completion

    async def _stop(self):
        for session in tuple(self._sessions):
            session.close()
        try:
            await self.operations.drain()
            for session in tuple(self._sessions):
                if session.channel is not None:
                    await session.channel.drain()
            if self.normal_service is not None:
                await self.normal_service.stop()
            elif self.bluez is not None:
                await self.bluez.stop()
        finally:
            await asyncio.to_thread(self.screen.release)
            # The outer phase A lifetime closes the single transferred store.
