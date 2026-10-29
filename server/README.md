# Inky Studio — photo service

> **Current delivery —29 October2026:** use the [current release guide](../docs/releases/ios-v1.0.0-build19.md).
> iPhone1.0.0(19) and PHOTO0.5.0rc2 are preserved in the source release tag
> `ios-v1.0.0-build19` and separate frozen component branches.
> **This main checkout retains the earlier implementation.** Check out the
> matching tag/branch before following candidate build or installation instructions.
> The older sections below retain their historical scope; they are not current
> TestFlight availability or proof of a public AppStore release.


The Python/FastAPI service runs on the frame. It receives photos, maintains their queue/history and schedule, and controls display operations. The React web interface is retained for the legacy installation; the current InkyOS/Imager path is used with the native iPhone app.

## Select the right source and runtime

| Runtime | Source / installation | Connection and updates |
|---|---|---|
| Legacy web/password service | Implementation retained on `main` | Local HTTP port 8000; legacy installer and updater |
| Imager-configured LAN frame | [InkyOS](https://github.com/mehdi7129/inkyOS) image, prepared with [inkyImager](https://github.com/mehdi7129/inkyImager) | HTTPS port 8443 and QR-bound identity; maintenance follows InkyOS |
| LAN photo-sharing candidate | [release/backend-lan-photo-sharing-20261023](https://github.com/mehdi7129/inky-studio/tree/release/backend-lan-photo-sharing-20261023), source `716104b1` | Tested/packaged, **not yet installed on the current SD** |

The source branches are separate from `main`. The existing physical LAN installation uses `b75bf1e7`; iPhone beta 16 was reported working with it. Beta 17 is available through internal TestFlight and remains compatible while the service update is pending.

See the [ecosystem checkpoint](../docs/ECOSYSTEM.md) and the candidate's [LAN contract](https://github.com/mehdi7129/inky-studio/blob/release/backend-lan-photo-sharing-20261023/docs/IMAGER-LAN.md).

## LAN photo access and sharing

The explicit Imager/LAN runtime serves photo access over HTTPS on port **8443**. It does not use the legacy HTTP listener for this flow. InkyOS supplies system/hardware configuration and the frame identity; inkyImager prepares the card and network configuration.

The initial QR gives a phone a `media` photo credential, not an administrator role. In the LAN sharing candidate, validated session/claim replies advertise the Boolean `can_invite`. Each authorized member can create a short-lived, single-use photo invitation and cancel its own invitation. The recipient remains `media` and receives a separate credential. The issuer is validated again at claim time.

Wi-Fi configuration, software updates and device administration remain outside the photo member's authority. Outside the explicit LAN runtime, media invitation creation remains refused. The QR envelope and photo-access database schema version **1** are unchanged.

The frozen candidate passed **138 focused backend tests**, including HTTPS A → B → C sharing, a photo operation by B, expiry/cancellation, administrative refusals and credential restoration after restart. A synthetic b75 → candidate → b75 → candidate check preserves the three credentials and schema. This does not claim deployment on the real card or a completed physical two-iPhone test.

## Update an existing Imager/LAN card

The current installation does not offer the legacy checkout/pip/sudo updater to photo members. Follow [InkyOS maintenance](https://github.com/mehdi7129/inkyOS) for its verified offline SD procedure. Source publication or a new iPhone build alone does not update the service.

The prepared delta changes three Python modules and their corresponding entries in the installed package `RECORD`. Preserve all other locally installed entries, including installer metadata; do not overwrite it with the wheel's `RECORD`. Identity/TLS material, Wi-Fi configuration, device credentials, database and photos must remain intact. No database migration or re-pairing is part of this candidate.

## Legacy local development

These commands are for the development/legacy service in the selected checkout, not an installation recipe for an existing Imager/LAN SD:

```bash
cd server
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
inky-studio-server
```

The local development endpoint is `http://localhost:8000/api/health`. A successful health response proves reachability, not physical display completion.

Off-Pi development uses a mock display. On a Raspberry, the optional `.[pi]` dependencies provide the real driver, but auto-detection or a test suite does not qualify every panel/Pi combination. Use InkyOS's admitted hardware profile for the image installation.

## Tests

```bash
cd server
ruff check .
pytest
```

Tests use temporary/synthetic state. Keep real credentials, pairing QRs, signed packages, SD images and runtime databases out of Git. Preserve dated audit reports as historical evidence rather than rewriting their original results.
