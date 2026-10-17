"""Real local sockets and files; synthetic root identity/receipt, no OS mutation."""
from __future__ import annotations

import copy
import json
import socket
import struct
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from inky_web.provisioning import initialization_ipc as ipc
from inky_web.provisioning.bootstrap_identity import (
    PREPARED_IDENTITY_FILENAME,
    PreparedFactoryIdentity,
)
from inky_web.provisioning.factory import FactoryState
from inky_web.provisioning.first_boot import (
    FirstBootCoordinator,
    FirstBootRefused,
    FirstBootUncertain,
)

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "shared/initialization-ipc-v1.json").read_text())
INTENT = VECTORS["success"][2]["request"]["intent"]
RECEIPT = VECTORS["success"][2]["response"]["result"]["receipt"]


def encode(value):
    return json.dumps(value, separators=(",", ":")).encode() + b"\n"


def success(request, result=None):
    if result is None:
        result = ({"status": "authorized"} if request["op"] == "initialization.inspect" else
                  {"status": "newly_consumed", "intent": request["intent"], "receipt": RECEIPT})
    return {"v": 1, "id": request["id"], "ok": True, "result": result}


@pytest.fixture
def root_peer(monkeypatch):
    # Deliberate portable test double; this does not qualify Linux credentials.
    calls = []
    monkeypatch.setattr(ipc, "_verify_server_peer", lambda connection: calls.append(connection.fileno()))
    return calls


@pytest.fixture
def serve():
    servers = []

    def create(handler):
        # Short paths also work under macOS's smaller sockaddr_un limit.
        directory = tempfile.TemporaryDirectory(prefix="inky-ipc-", dir="/tmp")
        path = str(Path(directory.name) / "control.sock")
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(path)
        listener.listen()
        listener.settimeout(0.05)
        stop = threading.Event()
        requests, raw_requests, errors = [], [], []
        active = set()
        active_lock = threading.Lock()

        def run():
            while not stop.is_set():
                try:
                    connection, _ = listener.accept()
                except TimeoutError:
                    continue
                except OSError:
                    return
                with active_lock:
                    if stop.is_set():
                        connection.close()
                        return
                    active.add(connection)
                try:
                    with connection:
                        # A valid OS proof can occupy up to ten seconds before
                        # the client sends its single request.
                        connection.settimeout(16)
                        raw = bytearray()
                        while not raw.endswith(b"\n") and len(raw) <= ipc.MAX_REQUEST_BYTES:
                            chunk = connection.recv(1025)
                            if not chunk:
                                break
                            raw.extend(chunk)
                        raw_requests.append(bytes(raw))
                        if raw:
                            request = json.loads(raw)
                            requests.append(request)
                            handler(connection, request)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # Client may reject or hit its total deadline first.
                except BaseException as exc:
                    if not stop.is_set():
                        errors.append(exc)
                finally:
                    with active_lock:
                        active.discard(connection)

        thread = threading.Thread(target=run)
        thread.start()
        server = SimpleNamespace(path=path, requests=requests, raw_requests=raw_requests,
                                 errors=errors, thread=thread, stop=stop,
                                 listener=listener, directory=directory,
                                 active=active, active_lock=active_lock)
        servers.append(server)
        return server

    yield create
    for server in servers:
        server.stop.set()
        server.listener.close()
        with server.active_lock:
            for connection in server.active:
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                connection.close()
        server.thread.join(4)
        server.directory.cleanup()
        assert not server.thread.is_alive()
        assert not server.errors


@pytest.mark.parametrize("vector", VECTORS["success"], ids=lambda item: item["name"])
def test_shared_success_vectors_roundtrip_once(serve, root_peer, vector):
    def respond(connection, request):
        assert request | {"id": vector["request"]["id"]} == vector["request"]
        connection.sendall(encode(vector["response"] | {"id": request["id"]}))

    server = serve(respond)
    client = ipc.InitializationIPCClient(server.path)
    result = (client.begin_initialization(INTENT) if vector["request"]["op"].endswith("begin")
              else client.inspect_initialization())
    assert result == vector["response"]["result"]
    assert len(server.requests) == len(root_peer) == 1
    assert str(UUID(server.requests[0]["id"])) == server.requests[0]["id"]
    assert len(server.raw_requests[0]) <= VECTORS["request_limit_including_lf"]
    assert server.raw_requests[0].count(b"\n") == 1


def test_every_operation_uses_a_new_connection_and_request_id(serve, root_peer):
    server = serve(lambda connection, request: connection.sendall(encode(success(request))))
    client = ipc.InitializationIPCClient(server.path)
    client.inspect_initialization()
    client.inspect_initialization()
    assert len(server.requests) == len(root_peer) == 2
    assert server.requests[0]["id"] != server.requests[1]["id"]


def test_default_deadline_matches_shared_fifteen_second_budget():
    assert VECTORS["deadline_seconds"] == ipc.DEADLINE_SECONDS == 15


def test_valid_delayed_peer_guard_retains_budget_for_one_request(serve, root_peer):
    """Real AF_UNIX exchange, portable proof double; no Linux UID qualification."""
    events = []

    @contextmanager
    def guard(connection):
        assert root_peer == [connection.fileno()]
        time.sleep(4)
        events.append("verified")
        try:
            yield
        finally:
            assert connection.fileno() == -1
            events.append("released")

    server = serve(lambda connection, request: connection.sendall(encode(success(request))))
    started = time.monotonic()
    assert ipc.InitializationIPCClient(server.path, peer_guard=guard).inspect_initialization() == {"status": "authorized"}
    assert 4 <= time.monotonic() - started < 6
    assert len(server.requests) == len(root_peer) == 1
    assert events == ["verified", "released"]


@pytest.mark.parametrize("begin", [False, True])
def test_peer_guard_exhausting_budget_sends_no_request(serve, root_peer, monkeypatch, begin):
    monkeypatch.setattr(ipc, "DEADLINE_SECONDS", 0.1)
    events = []

    @contextmanager
    def guard(connection):
        time.sleep(0.2)
        events.append("verified")
        try:
            yield
        finally:
            assert connection.fileno() == -1
            events.append("released")

    server = serve(lambda *_: pytest.fail("An exhausted proof must precede request submission"))
    client = ipc.InitializationIPCClient(server.path, peer_guard=guard)
    with pytest.raises(ipc.InitializationIPCError) as caught:
        client.begin_initialization(INTENT) if begin else client.inspect_initialization()
    assert caught.value.code == "unavailable"
    assert not caught.value.begin_submitted and not caught.value.uncertain
    assert events == ["verified", "released"]
    assert len(root_peer) == 1 and not server.requests


@pytest.mark.parametrize("begin", [False, True])
def test_peer_guard_and_response_share_one_absolute_budget(serve, root_peer, monkeypatch, begin):
    monkeypatch.setattr(ipc, "DEADLINE_SECONDS", 0.3)

    @contextmanager
    def guard(_connection):
        time.sleep(0.2)
        yield

    def respond(connection, request):
        time.sleep(0.2)
        connection.sendall(encode(success(request)))

    server = serve(respond)
    client = ipc.InitializationIPCClient(server.path, peer_guard=guard)
    with pytest.raises(ipc.InitializationIPCError) as caught:
        client.begin_initialization(INTENT) if begin else client.inspect_initialization()
    # Resetting the deadline after proof would incorrectly accept this response.
    assert caught.value.code == ("initialization_uncertain" if begin else "unavailable")
    assert caught.value.begin_submitted is begin and caught.value.uncertain is begin
    assert len(server.requests) == len(root_peer) == 1


@pytest.mark.parametrize("error", VECTORS["errors"], ids=lambda item: item["error"])
@pytest.mark.parametrize("begin", [False, True])
def test_shared_error_vectors_are_fixed_and_never_retried(serve, root_peer, error, begin):
    server = serve(lambda connection, request: connection.sendall(encode(error | {"id": request["id"]})))
    client = ipc.InitializationIPCClient(server.path)
    with pytest.raises(ipc.InitializationIPCError) as caught:
        client.begin_initialization(INTENT) if begin else client.inspect_initialization()
    assert caught.value.code == str(caught.value) == error["error"]
    assert caught.value.begin_submitted is begin
    assert caught.value.uncertain is (begin and error["error"] in {"unavailable", "initialization_uncertain"})
    assert len(server.requests) == 1


def invalid_response(request, failure):
    value = success(request)
    if failure == "wrong_id":
        value["id"] = str(uuid4())
    elif failure == "null_id":
        value["id"] = None
    elif failure == "boolean_version":
        value["v"] = True
    elif failure == "float_version":
        value["v"] = 1.0
    elif failure == "numeric_ok":
        value["ok"] = 1
    elif failure == "extra_field":
        value["secret"] = "synthetic-secret"
    elif failure == "extra_result_field":
        value["result"]["secret"] = "synthetic-secret"
    elif failure == "wrong_status":
        value["result"]["status"] = "newly_consumed" if request["op"].endswith("inspect") else "authorized"
    elif failure == "unknown_error":
        value = {"v": 1, "id": request["id"], "ok": False, "error": "synthetic-secret"}
    elif failure == "duplicate":
        return encode(value).replace(b'"v":1', b'"v":1,"v":1')
    elif failure == "nonfinite":
        return encode(value).replace(b'"v":1', b'"v":NaN')
    elif failure == "overflow_float":
        return encode(value).replace(b'"v":1', b'"v":1e999')
    elif failure == "no_newline":
        return encode(value)[:-1]
    elif failure == "extra_newline":
        return encode(value) + b"\n"
    elif failure == "trailing_bytes":
        return encode(value) + b"synthetic-secret"
    elif failure == "utf8":
        return b"\xff\n"
    elif failure == "malformed":
        return b'{"synthetic-secret":\n'
    elif failure == "eof":
        return b""
    elif failure == "deep_json":
        return b"[" * 900 + b"0" + b"]" * 900 + b"\n"
    return encode(value)


@pytest.mark.parametrize("failure", ["wrong_id", "null_id", "boolean_version", "float_version",
                                      "numeric_ok", "extra_field", "extra_result_field", "wrong_status",
                                      "unknown_error", "duplicate", "nonfinite", "overflow_float",
                                      "no_newline", "extra_newline", "trailing_bytes", "utf8",
                                      "malformed", "eof", "deep_json"])
@pytest.mark.parametrize("begin", [False, True])
def test_invalid_responses_never_grant_authority(serve, root_peer, failure, begin):
    server = serve(lambda connection, request: connection.sendall(invalid_response(request, failure)))
    client = ipc.InitializationIPCClient(server.path)
    with pytest.raises(ipc.InitializationIPCError) as caught:
        client.begin_initialization(INTENT) if begin else client.inspect_initialization()
    assert caught.value.code == ("initialization_uncertain" if begin else "unavailable")
    assert caught.value.begin_submitted is begin and caught.value.uncertain is begin
    assert "synthetic-secret" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert len(server.requests) == 1


@pytest.mark.parametrize("mutation", ["intent", "receipt_id", "digest", "receipt_extra"])
def test_begin_receipt_and_intent_are_exact(serve, root_peer, mutation):
    def respond(connection, request):
        value = copy.deepcopy(success(request))
        if mutation == "intent":
            value["result"]["intent"] = str(uuid4())
        elif mutation == "receipt_extra":
            value["result"]["receipt"]["path"] = "/synthetic-secret"
        else:
            value["result"]["receipt"][mutation] = "INVALID"
        connection.sendall(encode(value))

    server = serve(respond)
    with pytest.raises(ipc.InitializationIPCError) as caught:
        ipc.InitializationIPCClient(server.path).begin_initialization(INTENT)
    assert caught.value.uncertain
    assert str(caught.value) == "initialization_uncertain"


@pytest.mark.parametrize("extra", [0, 1])
def test_response_limit_includes_its_newline(serve, root_peer, extra):
    def respond(connection, request):
        raw = encode(success(request))[:-1]
        connection.sendall(raw + b" " * (2047 + extra - len(raw)) + b"\n")

    server = serve(respond)
    client = ipc.InitializationIPCClient(server.path)
    if extra:
        with pytest.raises(ipc.InitializationIPCError):
            client.inspect_initialization()
    else:
        assert client.inspect_initialization() == {"status": "authorized"}


def test_root_identity_is_required_before_sending_bytes(serve, monkeypatch):
    server = serve(lambda *_: pytest.fail("Untrusted peer must receive no request"))

    def deny(_connection):
        raise ipc.InitializationIPCError("forbidden")

    monkeypatch.setattr(ipc, "_verify_server_peer", deny)
    with pytest.raises(ipc.InitializationIPCError) as caught:
        ipc.InitializationIPCClient(server.path).begin_initialization(INTENT)
    assert str(caught.value) == "forbidden"
    assert not caught.value.begin_submitted and not caught.value.uncertain
    assert not server.requests


@pytest.mark.parametrize("uid", [0, 1000, 1001])
def test_linux_peer_check_uses_kernel_uid(monkeypatch, uid):
    monkeypatch.setattr(ipc, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(socket, "SO_PEERCRED", 17, raising=False)
    queries = []

    def credentials(*arguments):
        queries.append(arguments)
        return struct.pack("3i", 123, uid, 456)

    peer = SimpleNamespace(getsockopt=credentials)
    if uid == 0:
        ipc._verify_server_peer(peer)
    else:
        with pytest.raises(ipc.InitializationIPCError, match="^forbidden$"):
            ipc._verify_server_peer(peer)
    assert queries == [(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))]


def test_non_linux_refuses_without_a_fallback(monkeypatch):
    monkeypatch.setattr(ipc, "sys", SimpleNamespace(platform="darwin"))
    peer = SimpleNamespace(getsockopt=lambda *_: pytest.fail("No unqualified alternative"))
    with pytest.raises(ipc.InitializationIPCError, match="^forbidden$"):
        ipc._verify_server_peer(peer)


@pytest.mark.parametrize("intent", [None, True, 1, "", "ABCDEFAB-CDEF-4ABC-8DEF-ABCDEFABCDEF", "0" * 5000])
def test_invalid_intent_is_refused_before_connecting(tmp_path, intent):
    with pytest.raises(ipc.InitializationIPCError) as caught:
        ipc.InitializationIPCClient(str(tmp_path / "absent.sock")).begin_initialization(intent)
    assert str(caught.value) == "invalid_request"
    assert not caught.value.begin_submitted and not caught.value.uncertain


def test_missing_service_does_not_submit_begin(tmp_path):
    with pytest.raises(ipc.InitializationIPCError) as caught:
        ipc.InitializationIPCClient(str(tmp_path / "absent.sock")).begin_initialization(INTENT)
    assert str(caught.value) == "unavailable"
    assert not caught.value.begin_submitted and not caught.value.uncertain


def test_dribbling_bytes_cannot_extend_the_total_deadline(serve, root_peer, monkeypatch):
    monkeypatch.setattr(ipc, "DEADLINE_SECONDS", 0.3)
    def dribble(connection, _request):
        for _ in range(100):
            connection.sendall(b" ")
            time.sleep(0.05)

    server = serve(dribble)
    started = time.monotonic()
    with pytest.raises(ipc.InitializationIPCError) as caught:
        ipc.InitializationIPCClient(server.path).begin_initialization(INTENT)
    elapsed = time.monotonic() - started
    assert 0.25 <= elapsed < 1
    assert caught.value.uncertain and caught.value.begin_submitted
    assert len(server.requests) == 1


def test_response_is_not_accepted_until_eof_and_rejects_late_bytes(serve, root_peer):
    def respond(connection, request):
        connection.sendall(encode(success(request)))
        time.sleep(0.03)
        connection.sendall(b" ")

    server = serve(respond)
    with pytest.raises(ipc.InitializationIPCError):
        ipc.InitializationIPCClient(server.path).inspect_initialization()


def test_complete_response_without_eof_still_expires(serve, root_peer, monkeypatch):
    monkeypatch.setattr(ipc, "DEADLINE_SECONDS", 0.3)
    def respond(connection, request):
        connection.sendall(encode(success(request)))
        time.sleep(0.5)

    server = serve(respond)
    started = time.monotonic()
    with pytest.raises(ipc.InitializationIPCError) as caught:
        ipc.InitializationIPCClient(server.path).begin_initialization(INTENT)
    assert 0.25 <= time.monotonic() - started < 1
    assert caught.value.uncertain and caught.value.begin_submitted
    assert len(server.requests) == 1


def test_real_coordinator_reopens_same_binding_through_socket(serve, root_peer, tmp_path):
    state = {"status": "authorized"}

    def respond(connection, request):
        if request["op"] == "initialization.inspect":
            result = dict(state)
        else:
            first = state["status"] == "authorized"
            if first:
                state.update(status="consumed", intent=request["intent"], receipt=RECEIPT)
            assert state["intent"] == request["intent"]
            result = state | {"status": "newly_consumed" if first else "already_consumed"}
        connection.sendall(encode(success(request, result)))

    server = serve(respond)
    client = ipc.InitializationIPCClient(server.path)
    coordinator = FirstBootCoordinator(tmp_path / "private", client, lambda: "e" * 64)
    first = coordinator.initialize()
    first.ownership.close()
    second = coordinator.initialize()
    try:
        assert second.status.state == FactoryState.FACTORY
        assert second.status.identity == first.status.identity
        assert [request["intent"] for request in server.requests if request["op"].endswith("begin")] == [state["intent"]] * 2
    finally:
        second.ownership.close()


def test_lost_begin_response_cannot_recreate_missing_ledger(serve, root_peer, tmp_path):
    state = {"status": "authorized"}

    def respond(connection, request):
        if request["op"] == "initialization.inspect":
            connection.sendall(encode(success(request, dict(state))))
        elif state["status"] == "authorized":
            state.update(status="consumed", intent=request["intent"], receipt=RECEIPT)
            # Consumption happened, then the connection died without a reply.
        else:
            assert request["intent"] == state["intent"]
            connection.sendall(encode(success(request, state | {"status": "already_consumed"})))

    server = serve(respond)
    directory = tmp_path / "private"
    coordinator = FirstBootCoordinator(directory, ipc.InitializationIPCClient(server.path), lambda: "e" * 64)
    with pytest.raises(FirstBootUncertain):
        coordinator.initialize()
    prepared = PreparedFactoryIdentity.reopen(directory)
    before = (directory / PREPARED_IDENTITY_FILENAME).read_bytes()
    assert prepared.initialization_intent == state["intent"]
    with pytest.raises(FirstBootUncertain):
        coordinator.initialize()
    assert (directory / PREPARED_IDENTITY_FILENAME).read_bytes() == before
    assert not (directory / "ownership.sqlite3").exists()
    assert [request["intent"] for request in server.requests if request["op"].endswith("begin")] == [state["intent"]] * 2


def test_coordinator_failed_inspection_preserves_unconsumed_local_state(serve, root_peer, tmp_path):
    server = serve(lambda connection, request: connection.sendall(b"{}\n"))
    directory = tmp_path / "private"
    coordinator = FirstBootCoordinator(directory, ipc.InitializationIPCClient(server.path), lambda: "e" * 64)
    with pytest.raises(FirstBootRefused):
        coordinator.initialize()
    assert not (directory / PREPARED_IDENTITY_FILENAME).exists()
    assert [request["op"] for request in server.requests] == ["initialization.inspect"]


def test_peer_guard_covers_real_socket_eof_validation_and_close(serve, root_peer, monkeypatch):
    """Portable guard double, actual connected socket; no PIDFD/UID qualification."""
    active = []
    events = []
    read_response = ipc._read_response
    receipt_response = ipc._receipt_response

    @contextmanager
    def guard(connection):
        assert root_peer == [connection.fileno()]  # Existing peer auth ran first.
        assert connection.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) == socket.SOCK_STREAM
        active.append(connection)
        events.append("enter")
        try:
            yield
        finally:
            assert connection.fileno() == -1
            events.append("closed")
            active.pop()

    def read(connection, deadline):
        assert active == [connection]
        value = read_response(connection, deadline)
        events.append("eof")
        return value

    def receipt(*args, **kwargs):
        assert active and active[0].fileno() >= 0
        events.append("validated")
        return receipt_response(*args, **kwargs)

    monkeypatch.setattr(ipc, "_read_response", read)
    monkeypatch.setattr(ipc, "_receipt_response", receipt)
    server = serve(lambda connection, request: connection.sendall(encode(success(request))))
    assert ipc.InitializationIPCClient(server.path, peer_guard=guard).begin_initialization(INTENT)["intent"] == INTENT
    assert events == ["enter", "eof", "validated", "closed"]
    assert not active and len(server.requests) == 1


@pytest.mark.parametrize("phase", ["factory", "enter"])
def test_peer_guard_failure_before_begin_sends_no_bytes(serve, root_peer, phase):
    server = serve(lambda *_: pytest.fail("Guard refusal must precede any request"))

    class Refused:
        def __enter__(self):
            raise RuntimeError("private-peer-proof")

        def __exit__(self, *_):
            pytest.fail("An unentered proof cannot be released")

    def guard(connection):
        assert root_peer == [connection.fileno()]
        if phase == "factory":
            raise RuntimeError("private-peer-proof")
        return Refused()

    with pytest.raises(ipc.InitializationIPCError) as caught:
        ipc.InitializationIPCClient(server.path, peer_guard=guard).begin_initialization(INTENT)
    assert str(caught.value) == "unavailable"
    assert not caught.value.begin_submitted and not caught.value.uncertain
    assert caught.value.__cause__ is None
    assert not server.requests


@pytest.mark.parametrize("begin", [False, True])
@pytest.mark.parametrize("response", ["success", "forbidden"])
def test_peer_guard_exit_failure_after_send_is_fixed_and_begin_uncertain(serve, root_peer, begin, response):
    def respond(connection, request):
        value = success(request) if response == "success" else {"v": 1, "id": request["id"], "ok": False, "error": "forbidden"}
        connection.sendall(encode(value))

    @contextmanager
    def guard(connection):
        try:
            yield
        finally:
            assert connection.fileno() == -1
            raise RuntimeError("private-peer-proof")

    server = serve(respond)
    client = ipc.InitializationIPCClient(server.path, peer_guard=guard)
    with pytest.raises(ipc.InitializationIPCError) as caught:
        client.begin_initialization(INTENT) if begin else client.inspect_initialization()
    assert str(caught.value) == ("initialization_uncertain" if begin else "unavailable")
    assert caught.value.begin_submitted is begin and caught.value.uncertain is begin
    assert caught.value.__cause__ is None and len(server.requests) == 1


@pytest.mark.parametrize("response", ["malformed", "forbidden"])
def test_peer_guard_cannot_suppress_transport_or_explicit_refusal(serve, root_peer, response):
    observed = []

    class Suppressing:
        def __enter__(self):
            return None

        def __exit__(self, exception_type, exception, traceback):
            observed.append(exception)
            return True

    def respond(connection, request):
        value = b"{}\n" if response == "malformed" else encode({"v": 1, "id": request["id"], "ok": False, "error": "forbidden"})
        connection.sendall(value)

    server = serve(respond)
    with pytest.raises(ipc.InitializationIPCError) as caught:
        ipc.InitializationIPCClient(server.path, peer_guard=lambda _: Suppressing()).begin_initialization(INTENT)
    assert str(caught.value) == ("initialization_uncertain" if response == "malformed" else "forbidden")
    assert len(observed) == len(server.requests) == 1
    assert observed[0] is not None


def test_existing_peer_refusal_never_enters_injected_guard(serve, monkeypatch):
    def deny(_connection):
        raise ipc.InitializationIPCError("forbidden")

    monkeypatch.setattr(ipc, "_verify_server_peer", deny)
    server = serve(lambda *_: pytest.fail("Untrusted peer must receive no request"))
    with pytest.raises(ipc.InitializationIPCError, match="^forbidden$"):
        ipc.InitializationIPCClient(server.path, peer_guard=lambda _: pytest.fail("UID refusal precedes guard")).inspect_initialization()
    assert not server.requests


@pytest.mark.parametrize("entered", [False, True, object()], ids=["false", "true", "object"])
@pytest.mark.parametrize("exit_fails", [False, True])
def test_peer_guard_non_none_entry_is_refused_and_proof_released_before_send(serve, root_peer, entered, exit_fails):
    events = []

    class InvalidProof:
        def __enter__(self):
            events.append("entered")
            return entered

        def __exit__(self, *_):
            events.append("released")
            if exit_fails:
                raise RuntimeError("private-proof-diagnostic")

    server = serve(lambda *_: pytest.fail("A non-None entry is not an admission proof"))
    with pytest.raises(ipc.InitializationIPCError, match="^unavailable$") as caught:
        ipc.InitializationIPCClient(server.path, peer_guard=lambda _: InvalidProof()).begin_initialization(INTENT)
    assert not caught.value.begin_submitted and not caught.value.uncertain
    assert caught.value.__cause__ is None
    assert events == ["entered", "released"] and not server.requests
