"""In-memory TLS interop only. No socket, radio, Pi, Wi-Fi or real credentials."""
import ctypes as C
import hashlib
import json
import platform
import ssl
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
lib = C.CDLL(str(BASE / "libinky_c2_bench.dylib"))
def signature(name, args, result):
    f = getattr(lib, name); f.argtypes = args; f.restype = result; return f
ptr, n, integer, byteptr = C.c_void_p, C.c_size_t, C.c_int, C.c_char_p
new = signature("bench_new", [byteptr, n, byteptr, C.POINTER(integer)], ptr)
free = signature("bench_free", [ptr], None)
hs = signature("bench_handshake", [ptr], integer)
feed = signature("bench_feed", [ptr, byteptr, n], integer)
take = signature("bench_take", [ptr, ptr, n], integer)
write = signature("bench_write", [ptr, byteptr, n], integer)
read = signature("bench_read", [ptr, ptr, n], integer)
close = signature("bench_close", [ptr], integer)
app_written = signature("bench_app_written", [ptr], n)
pin_rejected = signature("bench_pin_rejected", [ptr], integer)
version = signature("bench_version", [ptr], byteptr)
error_text = signature("bench_error", [integer, ptr, n], None)
WANT_READ, WANT_WRITE = -0x6900, -0x6880
buffer = C.create_string_buffer(65536)
pin = hashlib.sha256((BASE / "server-spki.der").read_bytes()).digest()

def error(code):
    error_text(code, buffer, len(buffer)); return buffer.value.decode()

def run_case(name, bad_pin=False, corrupt_record=False):
    ca = (BASE / "ca.pem").read_bytes() + b"\0"
    expected = bytes([pin[0] ^ 1]) + pin[1:] if bad_pin else pin
    init_error = integer()
    client = new(ca, len(ca), expected, C.byref(init_error))
    assert client, error(init_error.value)
    incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.minimum_version = server_ctx.maximum_version = ssl.TLSVersion.TLSv1_3
    server_ctx.num_tickets = 0
    server_ctx.load_cert_chain(BASE / "server.pem", BASE / "server.key")
    server = server_ctx.wrap_bio(incoming, outgoing, server_side=True)
    chunks = {"client_to_server": 0, "server_to_client": 0}
    wire = {"client_to_server": bytearray(), "server_to_client": bytearray()}
    largest_chunk = 0
    deadline = time.monotonic() + 10

    def pump(tamper=False):
        nonlocal largest_chunk
        count = take(client, buffer, 20)
        if count:
            data = buffer.raw[:count]
            if tamper: data = data[:-1] + bytes([data[-1] ^ 1])
            assert len(data) <= 20
            incoming.write(data)
            chunks["client_to_server"] += 1
            wire["client_to_server"].extend(data)
            largest_chunk = max(largest_chunk, len(data))
        if outgoing.pending:
            data = outgoing.read(20)
            assert feed(client, data, len(data)) == len(data)
            chunks["server_to_client"] += 1
            wire["server_to_client"].extend(data)
            largest_chunk = max(largest_chunk, len(data))
        assert time.monotonic() < deadline, "Bounded ten-second timeout"

    try:
        # The wrapper refuses any application payload before authenticated TLS.
        assert write(client, b"PREMATURE", 9) == -3
        assert app_written(client) == 0
        start = time.perf_counter()
        server_ready = False
        for _ in range(20000):
            result = hs(client)
            if result < 0:
                assert bad_pin and pin_rejected(client), error(result)
                assert app_written(client) == 0
                assert write(client, b"FORBIDDEN", 9) == -3
                return {"name": name, "pass": True, "pin_rejected": True,
                        "application_bytes_sent": app_written(client),
                        "client_error": error(result), "elapsed_ms": round((time.perf_counter()-start)*1000, 3),
                        "chunks": chunks, "max_fragment_bytes": largest_chunk}
            if not server_ready:
                try: server.do_handshake(); server_ready = True
                except (ssl.SSLWantReadError, ssl.SSLWantWriteError): pass
            pump()
            if result == 0 and server_ready: break
        else: raise AssertionError("handshake iteration budget")
        assert not bad_pin, "Bad pin was unexpectedly accepted"
        assert version(client) == b"TLSv1.3" and server.version() == "TLSv1.3"
        handshake_ms = (time.perf_counter()-start)*1000
        payload = bytes((i * 37 + 19) % 256 for i in range(600))
        assert write(client, payload, len(payload)) == len(payload)
        received, echoed = bytearray(), bytearray()
        sent_echo = False
        tampered = False
        for _ in range(20000):
            pump(tamper=corrupt_record and not tampered)
            tampered = True
            try:
                fragment = server.read(4096)
                received.extend(fragment)
            except (ssl.SSLWantReadError, ssl.SSLWantWriteError): pass
            except ssl.SSLError as failure:
                assert corrupt_record and len(received) == 0
                return {"name":name,"pass":True,"tls":"TLSv1.3", "corrupt_record_rejected":True,
                        "server_application_bytes_received":0,
                        "server_error":{"type":type(failure).__name__,"message":str(failure),
                                        "errno":failure.errno,"reason":failure.reason},
                        "handshake_ms":round(handshake_ms,3),"max_fragment_bytes":largest_chunk}
            if received == payload and not sent_echo:
                assert server.write(bytes(received)) == len(payload); sent_echo = True
            count = read(client, buffer, len(buffer))
            if count > 0: echoed.extend(buffer.raw[:count])
            else: assert count in (WANT_READ, WANT_WRITE), error(count)
            if echoed == payload: break
        else: raise AssertionError("echo iteration budget")
        assert not corrupt_record, "Corrupt record accepted"
        assert bytes(received) == payload and bytes(echoed) == payload
        assert all(payload not in data for data in wire.values())
        assert app_written(client) == 600
        assert close(client) in (0, WANT_READ, WANT_WRITE)
        return {"name":name,"pass":True,"tls":"TLSv1.3","cipher":server.cipher()[0],
                "pin":"SHA256(DER SubjectPublicKeyInfo)","pre_handshake_write_refused":True,
                "handshake_ms":round(handshake_ms,3),"total_ms":round((time.perf_counter()-start)*1000,3),
                "application_bytes_each_way":600,"max_fragment_bytes":largest_chunk,
                "chunks":chunks,"encrypted_bytes":{key:len(data) for key,data in wire.items()}}
    finally: free(client)

cases = [run_case("pinned-tls13-fragmented-echo"),run_case("wrong-pin-no-payload",bad_pin=True),
         run_case("corrupt-encrypted-record",corrupt_record=True)]
report={"scope":"synthetic-memory-buffers-only-no-radio-no-pi",
        "platform":platform.platform(),"machine":platform.machine(),"python":platform.python_version(),
        "openssl":ssl.OPENSSL_VERSION,"mbedtls":"4.1.1",
        "dylib_stripped_bytes":(BASE/"libinky_c2_bench.dylib").stat().st_size,
        "source":json.loads((BASE/"source.json").read_text()),"cases":cases,
        "limitations":["Native macOS C/ctypes, not Swift/iOS or BLE",
                       "Synthetic CA supplied independently; QR-only trust/X509 policy not qualified",
                       "No ownership, revocation, persistence, Wi-Fi or failure recovery",
                       "Default library crypto configuration, static link/dead strip; not minimum iOS size"]}
(BASE/"result.json").write_text(json.dumps(report,indent=2)+"\n")
print(json.dumps(report,indent=2))
