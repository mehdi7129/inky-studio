# Initialization IPC v1 — coordinated implementation contract

Agreed between the Studio and InkyOS sessions on 11 October 2026. This is a
local initialization boundary, not a BLE extension or an enabled first-boot
flow. The production recipe, service activation and factory lifecycle remain
separate integration gates. It must not be installed on the current TEST SD.

Studio owns the client and shared fixtures. InkyOS owns the root service,
root-owned durable receipt, unit and Linux peer-credential qualification. The
existing network-helper v1 and Bluetooth v1 remain unchanged.

## Socket and actors

- AF_UNIX stream at `/run/inkyos-bootstrap/control.sock`.
- Parent directory `root:inky-provisioning`, mode `0750`; socket same owners,
  mode `0660`. The nonroot group cannot replace the socket or its directory.
- Server gets the connected caller's UID from Linux `SO_PEERCRED`, never a
  request field. Only the explicitly configured Studio service UID may use
  these operations (UID 1000 in the proposed image). Root and the distinct
  `inky-network` helper UID are not initialization clients.
- Client verifies kernel peer UID **0 before sending any bytes**. A socket
  path alone is not server authentication. Unsupported platforms fail closed;
  injected peer identities in portable tests are not a Linux qualification.
- One request and one response per connection. The server closes after the
  response. The client requires EOF after the single response line; bytes after
  its newline are invalid. Neither endpoint pipelines or reconnects to retry.
- UTF-8 JSON followed by one LF, with a maximum of **1024 request bytes** and
  **2048 response bytes, including LF**. Reject duplicate object keys, non-finite
  numbers, unknown fields, wrong primitive types and noncanonical UUIDs.
- Client and server use the same **20-second absolute monotonic budget** per
  connection: client starts before connect; server starts at accept. This
  includes the connected-peer proof (up to 15 seconds), 3 seconds for the
  exchange and 2 seconds of margin. Connect, peer check, send, response and EOF
  share that budget; completing the proof or receiving a byte never resets it.
  Server never interprets a caller timeout/disconnect as permission to undo
  consumption. If proof exhausts the client budget, no request is sent.

## Requests

Every operation gets a fresh request ID. The initialization **intent** is the
already-persisted coordinator intent and is retained across process restarts.

```json
{"v":1,"id":"11111111-1111-4111-8111-111111111111","op":"initialization.inspect"}
```

```json
{"v":1,"id":"11111111-1111-4111-8111-111111111111","op":"initialization.begin","intent":"22222222-2222-4222-8222-222222222222"}
```

`v` is integer 1, not boolean/float. `id` and `intent` are lowercase canonical
UUID strings. No path, UID, shell command, country, time, credential or owner
token is accepted. There is no remote `create_authorization` or reset operation.

## Responses

Success has exactly `v`, `id`, `ok`, `result`; `ok` is boolean true and `id`
matches the request. `result` is the existing receipt model's exact subobject:

| Operation | Exact result |
|---|---|
| inspect, unconsumed | `{"status":"authorized"}` |
| inspect, consumed | `{"status":"consumed","intent":UUID,"receipt":{"receipt_id":UUID,"digest":HEX64}}` |
| begin, newly consumed | `{"status":"newly_consumed","intent":UUID,"receipt":{"receipt_id":UUID,"digest":HEX64}}` |
| begin, previous consumption | Same fields, `status: "already_consumed"` |

UUIDs are canonical; digest is exactly 64 lowercase hexadecimal characters.
The begin response intent equals the submitted intent. No experimental model
snapshot, filesystem location or extra field appears in the response.

Failure has exactly `v`, `id`, `ok: false`, `error`. Fixed error vocabulary:

| Error | Meaning |
|---|---|
| `invalid_request` | Request refused before invoking receipt mutation |
| `forbidden` | Kernel caller UID not admitted; no receipt mutation |
| `unavailable` | No usable result; never infer authorization |
| `intent_conflict` | Receipt belongs to another intent; preserve existing state |
| `initialization_uncertain` | Consumption may have occurred; same-intent inspection/recovery only |

An undecodable request may receive `id: null`. The Studio client always sends a
valid ID and therefore rejects null, mismatched IDs, unknown codes or malformed
envelopes. Error strings never include request data, receipts, paths or exception
text. Server-side receipt corruption/absence is an error, not `authorized`.

## Irreversible consumption and recovery

The service directly invokes the reviewed durable receipt `inspect()` or
`begin(intent)` once. Only a successful **current begin call** returning
`newly_consumed` can authorize creation of the app's factory database. A readable
file, an inspect result or a previous response cannot stand in for that call.

The client sends at most once. Once it starts submitting begin, timeout, EOF,
I/O error, invalid response, `unavailable` or `initialization_uncertain` are
conservatively uncertain. A valid `invalid_request`, `forbidden` or
`intent_conflict` is a server-declared refusal. The existing coordinator remains
conservative for every failed begin invocation and never creates a database from
an error. Authentication/refusal before submission sends no request.

After lost response, inspect with the **same durable intent**. If consumed,
begin on that intent returns only `already_consumed`; it may reopen a consistent
existing ledger but cannot recreate a missing one. Crash between root consumption
and app database creation requires explicit recovery. Missing identity, database,
credentials or receipt never reopens factory initialization.

## Validation and integration gates

Shared synthetic vectors live in
[`shared/initialization-ipc-v1.json`](../../shared/initialization-ipc-v1.json).
The client tests must exercise strict schemas/bounds, root peer authentication
before submission, a single deadline under dribbling input, no retry, reply loss,
and preservation of coordinator consumption rules.

InkyOS must additionally test real Linux kernel peer credentials with distinct
root/app/helper users, root directory/socket ownership, process interruption at
receipt persistence boundaries, and preservation across service restarts. A Mac
fixture with an injected UID cannot establish any of those guarantees.

Before production activation: agree the factory authority creation hook; connect
credential persistence and `FirstBootCoordinator` without invoking the legacy
auto-creation path; qualify the one-owner lifecycle, physical QR, bootstrap TLS
dispatcher, iOS flow and recovery. This IPC does not set the time/country, release
the Wi-Fi gate, create an owner, show a QR or qualify a physical frame.

Phase B will use a distinct helper-to-OS system boundary. It still needs a
reviewed durable operation journal (old timestamps must never be reapplied),
explicit time bounds/NTP restoration, country observation and radio-gate release
before scan. Its schemas are not inferred from this initialization protocol.
