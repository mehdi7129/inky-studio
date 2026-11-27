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

Store device credentials in protected device storage. A device session can include an optional `stable_locator` with the frame’s configured mDNS address. Preserve the previous locator until a known candidate presents the same UUID and SPKI and opens a device session. A device with no reachable saved locator still needs a new way to learn the frame’s current address.

For an uncertain upload on a service without receipts, look for the same hash in the current queue. A match confirms that the photo is in the queue. When no match exists, retain the draft and present the uncertainty to the user. Installing a service with receipts later cannot retroactively confirm an earlier request.

Start from the route definitions for [access](../server/inky_web/api/photo_access.py), [queue](../server/inky_web/api/queue.py), [history](../server/inky_web/api/history.py) and [display](../server/inky_web/api/display.py). The [Swift clients](../ios/InkyStudio/Core) and [LAN integration tests](../server/tests/test_lan_photo.py) are working references.
