# System setup IPC — OS facts and contract proposed for root review

Status: design only, no runtime implementation or activation authorized. OS
checkout `/Users/mehdiguiard/Library/Caches/inkyos-factory-system-setup-20261016`
starts at `e674e96`; backend starts at `d67db9e`. The shared normative field
schemas are in `ipc-contract.json`. This draft must be approved together with
the backend wire/startup contract before any implementation.

## Real native peer identification

The existing `staging/bootstrap/writer-graph.py` already implements the exact
stdlib-to-PID1 bridge: `ReadOnlyCommands.call()` invokes `/usr/bin/busctl` with
an inherited pidfd; `KernelBackend.resolve()` checks the PID1 result, and
`Graph.initialization_guard()` compares it with observed MainPID/InvocationID
anchors and the fresh admitted graph. We extend these existing guards with
explicit setup/helper roles and expected credentials, not a homemade D-Bus
client or a generic root/UID allowlist.

The concrete subprocess argv is:

```text
/usr/bin/busctl --system --json=short --auto-start=no
  --allow-interactive-authorization=no --timeout=<remaining>s call
  org.freedesktop.systemd1 /org/freedesktop/systemd1
  org.freedesktop.systemd1.Manager GetUnitByPIDFD h <fd>
```

`subprocess.Popen(..., pass_fds=(fd,), close_fds=True, env={...})` passes the
socket peer's real `SO_PEERPIDFD` descriptor. systemd v257.13 supports this
manager method and its `o,s,ay` reply. Its busctl parser explicitly accepts
UNIX_FD arguments from inherited descriptors. These are existing upstream and
local implementations, not an assumed future API. Primary references:
[manager API](https://raw.githubusercontent.com/systemd/systemd/v257.13/man/org.freedesktop.systemd1.xml),
[busctl FD parser](https://raw.githubusercontent.com/systemd/systemd/v257.13/src/busctl/busctl.c).
The real native method/FD transfer still needs an inert PID1 fixture when the
builder is released; neither a unit fixture nor this source reading establishes
that runtime proof.

A caller must match the exact pinned unit, MainPID, InvocationID, launch argv,
unit security policy, current candidate, boot context and retained shared writer
lease before and after queries/effect admission. The peer pidfd stays held and
live. No read of another UID's `/proc/<pid>/exe` or `/proc/<pid>/root` is required;
no SYS_PTRACE is added to defeat a permission failure. Missing PIDFD/method or
ambiguous native observation refuses closed, without numerical-PID fallback.

## Privileges and owned lifetime

A separate new `inkyos-system-setup.service` runs root:inky-provisioning with
only SYS_TIME and NET_ADMIN. The existing initialization IPC remains incapable
of changing the clock/radio. ProtectClock must explicitly be false and the
setter must use the host network namespace. RestrictAddressFamilies includes
AF_UNIX, AF_NETLINK and AF_INET: the read-only mapping/firmware path may require
an AF_INET/SOCK_DGRAM ioctl socket. This grants neither NET_RAW nor vendor SET.
Only fixed native commands/read-only GET data are accepted; no shell, arbitrary
command or user path. No owner token, QR secret or Wi-Fi password enters IPC.
No Studio code is imported or executed under root.

Owner/claim/epoch validation is explicitly delegated to the actually admitted,
pinned main after its real `owners.status()`/prepared identity checks. OS checks
the consumed initialization receipt itself, derives current boot/candidate/
context/invocation itself, and binds all public identifiers to its own journal.
The authenticated main similarly validates the real initial-certificate
publication journal and same UUID/key/SPKI, then supplies only public publication
metadata. That delegation is explicit and subject to root review, not a boolean
claim or an invented OS certificate verification.

The root-only journal lives in `/var/lib/inkyos/system-setup` (0700, files0600).
Neither inky nor inky-network can write completion. Persistent admission slots,
child ownership and drains follow the existing shared-writer model. RESET/EOF
closes future session admission. A running syscall/process/thread is always
owned to completion and reaped, even beyond the 45-second *admission* budget.
No timeout licenses releasing SH while an effect is unknown.

Clock challenges use real OS randomness and CLOCK_BOOTTIME (TTL strictly30s).
The existing numeric `time-policy.py` is pinned by hash in the JSON. The setter
really calls clock_settime_ns(CLOCK_REALTIME), surrounds its effect and readback
with BOOTTIME observations, and checks the entire error interval within ±2s.
Those facts prove the setter/readback policy, not independent UTC; the timestamp
is an authenticated owner's assertion. Each sub-effect rechecks admission.

Country is supplied explicitly by the app, never inferred from flash locale.
Only standard `iw reg set CC` is permitted, followed by actual WLAN/PHY mapping,
firmware GET country/ccode/revision, global kernel country and bounded channel
observations. PHY labels98/99 are not firmware country. A country the pinned
native policy cannot establish remains refused, with WLAN closed. No TEST
receipt, key, capsule, module or grant is an active dependency.

## Every-boot RF closure before NetworkManager

A new `inkyos-wlan-close.service` must close only WLAN before NetworkManager;
NM receives an explicit Requires/After dependency so gate failure prevents its
startup. The gate writes WirelessEnabled=false durably, soft-blocks WLAN via the
real rfkill device and reads back the actual target. It preserves profiles,
identity, photos and Bluetooth. Its current-boot/candidate observation is stored
under `/run/inkyos-wlan-gate`, separate from factory Ready and user completion.

A simple Before=NetworkManager or After=systemd-rfkill ordering is insufficient:
systemd-rfkill restores state on later ADD events as well. Proposed explicit
profile policy: mask **both** systemd-rfkill.service and .socket before boot;
the gate checks masked/inactive/noMainPID. This disables their automatic
restoration/persistence; it does not issue rfkill ALL or block Bluetooth.
Source reference: [rfkill load_state/ADD handling](https://raw.githubusercontent.com/systemd/systemd/v257.13/src/rfkill/rfkill.c).
BLE availability is separately observed, never inferred from these masks. If
root requires retaining automatic rfkill restoration, a real selective WLAN
mechanism must replace this policy before implementation; no invented env/udev
toggle is accepted.

Before reopening WLAN on initial setup or resume, require the boot gate plus
fresh country observations and a closed profile inventory. The latest genuine
committed helper transaction is verified independently against the actual NM
persistent profile metadata; original profile UUID is historical audit only. A failure after
activation drains the admitted effects, requests NM WirelessEnabled=false,
soft-blocks WLAN and reads both back. Unconfirmed closure is uncertainty and
retains owned work/admission; it never becomes network readiness.

## Recovery, completion and ordinary reboot

`setup.inspect(workflow)` is readonly under a fresh admitted-main connection,
without phone/old session. It rediscovers latest op and completion after lost
replies. `not_started` does not authorize creation. Same operation/request hash
returns durable state; changed arguments conflict. A recovered pending operation
is uncertain and is never blindly repeated. Explicit owner recovery uses a new
op, fresh challenge and supersedes pointer only after prior effects drain and
native WLAN closure is verified. Tombstones remain bounded/persistent.

Initial normal-certificate publication requires a live same-boot/session apply
receipt. Historical status must never manufacture ClockResult or regenerate a
certificate. The sole data-only exception is finishing already durable identical
certificate candidate bytes/intent under an explicitly verified recovery path.
After a legitimate normal certificate exists, missing Wi-Fi/completion selects
CONTINUATION_NORMAL, never factory QR/welcome.

`setup.complete` requires an actual admitted helper `inspect_committed` reply,
plus independent NM profile/UUID/interface state checks. Helper-owned journal
bytes alone cannot create root completion. Initial publication operation/UUID/
SPKI are bound permanently, separately from the latest setup-effect operation.
The IDs may differ after an explicitly drained/superseded recovery on a later
boot. The original leaf SHA is historical, not an immutable current certificate
pin; an already published normal certificate is never recreated for that recovery. A legitimate later certificate with the same identity
is accepted, and no renewal uses an unattested reboot clock.

Ordinary `setup.resume` needs no phone or still-active owner: original owner and
epoch are historical consent, not a new mutating owner grant. It reads root
completion, uses fresh boot admission/gate, then reapplies/readbacks country and
radio before network. It never replays old UTC or claims a new clock proof.
A normal authenticated owner may change Wi-Fi later. To keep that path working,
resume asks the new setup-only `inspect_latest_committed` RPC, requires a present
validated journal with no pending/uncertain transaction, and verifies its latest
committed record against real NM profile UUID/id/interface. The helper's existing
record update order determines latest; no new helper datastore is invented.
OS then updates a separate root-owned network-head revision atomically. The
initial completion/identity/publication remain immutable; the initial profile
is audit history, not an eternal restriction.

The helper's existing HMAC protects the original begin intent for retries, not
the whole journal record. The design does not call it a signed journal.
“Authentic” here means strict response from the actually attested pinned helper
process plus independent current NM checks, never a raw writable file or a
main-supplied boolean. If journal is absent/pending/uncertain or profile metadata
conflicts, keep NORMAL_RECOVERY with WLAN closed, without fallback to the first
profile. BLE/normal pinned identity permits explicit owner reconfiguration;
factory/QR is never reopened. A disconnected committed profile may return no IP
and no active connection: inspect discovers its target before reconnection,
and network readiness requires an actual later current IP.

## Explicit HTTPS origin

The existing firstboot code already persists an entropy-based unique
`inky-<32hex>` hostname in root-owned `/var/lib/inkyos/system.json`, reconciles
`/etc/hostname`, and sets the runtime name before network services. No new
hostname privilege or SYS_ADMIN is needed. This alone is not mDNS proof.

The proposed OS status getter observes actual Avahi DBus name/state and current
interface/NM evidence, compares it with that preserved root state, and emits the
explicit `https://inky-<persisted32hex>.local:8443` only when justified. Otherwise
`status.live.https_origin=null`. The backend never constructs it from Host,
SAN, IP or socket.gethostname. This observation can become available while the
Wi-Fi transaction awaits confirmation, before setup.complete. Native interface/
announcement evidence remains an implementation/bench requirement.

## Native files/functions still missing

- New pinned setter and close-only WLAN gate scripts plus their two units.
- New root persistent/runtime parents and the early NM dependency/rfkill masks.
- Explicit setup writer role/launch argv and expanded mandatory unit/support/ELF
  inventories, with no rights change to the existing initialization IPC.
- Native reciprocal setup/network peer guards extending writer-graph, source
  checks and owned drains; no generic root peer admission.
- factory-main injection of the real OS adapter and reviewed continuation.
- Backend-only helper inspect_committed and its exact authorized setup peer.
- Backend certificate/owner-authorized continuation and startup selection.

No image profile is executed or represented as ready until this complete native
closure and the matching Studio continuation pass their real relevant checks.

## Frozen helper inspection details

Two closed requests exist: `inspect_committed` with exactly `op,id,owner_id`,
and `inspect_latest_committed` with exactly `op` (no caller-selected transaction).
Success is exactly `{ok:true,result:NetworkObservation}`. Errors are closed: no
committed record → `not_found`; any pending/nonfinal transaction → `busy`;
invalid/partial/uncertain journal or inconsistent/unavailable NM evidence →
`not_ready`; peer/grammar errors → `permission_denied`/`invalid_request`. None
selects a fallback profile or authorizes initialization.

`boot_id`/`nm_unique_owner` always describe the **current observation**. Separate
`commit_boot_id`/`commit_nm_unique_owner` describe the historical committed
journal instance. Empty IPv4 means disconnected, never current network readiness.

`observation_sha256` hashes the exact canonical returned observation excluding
that field itself (ASCII sorted compact JSON plus LF). OS recomputes it and stores
it as `NetworkHead.source_observation_sha256`. It is neither a signature nor a
hash of a secret/key or uninspected journal.

The backend wire apply ACK is a prompt RAM acknowledgment while its real owned
IPC task continues; only a durable OS receipt establishes effects_completed.
Negotiation may discover a nullable latest operation via readonly inspect. A
null HTTPS origin means wait_origin and readonly polling, never confirm/PHOTO.
