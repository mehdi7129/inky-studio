# Hardware display candidate for the first InkyOS LAN bench

Status: software candidate, 3 October 2026. No Raspberry, SD card, EEPROM,
GPIO, Wi-Fi profile or personal frame was changed while developing it.
This does not qualify an image, physical refresh, QR scan or iPhone Bluetooth.

## Scope and deployment contract

The source candidate is based on PR #17 (`758a2bf`), which already contains the
offline payload packaging and corrected panel metadata. It is separate from
the iOS branch and has not been released. Keep `inky==2.3.0`; no driver upgrade,
EEPROM rewrite or manual driver override is included.

Select these values in the **dedicated bench's candidate service**, after its
operator/runtime safeguards are qualified, not on the personal frame:

```ini
Environment=INKY_STUDIO_DISPLAY_MODE=hardware
Environment=INKY_STUDIO_DISPLAY_PROFILE=ac073-800x480
```

`INKY_STUDIO_DISPLAY_MODE=auto` selects hardware on Linux and simulation on
other systems. Explicit `mock` never imports or accesses hardware. Invalid
mode/profile combinations are configuration errors. Linux development and CI
must select `mock` explicitly. Production hardware errors never fall back to a
simulated 800×480 display.

The profile requires the exact driver module `inky.inky_ac073tc1a`, integer
driver dimensions 800×480, library version 2.3.0 and four integer EEPROM fields:

| Raw width, height, variant, color | Candidate decision |
|---|---|
| 800, 480, 20, 5 | Normal legacy seven-color profile |
| 800, 480, 20, 4 | Explicit bench profile required; raw color remains unmapped |
| Anything else or missing/non-integer fields | Hardware unavailable; no display command |

For raw color 4, the seven-color palette comes from the driver selected by the
official `auto()` mapping for variant 20. It is **not** an interpretation of
color 4, physical SKU proof or authorization to rewrite it to 5. Omission of
the explicit profile does not allow this exception. Other panel sizes/revisions
do not gate this first bench, and are not newly qualified by it.

## Failure and diagnostic behavior

Initialization failures keep the service and authenticated diagnostic API alive.
No fictitious dimensions are returned. `/api/state`, `/api/display`, uploads,
next and previous return HTTP **503**, including when the queue is empty.
`/api/health` describes the service only; it cannot certify the panel.

`/api/display/status` requires normal authentication and remains readable while
the SPI owner is busy. It contains the selected mode/profile, state, safe error
code/message, driver metadata, raw variant/color, observed dependency versions,
monitor coverage and busy observations. No serial number, identity, credential,
filesystem path or exception traceback is returned. Observations are cleared
at the beginning of a new operation and published after the driver returns;
an empty list while busy must not be mistaken for a successful operation.

| Code | Meaning |
|---|---|
| `display_unavailable` | Hardware initialization/profile/driver unavailable |
| `display_refresh_failed` | Image preparation, GPIO/SPI or driver raised |
| `display_busy_timeout` | Original GPIO edge wait returned false |
| `display_busy_unverified` | Critical refresh completion could not be observed |

Failures remain latched until an operator checks the bench and restarts the
service. There is no automatic retry and no new successful history entry or
queue consumption for the failed operation. A `display_error` event contains
only `code` and a French `detail`; no `display_changed` success is emitted.
The web uses its existing Bento alert. Current iOS error handling can present
the detail, but the newer QR/Bluetooth build still needs actual distribution.

## AC073 busy observation, without changing the driver sequence

Only the pinned AC073 2.3.0 driver is instrumented. A temporary **instance**
wrapper calls the original `_busy_wait`; a transparent GPIO proxy records its
existing return values. It performs no extra GPIO read, wait, event drain,
sleep or command. No warning filter or class/module method is changed.
The wrapper and proxy are restored on success and on exceptions.

All four upstream phases remain in order: reset/setup (1 s), power-on (0.4 s),
refresh (45 s), power-off (0.4 s). Those arguments are not an end-to-end latency
bound. A reported timeout is raised at the application boundary **after** the
original `show()` returns, preserving POF and its final wait. No thread is
cancelled and the existing display lock is held through the whole operation.

An initially high pin is recorded as `held_high_unverified`, not mislabeled as
an edge timeout. That observation on the critical refresh phase blocks success;
it can conservatively reject a physically successful refresh and must be
qualified on the bench. Short-phase held-high observations remain diagnostic.
An empty event read remains unverified. Even a received edge does not prove
its freshness, the physical panel identity or the pixels actually displayed.
Other driver families report `not_monitored`; do not extend the AC073 timeout
claim to them.

The underlying driver still decides when to power off after its wait. This
patch prevents false application acknowledgement; it does not prove electrical
safety or that the panel is ready after a timeout.

## Stop, dependency and physical qualification boundaries

### Service drain contract

The installer emits this policy for the application service:

```ini
[Service]
KillSignal=SIGTERM
KillMode=mixed
TimeoutStopSec=infinity
SendSIGKILL=no
```

The main process owns graceful shutdown. Systemd sends it SIGTERM and waits;
the service does not impose an arbitrary stop deadline or a final SIGKILL.
These settings must also be applied and verified in the InkyOS application
unit before qualifying active-service stop. Copying application files or using
the existing online updater does **not** update an already installed unit.
The Bluetooth installer already orders Studio after `inky-network.service`,
so normal ordered shutdown keeps that helper available for cancellation.

At the first SIGTERM/SIGINT, the process asks both HTTP listeners to stop
accepting requests and closes display admission without waiting for SPI. An
operation that already owns the lock finishes its original driver call and its
queue/history commit.
Queued and new display operations are rejected; they cannot start a second
refresh during drain. Repeated signals request the same drain, rather than
force-exiting. The single-process owner ignores `WEB_CONCURRENCY`; launching
multiple independent Studio services on the same SPI device remains invalid.

Uvicorn no longer cancels in-flight requests after ten seconds. Idle WebSockets
are closed by its normal shutdown. Scheduler, welcome and provisioning workers
are drained before releasing the driver, with lock waiting off the event loop.
Shutdown does not initiate a new QR-restoration refresh; adoption is closed and
its persisted recovery marker is retained for the next authorized startup.

An indefinitely blocked driver or admitted HTTP request can therefore keep the
unit **deactivating** indefinitely. An operator UI timeout must report that work
continues; it must
not report `inactive`, issue a forced kill, begin another hardware owner or
power off the host. This policy covers a normal service stop/restart, not forced
host shutdown, power loss, OOM, an external kill or electrical safety. Even a
normal reboot/poweroff must be preceded by a completed service drain and a
verified `inactive/dead` state; a host watchdog or global shutdown/job timeout
is outside this unit's contract. No overall physical refresh/stop duration is
certified here. InkyOS still owns Linux-unit integration and real-panel stop
qualification.

### Startup is a hardware action

A hardware-mode start can display the welcome screen on a fresh frame or
restore a persisted adoption image. Treat startup as explicit authorization
to refresh after the bench gates; it is **not** passive diagnostic observation.
`/api/display/status` itself does not refresh the panel. No separate diagnostic
startup mode is introduced by this candidate.

Freeze and record the full payload and dependency versions, including `inky`,
`gpiod`, `gpiodevice`, `spidev`, Pillow and Python. The Inky pin alone does not
freeze its transitive GPIO dependencies. Update image whitelists/preflight only
against a reviewed candidate; do not replace a wheel ad hoc on the SD card.

Before calling the first LAN bench qualified: verify the raw tuple without
rewriting it; verify authenticated diagnostics; then run authorized repeated
refreshes with one image, distinguish request/driver/visible-panel results,
measure each phase and total time, check queue/history, observe held-high and
fault behavior, and prove safe service stop. Keep operator access independent
of the app. A build 3 iPhone can test ordinary photo use on an already configured
LAN; it cannot qualify QR/BLE. No additional simulator is required here.

## Reproducible software checks and primary references

`server/tests/test_display_hardware.py` exercises mode/profile guards, unavailable
hardware, 503 responses, authenticated diagnostics, latched failures, unchanged
queue/history and display serialization. `server/tests/test_display_busy.py`
executes upstream busy/update method bodies with inert GPIO and compares traces
with/without the observer, including exceptions, masked warnings, empty event
reads and two independent instances. The fixture records its source and MIT
notice. These are software tests, not Raspberry qualification.

- [Pimoroni 2.3.0 autodetection](https://github.com/pimoroni/inky/blob/v2.3.0/inky/auto.py)
- [Pimoroni 2.3.0 EEPROM mapping](https://github.com/pimoroni/inky/blob/v2.3.0/inky/eeprom.py)
- [Pimoroni 2.3.0 AC073 driver](https://github.com/pimoroni/inky/blob/v2.3.0/inky/inky_ac073tc1a.py)
- [libgpiod LineRequest contract](https://libgpiod.readthedocs.io/en/v2.3/python_line_request.html)
- [systemd stop timeout](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html#TimeoutStopSec=)
- [systemd signal and kill policy](https://www.freedesktop.org/software/systemd/man/latest/systemd.kill.html)
- [Uvicorn graceful shutdown](https://uvicorn.dev/server-behavior/#graceful-process-shutdown)

The AC073 file is byte-identical in tags and PyPI sdists 2.3.0 and 2.4.0
(SHA-256 `ab31898c7c291ce1b63a4c21798860a40e3a9c2a68e57dab933f882d5ecf5582`).
The historical GPIO incident remains unresolved; attributing it to a change in
that file between those versions is not supported. This correction does not
authorize an upgrade.

## Initial candidate software validation, 3 October 2026 (`98a17a0`)

| Check | Result and boundary |
|---|---|
| Backend, Python 3.13 on macOS | 399 tests passed; one upstream TestClient deprecation warning |
| AC073 observer and integrated API cases | 23 tests passed, included in the backend total |
| Web | 48 tests, ESLint, TypeScript and Vite build passed; existing large HEIC chunk warning |
| Offline packaging | 21 tests passed |
| Backend Ruff and installer/CLI ShellCheck | Passed |
| Built server wheel | New modules matched source bytes; wheel installed into an isolated venv and mock smoke passed |
| Password migration HTTP/WebSocket using installed wheel | 29 checks passed with synthetic credentials on loopback |
| Independent targeted review | No remaining software blocker found; physical qualification still open |

These results are local software evidence. The draft PR's CI and the eventual
ARM64 payload/bench qualification are separate checkpoints. No release, merge,
SD mutation or physical display refresh was performed.

## Stop-drain follow-up validation, 3 October 2026

- Full backend suite: **411 passed** on macOS/Python 3.13, including eleven new
  lifecycle/admission/provisioning cases and the emitted-unit installer test.
- Real subprocess tests cover HTTP-only and dual HTTP/TLS listeners, an active
  refresh held beyond the old ten-second deadline, queue/history completion,
  a rejected waiter, idle WebSocket closure, repeated SIGTERM/SIGINT, early
  initialization/welcome shutdown, and a failed listener while work is active.
- Adoption shutdown closes the token, preserves the recovery marker, cancels
  the network transaction and starts no second refresh.
- Full offline producer/dependency validation suite: **80 pytest cases passed**.
- Backend and packaging Ruff, installer/CLI ShellCheck and `git diff --check`
  passed. Independent review found no remaining software blocker.
- `systemd-analyze verify` passed in the isolated Linux builder. This checks the
  emitted unit's syntax/policy with `ExecStart` substituted by `/usr/bin/true`;
  it neither installs a unit nor starts a process and is not an active-service
  stop test. The actual installed unit/drop-ins remain an InkyOS qualification
  gate.

The immutable ARM64 source/frontend/wheelhouse bundle is produced separately
from the committed follow-up. Its manifest starts with empty qualification
evidence. Candidate assembly and these software tests do not grant a release
or physical-display qualification.
