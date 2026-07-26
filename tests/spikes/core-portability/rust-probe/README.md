# Nabla Core portability Rust probe

This crate is an isolated, disposable candidate probe for
`SPIKE-CORE-PORTABILITY-001`. It is not production application code and does
not select the final Core runtime, process model, IPC transport, or mobile
packaging model.

The probe exposes one SQLite-owning command handler through two adapters:

- `nabla-core-probe-service`: a separate process using bounded NDJSON over
  stdin/stdout;
- `nabla_core_portability_probe`: a `cdylib` with the C ABI declared in
  `include/nabla_core_probe.h`.

Both adapters execute the same JSON request contract. The fixture schema is
deliberately spike-only and must not be treated as production DDL.

## Commands

From the repository root:

```powershell
cargo fmt --manifest-path tests/spikes/core-portability/rust-probe/Cargo.toml -- --check
cargo test --manifest-path tests/spikes/core-portability/rust-probe/Cargo.toml --locked
cargo build --manifest-path tests/spikes/core-portability/rust-probe/Cargo.toml --release --locked
```

Interactive separate-process example:

```powershell
'{"op":"inspect"}' |
  cargo run --quiet `
    --manifest-path tests/spikes/core-portability/rust-probe/Cargo.toml `
    --bin nabla-core-probe-service -- `
    --db "$env:TEMP\nabla-core-probe.sqlite3"
```

The service accepts one JSON object per line. A request is bounded to 64 KiB;
an oversized line is drained and rejected without terminating the service.
Example mutation:

```json
{"op":"apply","request_id":"request-1","fact_id":"fact-1","value":"example"}
```

Probe-only rollback injection accepts `after_fact`, `after_idempotency`,
`after_audit`, or `after_outbox` in `inject_failure`. `panic_probe` exists only
to verify that adapter unwind guards contain a handler panic.

The process adapter alone recognizes `op: "crash_probe"` with one of the same
stage names in `crash_after`. It aborts the disposable child inside an open
transaction so the runner can measure SQLite recovery after abrupt process
termination. This fatal operation is deliberately absent from the shared
Core/FFI request contract; sending it through the C ABI yields `INVALID_JSON`.

The SQLite busy timeout, request/value limits, response codes, FFI ABI version,
and FFI status values are constants in this probe so observations are
repeatable. They are measurements and ADR inputs, not product defaults.

The C ABI permits one outstanding buffer-sizing response per handle. After
`NABLA_CORE_PROBE_BUFFER_TOO_SMALL`, the host must retry the same request until
it succeeds; an interleaved request is rejected with
`NABLA_CORE_PROBE_INVALID_ARGUMENT`. This keeps pending response memory finite.
