"""Synthetic TLS peer over JSON stdin/stdout; no socket, Bluetooth or real credentials."""
import base64
import json
import ssl
import sys
import time
from pathlib import Path

directory, label = Path(sys.argv[1]), sys.argv[2]
incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
profile = sys.argv[3] if len(sys.argv) > 3 else "normal"
context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_2 if profile == "tls12" else ssl.TLSVersion.TLSv1_3
context.num_tickets = 0
if profile in {"bootstrap", "tls12"}:
    context.set_alpn_protocols(["inky-bootstrap/1"])
elif profile == "wrong-alpn":
    context.set_alpn_protocols(["inky-normal/1"])
key = label if label in {"other", "p384"} else "server"
context.load_cert_chain(directory / (label + ".pem"), directory / (key + ".key"))
server = context.wrap_bio(incoming, outgoing, server_side=True)
ready = False
received = bytearray()
terminal_error = None
for line in sys.stdin:
    request = json.loads(line)
    if request.get("delay_reply") == "true":
        time.sleep(1.2)  # Exercise the client's repeated poll, without radio/network.
    try:
        if request.get("feed"):
            incoming.write(base64.b64decode(request["feed"]))
        if not ready:
            server.do_handshake()
            ready = True
        if "write" in request:
            server.write(base64.b64decode(request["write"]))
        if request.get("close"):
            server.unwrap()
        else:
            while True:
                data = server.read(16384)
                if not data:
                    break
                received.extend(data)
    except (ssl.SSLWantReadError, ssl.SSLWantWriteError):
        pass
    except ssl.SSLError as error:
        terminal_error = str(error)
    print(json.dumps({"out": base64.b64encode(outgoing.read()).decode(),
                      "received": base64.b64encode(received).decode(),
                      "ready": ready, "error": terminal_error}), flush=True)
