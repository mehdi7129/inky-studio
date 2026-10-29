"""Inactive observation: real files, sockets and flock; synthetic OS admission.

The existing IPC suite qualifies transport schemas/deadlines separately. These
tests compose it with Studio guards; injected root metadata/peer identities do
not qualify an installed Linux graph, root service, radio or physical frame.
"""
from __future__ import annotations

import asyncio
import copy
import fcntl
import json
import os
import subprocess
import sys
import threading
from contextlib import contextmanager
from contextvars import copy_context
from dataclasses import FrozenInstanceError, asdict, fields
from types import SimpleNamespace
from uuid import uuid4

import pytest

from inky_web import auth
from inky_web.provisioning import factory_environment as environment
from inky_web.provisioning import factory_observation as observation
from inky_web.provisioning import factory_runtime, first_boot
from inky_web.provisioning import factory_writer as writer
from inky_web.provisioning import initialization_ipc as ipc

from .test_initialization_ipc import encode, success
from .test_initialization_ipc import root_peer as root_peer
from .test_initialization_ipc import serve as serve


@pytest.fixture(autouse=True)
def inky_env(tmp_path, monkeypatch):
    # Override conftest's eager legacy DB creation.
    data = tmp_path / "state"
    monkeypatch.setenv("INKY_STUDIO_DATA_DIR", str(data))
    monkeypatch.delenv("INKY_STUDIO_FACTORY_REQUIRED", raising=False)
    monkeypatch.delenv("INKY_STUDIO_DISABLE_AUTH", raising=False)
    for name in tuple(os.environ):
        if name.startswith("INKYOS_WRITER_"):
            monkeypatch.delenv(name)
    monkeypatch.setattr(environment, "FACTORY_SIGNAL_PATHS", (tmp_path / "absent",))
    return data


@pytest.fixture(scope="module")
def credentials_record():
    from pathlib import Path

    return auth._new_credentials(Path("/synthetic"), "synthetic-observation-password",
                                 bootstrap=True).record()


@pytest.fixture
def configured(inky_env, tmp_path, monkeypatch, credentials_record):
    marker = tmp_path / "etc" / "factory-v1.json"
    marker.parent.mkdir()
    marker.write_text(json.dumps({"version": 1, "app_uid": os.geteuid(),
                                  "data_dir": str(inky_env)}))
    marker.chmod(0o644)
    inky_env.mkdir(mode=0o700)
    credential_path = inky_env / "credentials.json"
    credential_path.write_text(json.dumps(credentials_record))
    credential_path.chmod(0o600)
    monkeypatch.setenv("INKY_STUDIO_FACTORY_REQUIRED", "1")
    monkeypatch.setattr(factory_runtime, "MARKER_PATH", marker)
    monkeypatch.setattr(factory_runtime, "EXPECTED_DATA_DIR", inky_env)
    monkeypatch.setattr(factory_runtime, "EXPECTED_APP_UID", os.geteuid())
    monkeypatch.setattr(factory_runtime, "_root_directory", lambda _info: None)
    read_file = factory_runtime._read_file

    def read_owned(directory, name, limit, **policy):
        if name == marker.name:
            policy = policy | {"uid": os.geteuid(), "gid": os.getegid()}
        return read_file(directory, name, limit, **policy)

    monkeypatch.setattr(factory_runtime, "_read_file", read_owned)

    def forbidden(*_args, **_kwargs):
        pytest.fail("Observation invoked an initialization or credential mutation")

    monkeypatch.setattr(first_boot.FirstBootCoordinator, "initialize", forbidden)
    monkeypatch.setattr(factory_runtime, "prepare_factory", forbidden)
    monkeypatch.setattr(factory_runtime, "initialize_factory", forbidden)
    monkeypatch.setattr(auth, "load_or_create_credentials", forbidden)
    monkeypatch.setattr(auth, "reset_credentials", forbidden)
    monkeypatch.setattr(ipc.InitializationIPCClient, "begin_initialization", forbidden)
    return SimpleNamespace(data=inky_env, marker=marker, credentials=credential_path,
                           root=tmp_path)


@pytest.fixture
def admission(tmp_path, monkeypatch):
    path = tmp_path / "writer.lock"
    path.touch()
    acquisitions, releases = [], []

    def available():
        with path.open("rb") as descriptor:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            return True

    def child_available():
        probe = subprocess.run([sys.executable, "-I", "-c", """
import fcntl
import sys
with open(sys.argv[1], "rb") as descriptor:
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit(1)
""", str(path)], capture_output=True, text=True)
        assert probe.returncode in {0, 1}, probe.stderr
        return probe.returncode == 0

    @contextmanager
    def admitted(role):
        assert role == "main"
        with path.open("rb") as descriptor:
            fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)

            def check():
                if descriptor.closed:
                    raise ValueError("private-closed-lease")
                os.fstat(descriptor.fileno())

            lease = SimpleNamespace(check=check, fileno=descriptor.fileno, close=descriptor.close)
            acquisitions.append(lease)
            try:
                yield lease
            finally:
                releases.append(lease)

    monkeypatch.setattr(writer, "_installed_runtime", lambda: SimpleNamespace(writer_guard=admitted))
    return SimpleNamespace(available=available, child_available=child_available,
                           acquisitions=acquisitions, releases=releases)


def snapshot(directory):
    return {str(path.relative_to(directory)): path.read_bytes()
            for path in directory.rglob("*") if path.is_file() and not path.is_symlink()}


def connect_observer(monkeypatch, server):
    constructions = []

    def client(*args, **kwargs):
        assert not args and not kwargs, "Production observation must use the fixed default socket"
        constructions.append(True)
        return ipc.InitializationIPCClient(server.path)

    monkeypatch.setattr(observation, "InitializationIPCClient", client)
    return constructions


def forbid_ipc(monkeypatch):
    attempts = []

    def forbidden():
        attempts.append(True)
        pytest.fail("Rejected observation reached IPC")

    monkeypatch.setattr(observation, "InitializationIPCClient", forbidden)
    return attempts


@pytest.mark.parametrize("state", ["authorized", "consumed"])
async def test_observation_returns_only_current_state_without_mutations(
    state, configured, admission, serve, root_peer, monkeypatch,
):
    result = {"status": state}
    if state == "consumed":
        result |= {"intent": str(uuid4()), "receipt": {"receipt_id": str(uuid4()), "digest": "a" * 64}}

    def handler(connection, request):
        assert not admission.available()
        assert request["op"] == "initialization.inspect"
        connection.sendall(encode(success(request, result)))

    server = serve(handler)
    constructions = connect_observer(monkeypatch, server)
    before = snapshot(configured.root)
    observed = await observation.observe_initialization_service(configured.data)
    assert asdict(observed) == {"receipt_state": state}
    assert [field.name for field in fields(observed)] == ["receipt_state"]
    with pytest.raises(FrozenInstanceError):
        observed.receipt_state = "authorized"
    assert snapshot(configured.root) == before
    assert len(constructions) == len(root_peer) == len(server.requests) == 1
    assert len(admission.acquisitions) == len(admission.releases) == 2
    assert admission.available()


async def test_legacy_guard_is_not_initialization_admission(inky_env, monkeypatch):
    attempts = forbid_ipc(monkeypatch)
    monkeypatch.setattr(writer, "_installed_runtime", lambda: pytest.fail("Legacy imported OS"))
    monkeypatch.setattr(observation, "select_runtime", lambda _path: pytest.fail("No guard reached selector"))
    with pytest.raises(factory_runtime.FactoryRuntimeError, match="^factory_runtime_refused$"):
        await observation.observe_initialization_service(inky_env)
    assert not attempts and not inky_env.exists()


async def test_guard_refusal_is_fixed_before_selector_or_ipc(configured, monkeypatch):
    attempts = forbid_ipc(monkeypatch)
    monkeypatch.setattr(writer, "_installed_runtime",
                        lambda: (_ for _ in ()).throw(ValueError("private-admission-secret")))
    monkeypatch.setattr(observation, "select_runtime", lambda _path: pytest.fail("Rejected guard selected"))
    with pytest.raises(factory_runtime.FactoryRuntimeError) as caught:
        await observation.observe_initialization_service(configured.data)
    assert str(caught.value) == "factory_runtime_refused" and not attempts


async def test_independent_guard_must_admit_before_ipc(configured, admission, monkeypatch):
    attempts = forbid_ipc(monkeypatch)
    installed_runtime = writer._installed_runtime
    loads = []

    def load():
        loads.append(True)
        if len(loads) == 2:
            raise ValueError("private-independent-admission-secret")
        return installed_runtime()

    monkeypatch.setattr(writer, "_installed_runtime", load)
    with pytest.raises(factory_runtime.FactoryRuntimeError, match="^factory_runtime_refused$"):
        await observation.observe_initialization_service(configured.data)
    assert not attempts and len(loads) == 2
    assert len(admission.acquisitions) == len(admission.releases) == 1
    assert admission.available()


async def test_closed_inherited_context_refuses_before_ipc(configured, admission, monkeypatch):
    attempts = forbid_ipc(monkeypatch)
    with writer.main_writer_guard():
        context = copy_context()
    task = asyncio.create_task(observation.observe_initialization_service(configured.data), context=context)
    with pytest.raises(factory_runtime.FactoryRuntimeError, match="^factory_runtime_refused$"):
        await task
    assert not attempts and admission.available()
    assert len(admission.acquisitions) == 1


@pytest.mark.parametrize("name,value", [("INKYOS_WRITER_UNKNOWN", ""),
                                        ("INKYOS_WRITER_ROLE", "helper"),
                                        ("INKY_STUDIO_FACTORY_REQUIRED", "")])
async def test_changed_inherited_environment_refuses_before_ipc(
    configured, admission, monkeypatch, name, value,
):
    attempts = forbid_ipc(monkeypatch)
    with writer.main_writer_guard():
        monkeypatch.setenv(name, value)
        with pytest.raises(factory_runtime.FactoryRuntimeError, match="^factory_runtime_refused$"):
            await observation.observe_initialization_service(configured.data)
    assert not attempts and admission.available()


async def test_environment_changed_during_prerequisites_refuses_before_ipc(
    configured, admission, monkeypatch,
):
    attempts = forbid_ipc(monkeypatch)
    select_runtime = observation.select_runtime

    def select(directory):
        config = select_runtime(directory)
        monkeypatch.setenv("INKYOS_WRITER_UNKNOWN", "")
        return config

    monkeypatch.setattr(observation, "select_runtime", select)
    with pytest.raises(factory_runtime.FactoryRuntimeError, match="^factory_runtime_refused$"):
        await observation.observe_initialization_service(configured.data)
    assert not attempts and admission.available()


async def test_selector_cannot_choose_legacy_under_admission(configured, admission, monkeypatch):
    attempts = forbid_ipc(monkeypatch)
    monkeypatch.setattr(observation, "select_runtime", lambda _directory: None)
    with pytest.raises(factory_runtime.FactoryRuntimeError, match="^factory_runtime_refused$"):
        await observation.observe_initialization_service(configured.data)
    assert not attempts and admission.available()


@pytest.mark.parametrize("failure", ["selector", "credentials", "credential_mode"])
async def test_invalid_local_prerequisites_refuse_before_ipc(
    configured, admission, monkeypatch, failure,
):
    attempts = forbid_ipc(monkeypatch)
    if failure == "selector":
        configured.marker.write_text("{}")
    elif failure == "credentials":
        configured.credentials.write_text("private-invalid-credential")
    else:
        configured.credentials.chmod(0o644)
    before = snapshot(configured.root)
    with pytest.raises(factory_runtime.FactoryRuntimeError, match="^factory_runtime_refused$"):
        await observation.observe_initialization_service(configured.data)
    assert not attempts and snapshot(configured.root) == before and admission.available()


@pytest.mark.parametrize("failure", ["environment", "selector", "credentials", "epoch", "lease"])
async def test_post_inspect_revalidation_refuses_stale_result(
    configured, admission, serve, root_peer, monkeypatch, credentials_record, failure,
):
    def handler(connection, request):
        if failure == "environment":
            monkeypatch.setenv("INKYOS_WRITER_UNKNOWN", "")
        elif failure == "selector":
            configured.marker.write_text("{}")
        elif failure == "credentials":
            configured.credentials.write_text("private-invalid-after-inspect")
        elif failure == "epoch":
            changed = copy.deepcopy(credentials_record)
            changed.pop("bootstrap_password")
            changed["salt"] = "b" * 32
            configured.credentials.write_text(json.dumps(changed))
        else:
            admission.acquisitions[-1].close()
        connection.sendall(encode(success(request)))

    server = serve(handler)
    constructions = connect_observer(monkeypatch, server)
    with pytest.raises(factory_runtime.FactoryRuntimeError, match="^factory_runtime_refused$"):
        await observation.observe_initialization_service(configured.data)
    assert len(constructions) == len(server.requests) == 1
    assert admission.available()


@pytest.mark.parametrize("failure", ["absent", "unavailable", "forbidden", "malformed", "exception"])
async def test_ipc_failure_is_sanitized_without_retry_or_begin(
    configured, admission, serve, root_peer, monkeypatch, caplog, failure,
):
    calls = []
    if failure == "absent":
        def client():
            calls.append(True)
            return ipc.InitializationIPCClient(str(configured.root / "absent.sock"))
        monkeypatch.setattr(observation, "InitializationIPCClient", client)
    elif failure == "exception":
        def inspect():
            calls.append(True)
            raise RuntimeError("private-inspection-secret")
        monkeypatch.setattr(observation, "InitializationIPCClient",
                            lambda: SimpleNamespace(inspect_initialization=inspect))
    else:
        def handler(connection, request):
            calls.append(True)
            reply = (success(request, {"status": "private-unknown-state"}) if failure == "malformed"
                     else {"v": 1, "id": request["id"], "ok": False, "error": failure})
            connection.sendall(encode(reply))
        server = serve(handler)
        connect_observer(monkeypatch, server)
    before = snapshot(configured.root)
    with pytest.raises(factory_runtime.FactoryRuntimeError) as caught:
        await observation.observe_initialization_service(configured.data)
    assert str(caught.value) == "factory_runtime_refused"
    assert caught.value.exit_status == 78 and caught.value.__suppress_context__
    assert "private" not in caplog.text and len(calls) == 1
    assert snapshot(configured.root) == before and admission.available()


@pytest.mark.parametrize("nested,cancel,failed", [
    (False, True, False), (True, True, False), (True, False, False), (True, True, True),
])
async def test_owned_shared_lease_outlives_external_guard_and_cancellation_until_socket_closes(
    configured, admission, serve, root_peer, monkeypatch, nested, cancel, failed,
):
    loop = asyncio.get_running_loop()
    previous_exception_handler = loop.get_exception_handler()
    unobserved_exceptions = []
    pending_before = asyncio.all_tasks()
    loop.set_exception_handler(lambda _loop, context: unobserved_exceptions.append(context))
    started = asyncio.Event()
    release = threading.Event()
    finished = threading.Event()
    connections = []
    verify_peer = ipc._verify_server_peer

    def tracked_peer(connection):
        verify_peer(connection)
        connections.append(connection)

    monkeypatch.setattr(ipc, "_verify_server_peer", tracked_peer)

    def handler(connection, request):
        # A complete line alone is insufficient: hold EOF until released, even
        # when the eventual worker result is a transport refusal.
        reply = ({"v": 1, "id": request["id"], "ok": False, "error": "unavailable"}
                 if failed else success(request))
        connection.sendall(encode(reply))
        loop.call_soon_threadsafe(started.set)
        assert release.wait(5), "Test did not release its IPC peer"

    server = serve(handler)
    connect_observer(monkeypatch, server)
    inspect = observation._inspect

    def tracked_inspect(directory):
        try:
            return inspect(directory)
        finally:
            assert connections and connections[0].fileno() == -1
            finished.set()

    monkeypatch.setattr(observation, "_inspect", tracked_inspect)
    task = None
    try:
        if nested:
            with writer.main_writer_guard():
                task = asyncio.create_task(observation.observe_initialization_service(configured.data))
                await asyncio.wait_for(started.wait(), 2)
                assert len(admission.acquisitions) == 2
            assert len(admission.releases) == 1
        else:
            task = asyncio.create_task(observation.observe_initialization_service(configured.data))
            await asyncio.wait_for(started.wait(), 2)
        assert not admission.child_available()
        for _ in range(3):
            if cancel:
                task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and not finished.is_set()
            assert not admission.child_available()
    finally:
        release.set()
        try:
            if task is not None:
                if cancel:
                    with pytest.raises(asyncio.CancelledError):
                        await asyncio.wait_for(task, 2)
                else:
                    assert (await asyncio.wait_for(task, 2)).receipt_state == "authorized"
            await asyncio.sleep(0)
        finally:
            loop.set_exception_handler(previous_exception_handler)
    assert finished.is_set() and connections[0].fileno() == -1
    assert len(server.requests) == len(root_peer) == 1
    assert len(admission.acquisitions) == len(admission.releases) == 2
    assert admission.child_available()
    assert not (asyncio.all_tasks() - pending_before)
    assert not unobserved_exceptions
