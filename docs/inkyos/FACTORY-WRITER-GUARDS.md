# Installed factory writer guards

This lot follows the inactive bootstrap candidate in PR #29. It does not enable
Bluetooth bootstrap, publish normal identity, change the Wi-Fi protocol, install
an OS image or replace the physical TEST payload.

The `a071f19` bundle and its 2.3.0 dependency closure below are immutable
historical artifacts. The later [2.5.0 driver candidate](DISPLAY-DRIVER-250.md)
does not rewrite their manifest or qualify a new installed graph. A new closure
and bundle must be reviewed separately; do not package new sources with the old
Inky wheel.

## Installed boundary

Presence of `INKY_STUDIO_FACTORY_REQUIRED`, any `INKYOS_WRITER_*` variable,
the Studio factory marker, the OS runtime manifest or the factory context file
or directory selects the factory boundary. Empty, partial or unreadable signals
cannot select legacy. Durable Studio traces also remain a refusal boundary in
the selector and maintenance guards.

Main and the system-Python network helper read the fixed root-owned manifest
and runtime module through anchored directory descriptors. They refuse links,
writable ancestors, unexpected ownership/modes, xattrs, duplicate JSON keys and
module pin mismatches before executing that module. The helper cannot import
the application venv, so these two small trust loaders are intentionally local
to each entry point. Lease and inherited-FD policy are shared in the OS API:

```python
with runtime.writer_guard("main") as lease:
    lease.check()
    # Own and drain admitted work before leaving this scope.
```

The closed roles are `main`, `helper`, `ipc`. The OS primitive acquires its own
SH lease, validates Ready, context and installed role, and strictly checks any
inherited FD/role/context triplet before closing the inherited FD without
`LOCK_UN`. Its fixture overrides cannot select the production root.

Main retains one lease through nested startup entries. Direct ASGI lifespan
calls always check the selector, including callers using the old private
`_legacy_selected=True` keyword. Reused async contexts check the live lease and
unchanged factory environment before yielding. The factory initializer remains
`NoReturn`: it still ends with `factory_runtime_pending` (78), rather than
falling back to the normal DB, driver or listeners.

## Maintenance and installed frontend

`start`, `stop`, `restart`, `welcome`, `reset-password` and `update` CLI actions
check legacy eligibility before touching the service. Password commands keep
their Python guard. The updater checks before its lock, temp tree, discovery,
download, pip invocation or restart; its CLI checks before release discovery.
Maintenance never imports OS authority or borrows the `main` role.

Factory frontend resolution is fixed at `/usr/lib/inky-studio/client/dist`.
An absent bundle remains absent; a source checkout or a `site-packages/client`
decoy cannot provide fallback bytes. Legacy source/editable layout is retained.
The wheel test actually builds a wheel and installs it offline in a temporary
venv, then imports only the path resolver with isolated Python. It verifies
non-editable contents, entry point, metadata without a personal email and the
existing runtime dependencies, including `inky==2.3.0`.

## Qualification limits

Local validation of this lot passed 1,189 backend tests on Python 3.13.15,
including the real wheel installation. One subsequent regression for a partial
D-Bus constructor passed separately; the helper suite now has 70 new cases.
The existing
HTTP/WebSocket password migration probe, Ruff, ShellCheck and diff whitespace
checks also passed. An independent review replayed the selector bypass,
nested-environment, asynchronous restoration and partial-constructor cases;
all confirmed findings were corrected before publication.

The startup tests use a real flock and blocked startup threads under a synthetic
OS adapter. They prove the Studio scope retains its lease through repeated
cancellation. OS identity, ownership, NSS, context, Ready and inherited-FD
validation require the separately published OS primitive tests.

Normal TLS identity and driver initialization remain part of the legacy core,
which factory startup cannot reach. These guards do not qualify those operations
as a future active factory lifecycle. Bootstrap activation must retain its own
drain envelope and be validated with the installed graph.

The helper stops admitting requests on TERM/INT and retains both writer locks
through startup recovery and shutdown. A NetworkManager method returning is not
a completion proof. Factory shutdown cancels pending transactions, preserves a
durably committed profile, and observes the expected stable connection, removal
of the temporary profile/checkpoint and completion of an admitted scan through
`LastScan`. Uncertain state is retried without a deadline that releases SH.
These are synthetic adapter and lock tests, not a real-radio qualification.
The installed supervisor must also preserve this drain policy; forced process
termination and the complete privileged wrapper graph remain an OS gate.

NetworkManager contracts used for the shutdown observations:

- [Manager and activation API](https://networkmanager.dev/docs/api/latest/gdbus-org.freedesktop.NetworkManager.html)
- [Device state API](https://networkmanager.dev/docs/api/latest/gdbus-org.freedesktop.NetworkManager.Device.html)
- [Wireless scan completion API](https://networkmanager.dev/docs/api/latest/gdbus-org.freedesktop.NetworkManager.Device.Wireless.html)

An installed application wheel, a complete pinned system support inventory and
qualified privileged wrappers are still separate gates. Neither these tests nor
GitHub CI prove BlueZ, iPhone permissions, NetworkManager on the real Pi, SPI,
e-ink output, reboot recovery or the complete first-use flow.
