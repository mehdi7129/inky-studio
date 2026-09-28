# Local first-boot coordination — injected prototype

`provisioning/first_boot.py` coordinates actual prepared identity files and the
factory ownership database through a **trusted injected OS adapter**. It is not
imported by the application runtime. No socket, root authorization, clock setter,
password generation, QR display, GATT service or iOS setup flow is enabled.

## Internal boundary and sequence

```python
result = FirstBootCoordinator(
    private_dir,
    adapter=trusted_initialization_adapter,
    verify_credentials=read_and_verify_persisted_credential_epoch,
).initialize()
```

The adapter supplies the exact subobjects from InkyOS's experimental receipt
model, not a newly defined wire protocol:

- `inspect_initialization()`: `{status: authorized}` or
  `{status: consumed, intent: UUID, receipt: {receipt_id: UUID, digest: hex64}}`.
- `begin_initialization(intent)`: the same intent/receipt shape with status
  `newly_consumed` or `already_consumed`.

Only `newly_consumed` from an actual begin invocation authorizes creating the
ownership database. A readable grant file or prior inspect result cannot do so.
The future implementation must expose inspect and begin through an authenticated
root boundary; the app cannot read the root-only receipt directly. Current tests
use a fake adapter, and therefore do not qualify this privilege boundary.

Under a process-shared private workflow lock, the coordinator:

1. Inspects OS authority and validates existing private file types/permissions.
2. Verifies already-persisted credentials and their canonical current epoch.
   A missing or invalid prerequisite fails before identity preparation or begin,
   preserving unconsumed OS authority and any existing adopted state.
3. For authorized fresh state, prepares an exclusive identity or reopens the
   existing prepared identity; for consumed state, strictly reopens the same
   OS-bound intent. It never regenerates a consumed frame's missing identity.
4. Verifies any normal identity already published, then invokes begin using the
   durable intent. Unknown or mismatched results fail without retry or reset.
5. Creates a pending factory ledger only for `newly_consumed`; otherwise reopens
   an existing ledger with the same receipt and real UUID/key binding.
6. Re-verifies existing credential material through the callback, rereads the
   identity and normal-publication state, then marks factory ready. Adoption is
   terminal and is preserved on all later calls.

The callback must verify already persisted credentials and return their canonical
current epoch each time. The ownership store retains it so password rotation is
observed on later operations. The preflight epoch is not cached or frozen: a
valid epoch change during begin is accepted after the second verification.
A failure after begin remains uncertain and may leave a resumable pending ledger;
the preflight does not replace the post-begin checks.
A fake callback returning a hex string is only a
test assertion; it does not establish real password persistence. Actual initial
credential creation and ordering still require startup integration.

## Interruption and error meaning

`FirstBootRefused` means this invocation did not submit begin. It may already have
prepared local files; it does not promise zero filesystem effects.
`FirstBootUncertain` means begin was attempted: consumption and local commits may
have occurred. Neither error reflects adapter payloads or secrets. Neither retries,
cleans state, creates another intent, nor automatically reopens a QR window.

After response loss, the same intent is consulted again. `already_consumed`
requires an existing valid ownership database: consumption followed by a crash
before database creation requires explicit recovery. A retained pending database
can resume once its already-persisted identity/credentials are consistent.

A missing normal certificate is permitted only before initial publication has
completed, including an interrupted initial publication. Missing/corrupt/different
normal identity after completion fails; the coordinator never republishes it.
Certificate operation retries belong to the separate authenticated repair flow.

## Validation and remaining work

Tests use real local bundles/SQLite and fake OS authority. They exercise restart,
reply loss, invalid responses, inconsistent bindings, database/identity loss,
credential errors, revoke/last-owner state, normal-publication states and two
concurrent threads. Existing factory and certificate tests add subprocess crashes
at their persistence boundaries. These do not replace independent-process testing
of the whole coordinator, a real root adapter or physical SD power loss.

The next integration needs the privileged adapter, durable credential startup,
owner-authorized clock operation/result binding, separate bootstrap command
allowlist/channel, strict normal reconnect, country gate and the complete iPhone
flow. `FactoryStatus.factory` means the ledger is ready for an authorized initial
claim; it does not assert clock, network, normal TLS or hardware readiness.
