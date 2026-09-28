# First boot without an existing LAN — coordination draft

Status: **design requirements, not an implemented protocol or release gate
closure**. Prepared on 2026-09-28 against application source
`80dfc37629fe4d3853ed80bf614c5fad2e8512ba` in branch
`codex/first-boot-contract`. This branch does not contain the sibling offline
packaging PR #13. The existing Bluetooth candidate and deployed Pi stay separate.

## Shared objective and ownership

A fresh InkyOS frame must display its own setup information, accept an iPhone
without a shared LAN, establish a usable clock, apply the user's Wi-Fi country,
and connect to a supported WPA2 Personal 2.4 GHz network. Claim and subsequent
photo authentication must both be usable. No app identity, QR secret, owner,
password or photo database is created while building an image.

The Inky Studio session owns this document and all app, iOS, protocol and helper
changes. The InkyOS session owns its separate repository's image integration,
system packages, host initialization and VM qualification. Neither session edits
the other's files without assigning a specific subtask. Until an executable
contract is reviewed and tested, InkyOS may package a pinned application but
must keep automatic app/helper startup disabled.

| Owner | Files / responsibility | Required change |
| --- | --- | --- |
| Inky Studio | `server/inky_web/main.py`, new factory state module | Guard initialization before any credential/identity/ownership auto-creation; single runtime and display owner |
| Inky Studio | `server/inky_web/auth.py`, `welcome.py` | Preserve password migration; retain a usable initial photo-login path after QR claim |
| Inky Studio | `provisioning/identity.py` | Separate durable key identity from certificate issuance; preserve frame UUID and key across clock repair |
| Inky Studio | `provisioning/ownership.py`, `runtime.py`, `screen.py` | Atomic claim/state transition; journaled display intent and reconciliation |
| Inky Studio | `provisioning/bluez.py`, `transport.py`, protocol docs | Versioned bootstrap capability, bounded per-peer parsing, explicit compatibility rules |
| Inky Studio | `scripts/inky-network-helper.py`, `install-bluetooth.sh`, any new helper | Narrow authenticated-app-to-system operations, privilege boundaries and crash recovery |
| Inky Studio | `ios/InkyStudio/Provisioning/`, connection/setup UI and tests | New-frame entry, authenticated bootstrap, country confirmation, errors and resumption |
| InkyOS | image recipes, first-boot host setup, units and package inventory | Host identity and prerequisites; install reviewed helper artifacts without executing installers during assembly |
| Both | inert fixtures and qualification reports | Exact source hashes, machine-readable expected outcomes, explicit mock/VM/hardware distinction |

Paths beginning with `provisioning/` are relative to `server/inky_web/`.

## Existing behavior verified in source

- `serve_with_https()` creates/loads TLS identity before the application
  lifespan. New certificates require a clock at or after 2026-01-01. Existing
  leaves last 396 days; renewal preserves the key. The iPhone checks validity
  dates as well as the physical key pin.
- Credential, identity and ownership loaders can initialize a missing store.
  They do not currently consult a durable factory authorization record.
- An initial QR window requires an authenticated network session. BLE v1 and
  helper requests have strict schemas without time or country operations.
- Claim is transactional and retryable; iOS persists its owner token before
  sending it. Bluetooth ownership does not authenticate photo API requests.
- Claim closes the QR screen. With no photo history, restoration displays only
  “Inky Studio”, so the initial application password needs a deliberate display
  sequence. Empty history must not become permission to adopt a frame.
- The helper can represent `previous_uuid = null`. Recovery then has no old LAN
  to restore; it must preserve the owner and allow another authorized attempt.

These observations are first-boot design gaps. The existing Bluetooth flow still
has its own open physical qualification criteria; this draft closes none of them.

## Durable state requirements

The implementation will distinguish at least:

| Conceptual state | Permitted behavior |
| --- | --- |
| No valid initialization authority | No automatic factory entry; existing installations use an explicit compatibility/migration path |
| Factory initialization pending | Resume the same explicitly authorized initialization, or report recovery if its durable records disagree |
| Factory, unclaimed | Show a bounded physical setup window using this device's identity; authorize no other operations through public discovery |
| Adopted | Bootstrap/BLE recovery requires an authorized owner; missing Wi-Fi or an expired certificate cannot reopen factory adoption |
| Recovery required | Preserve evidence and identity; no credential regeneration, ownership clearing or automatic reset |

These names are conceptual, **not a committed file format**. Before runtime work,
specify the initial authorization source, storage paths/permissions, journaling
order, and reconciliation for every interruption. A static image flag plus an
empty app directory is insufficient: deleting application files on an initialized
device must not look like a new frame. A consumed initialization receipt or an
equivalent independently retained record is needed. A deliberate whole-device
reflash is a separate reset operation; this software-only design does not promise
anti-rollback protection against someone restoring the entire storage medium.
An adopted frame still supports photo login with the application password and
the existing authenticated-session flow for adding a phone; Bluetooth ownership
does not replace either authentication policy.

Factory claim must become terminal atomically with its owner receipt. A lost
response must be retryable by that same phone, without permitting another owner.
Wi-Fi success, photo login, password rotation and the number of currently active
owners do not control this terminal transition. In particular, revoking the last
phone cannot turn an adopted frame back into a factory frame.
Reboot invalidates the previous QR window and transient transport proofs. Only
an explicitly unclaimed, authorized factory state may open a replacement window.
Expiry and rate limits must use monotonic time and survive clock adjustments
without extending an existing authorization window.

## Clock bootstrap: decision still open

Adding a `time` command inside TLS v1 cannot solve initial certificate issuance
or an expired certificate: the trusted connection is not yet available. The
proposed design direction is an independently authenticated bootstrap exchange,
followed by ordinary fully verified TLS. This is an application design proposal,
not a reviewed cryptographic protocol.

The protocol review must settle all of the following before defining wire bytes:

- Physical QR proof for a genuinely new frame, and a **separate existing-owner
  recovery path** for a frame with an invalid clock or expired certificate.
  Existing-owner recovery must not reset adoption or transmit the owner token
  outside a confidential authenticated channel.
- Authentication of frame identity and the complete request, fresh challenges,
  direction/version separation, replay and reflection resistance, and strict
  lifetime/size/rate limits. No time, country or ownership mutation before proof.
- State what the phone's time proves: it is an assertion from the authorized
  phone, not an independently trusted time authority. Define numeric bounds,
  backward/forward correction policy and recovery from a previously bad future
  value. A naive permanent high-water mark could lock a frame after one bad time.
- Bootstrap permits only the narrowly reviewed prerequisites. It never transports
  Wi-Fi passwords, photo passwords or arbitrary commands before normal TLS.
- Certificate issuance/renewal follows accepted time and retains the same key.
  iOS verifies the resulting certificate normally, including dates, identity,
  name and usage. No accept-all verifier or disabled date check.

Possible primitives and their libraries require a separate security decision,
cross-language test vectors and adversarial review. Do not extend QR v1 or its
GATT stream by silently accepting new fields. Unknown capability/version is an
explicit unsupported result, with no downgrade fallback for a new-frame flow.

## Clock and country system boundary

The app authenticates the request; a narrow helper applies system changes.
OS installation does not grant the ordinary app account general clock-setting,
network administration or shell privileges. Helper requests need strict types,
fixed operations, authorization of the local caller, bounded input and receipts.
An ACK means the relevant system state was verified, not merely that a subprocess
was launched. The exact API remains pending joint review.

The systemd `SetTime` API uses microseconds since the Unix epoch and separates
absolute/relative mode and interactive authorization. `SetNTP` changes service
state; its use needs an explicit restoration policy rather than a permanent
disable. See the [official timedate interface](https://github.com/systemd/systemd/blob/main/man/org.freedesktop.timedate1.xml).
The upstream [polkit policy](https://github.com/systemd/systemd/blob/main/src/timedate/org.freedesktop.timedate1.policy)
also declares implied permissions for `set-time`. Verify the actual Trixie policy
and effective permissions before claiming a narrowly scoped deployment.

Country is a user-confirmed current operating location, not a value inferred from
language, timezone or nationality. Validate against an explicit supported list;
two uppercase letters alone are not sufficient. Confirm the effective regulatory
state for the target radio before scan or connection. The kernel and driver may
restrict a requested domain; success cannot be inferred from the requested code
alone. See [Linux wireless regulatory documentation](https://cdn.kernel.org/doc/html/latest/networking/regulatory.html)
and [driver/regulatory interactions](https://wireless.docs.kernel.org/en/latest/en/developers/regulatory/processing_rules.html).

Country changes while a transaction is pending require a defined reject/cancel
policy. Persisted country must be reconciled after reboot before Wi-Fi operations.
On an unconfigured factory image, **InkyOS owns the boot-time Wi-Fi radio and
NetworkManager scan/autoconnect gate**; checking only app/helper commands is not
sufficient. The reviewed helper-to-OS acknowledgement will release that gate
only after effective regulatory state is verified. The exact mechanism, persisted
state and startup ordering remain to be tested on the target. Existing configured
frames need a migration/reconciliation path preserving their valid configuration,
not an unconditional Wi-Fi disable introduced by an application update.
No change may broaden the existing supported network types or silently reconnect
another profile. Confirm first-network success through the adopted frame's pinned
HTTPS endpoint, as for the current flow.

The [BlueZ GATT API](https://bluez.readthedocs.io/en/latest/gatt-api/) exposes the
peer device, offset and MTU to the server. Bootstrap must retain per-peer
isolation and bounded MTU-aware framing. Notifications must not expose private
setup data across sessions. These API capabilities do not themselves provide
application authentication.

## Shared acceptance cases

All cases initially use synthetic data and injected clock/network/display
adapters. No real credentials enter fixtures, screenshots, logs or peer messages.

| ID | Scenario | Required observable result |
| --- | --- | --- |
| FB-01 | Build two images; inspect files and intercepted service calls | No app startup or generated per-frame credential/key/owner/QR in either image |
| FB-02 | Explicit fresh initialization with no LAN and implausible time | A usable physical setup path exists without certificate-validation bypass |
| FB-03 | Initialized frame loses any previously established identity, credential, ownership or factory record | Recovery state; no new password/key/QR adoption authority; a legacy installation that never had a factory record uses explicit migration |
| FB-04 | Kill initialization between every durable write; restart | Same identity or explicit recovery; no duplicate authority or silent reset |
| FB-05 | Two phones claim concurrently; lose the winner's reply | One terminal owner; idempotent retry by the winner; loser rejected |
| FB-06 | Reboot, stale QR, replay, changed nonce/epoch/country/frame, oversized payload | No privileged mutation or owner disclosure; fixed non-secret errors |
| FB-07 | Adopted frame stored beyond certificate expiry with no LAN | Existing-owner clock repair or explicit recovery; no factory reopening |
| FB-08 | Wrong/future phone time; NTP enabled; helper error or restart | Bounded documented outcome and recoverable state; no false success |
| FB-09 | Unsupported country, different applied domain, country change during Wi-Fi trial; autonomous NetworkManager startup on a factory image | No scan/connect until acceptable effective state, including before app startup; no partial success report |
| FB-10 | Wrong Wi-Fi password when no previous network exists | Same owner/key preserved; another authorized trial possible |
| FB-11 | Claim succeeds; no photo history; app reconnects | Initial photo login remains usable; display reservation prevents competing refreshes |
| FB-12 | Legacy v1 client/frame and new bootstrap-capable client/frame combinations | Explicit compatibility behavior; no relaxed parsers or insecure fallback |

Extend the matrix with existing-installation migration preserving password/pin/
photos, Keychain write failure before claim, and password rotation or revocation
during a Wi-Fi trial. Migration may not infer a new frame from missing records;
revocation may not recreate factory authority.

Passing these fixtures does not qualify radio, GPIO/SPI, real e-ink readability,
NetworkManager rollback, minimal-image native dependencies or iPhone behavior.
Those require separate VM and physical reports tied to the integrated commit.

## Implementation sequence and handoff

InkyOS can prepare declarative units, policy files and launcher placement from
the **exact pinned** `install.sh`, `scripts/install-bluetooth.sh` and launcher
sources. Do not run or source those shell installers during generation. Record
the source hash and compare rendered permissions, paths, arguments and service
identities against that source; list intentional differences such as masked
units. Do not widen sudo/polkit rules, enable services, or invent bootstrap
variables based on this draft. Source-controlled templates shared by both
install paths are the preferred follow-up; their extraction needs app-repository
review and equivalence tests before they replace installer behavior.

1. Review durable initialization authority and bootstrap cryptographic design;
   agree schemas, compatibility, primitive inventory and privilege boundary.
2. Implement factory state and interruption tests behind explicit opt-in; keep
   current installations on their unchanged initialization path until migration
   behavior is specified and tested.
3. Implement helper adapters and target-VM tests; publish operation fixtures and
   capability/version contract before enabling image units.
4. Implement backend and iOS bootstrap together with interoperability vectors,
   then the initial password/country/Wi-Fi user flow.
5. Integrate an exact reviewed app/helper build in the experimental image and
   run the complete fixture matrix before physical qualification.

The next handoff is this requirements draft and the source hash, **not a claim
that first boot is implemented**. InkyOS should review the initialization-receipt
boundary and target clock/regulatory behavior before either side freezes an API.

Application work now includes an [internal opt-in factory-state foundation](FACTORY-STATE.md).
It implements only the ownership ledger and claim transition. It does not verify
the real OS receipt or enable the runtime/bootstrap interfaces described above.
