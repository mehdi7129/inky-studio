# Build a PHOTO client

A client communicates directly with an InkyOS frame on the local network. The [LAN runtime contract](IMAGER-LAN.md) defines the invitation QR, the frame UUID, its SPKI SHA-256 pin, the canonical HTTPS endpoint and the `owner` and `media` roles. Use the exact frame pin from the trusted QR. Keep TLS validation and origin checks active, and keep a separate cookie jar per connection. Never pass a device token, invitation token or photo to a plain HTTP endpoint.

| Operation | API entry point |
| --- | --- |
| Accept a single-use invitation | `POST /api/auth/invitations/claim` |
| Reopen an existing device session | `POST /api/auth/device-session` |
| Verify identity on a trusted TLS candidate before reopening a session, rc5+ | `GET /api/auth/frame-identity` |
| Read or add to the queue | `GET /api/queue` or multipart `POST /api/queue` with `file`, using a PNG cropped to the exact display size |
| Confirm an upload, rc5+ | Include a stable `Idempotency-Key` UUID on upload. Look it up with `GET /api/queue/uploads/{id}`; a matching accepted retry returns the original result. |
| Read history or control display | `/api/history` and `/api/display` |

Store device credentials in protected device storage. Preserve the previous locator until the candidate presenting the same UUID and SPKI opens a device session. For an uncertain upload on an older service without receipts, keep the prepared photo and have the user verify the queue before starting another send.

Start from the route definitions for [access](../server/inky_web/api/photo_access.py), [queue](../server/inky_web/api/queue.py), [history](../server/inky_web/api/history.py) and [display](../server/inky_web/api/display.py). The [Swift clients](../ios/InkyStudio/Core) and [LAN integration tests](../server/tests/test_lan_photo.py) are working references.
