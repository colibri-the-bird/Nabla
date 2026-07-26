# Core Runtime Portability Spike

| Field | Value |
|---|---|
| Task | `SPIKE-CORE-PORTABILITY-001` |
| Artifact | `CORE-PORTABILITY-SPIKE-v1` |
| Report status | Measurements complete — owner approval pending |
| Candidate under measurement | Rust |
| Prepared context manifest | `05e2d865ce91ed1e0b73da2a1cb8d6eb74bb968179772081e7b197bc488a6079` |
| Raw result | `tests/spikes/core-portability/results/windows-x86_64.json` |
| Raw result SHA-256 | `58ac966c3ceba16e06743f58daf09fda992fbba164d7304fe7c6dba8871c10ec` |

## 1. Purpose and decision boundary

This spike measures whether a minimal candidate Core boundary can be reproduced
with Rust across the exact host and target shapes exercised by the checked-in
experiment.

Rust is only the candidate under measurement. This report does not select the
final Core Runtime language, runtime architecture, IPC mechanism, FFI surface,
packaging system, or production process model. Those decisions remain inputs to
ADR-001 and the other applicable ADRs.

The experiment is disposable and synthetic. It creates neither production
application code nor production data. Its fixture DDL exists only to observe
transaction and recovery behavior; it is not Nabla's production schema and
cannot freeze production DDL or a public contract.

## 2. Scope and harness shape

The experiment measures:

1. a Desktop Core Service-shaped child process;
2. an Embedded Core-shaped host loading a real C ABI;
3. SQLite commit, rollback, reopen, integrity, writer contention, and abrupt
   process recovery;
4. bounded NDJSON and FFI adapter behavior;
5. host packaging and native dependency observations;
6. Android arm64 cross-build feasibility;
7. non-interactive tooling and cleanup.

The recorded Python callers do not open the fixture databases. They pass a path
to the Rust Core and use only the process or C ABI adapter. This separation is a
property of the harness construction, not an OS access-control or security
boundary: the caller still runs with the same filesystem identity and could
open the file outside this experiment.

The process transport is bounded NDJSON over child stdin/stdout. It is a probe
transport only. It does not prove OS-native IPC, peer credentials,
install-scoped authentication, confidentiality, authorization, or a production
lifecycle design.

The fatal `crash_probe` operation is recognized only by the disposable process
adapter. It is deliberately absent from the shared Core/FFI request contract.

## 3. Reproducibility record

### 3.1 Environment

| Property | Observed value | Raw evidence |
|---|---|---|
| Run interval (UTC) | `2026-07-26T20:03:38.653417Z` to `2026-07-26T20:05:30.016060Z` | `/started_at_utc`, `/completed_at_utc` |
| Host | Windows 11-compatible kernel `10.0.22631`, build `22631.6199`, x86-64 | `/environment/host` |
| Rust compiler | `rustc 1.96.0`, host `x86_64-pc-windows-msvc`, LLVM `22.1.2` | `/environment/rust/rustc` |
| Cargo | `cargo 1.96.0` | `/environment/rust/cargo` |
| Python harness | CPython `3.12.7`, 64-bit AMD64 | `/environment/python` |
| Rust probe SQLite | bundled SQLite `3.46.0`, WAL, `synchronous=FULL`, busy timeout `250 ms` | `/cases/DESKTOP-001/initial/responses/0` and probe source |
| Python SQLite | `3.45.3`; environment observation only, not the Core database engine | `/environment/python/sqlite_version` |
| Android build tools | `cargo-ndk 4.1.2`, NDK `27.2.12479018`, target `aarch64-linux-android`, API `21` | `/environment/android`, `/environment/rust`, `/cases/ANDROID-BUILD-001` |
| Native inspection | GNU `objdump`; completed for host service, host DLL, and Android `.so` | `/cases/PACKAGE-001/dynamic_dependencies`, `/cases/ANDROID-BUILD-001/dynamic_dependencies` |

Host naming follows the raw OS APIs. The registry exposes the legacy product
label `Windows 10 Pro`, while version `10.0.22631`, display version `23H2`, and
build `22631.6199` identify the measured Windows 11 generation.

### 3.2 Canonical invocation

From the repository root:

```text
python tests/spikes/core-portability/run_experiment.py --offline --output tests/spikes/core-portability/results/windows-x86_64.json
```

| Item | Recorded value |
|---|---|
| Preconditions | CPython 3.12, Rust/Cargo 1.96, locked Cargo dependencies already cached; Android build additionally requires the recorded target, cargo-ndk, and NDK |
| Network access | No; every Cargo command used `--offline`, and runtime probes open no network listener |
| Input fixture | Fixed synthetic JSON requests and ephemeral spike-only SQLite databases |
| Build configuration | `CARGO_INCREMENTAL=0`, `CARGO_TERM_COLOR=never`, temporary `CARGO_TARGET_DIR` |
| Overall exit code | `0` |
| Raw stdout/stderr | Embedded per command and runtime case in the structured result with byte count, full SHA-256, bounded preview/text, and capture-completeness flags |
| Structured result | `tests/spikes/core-portability/results/windows-x86_64.json` |
| Structured result size | `1,151,628` bytes |
| Structured result SHA-256 | `58ac966c3ceba16e06743f58daf09fda992fbba164d7304fe7c6dba8871c10ec` |
| Cleanup | Passed; the temporary work root, build products, databases, and possible crash dump were absent after runner exit |

The runner uses direct argv execution without a shell, finite build/runtime
timeouts, a 1 MiB stdin limit, a 256 KiB retained preview limit per stream, and
a 4 MiB structured-result limit. Full captured streams are hashed even when
their retained preview is truncated. A required assertion failure writes the
JSON result and returns a non-zero exit code.

## 4. Measurements

Every exact child argv, cwd, exit code, duration, stdout/stderr byte count and
hash is stored under the referenced JSON object.

| Case | Dimension | Platform/target | Result | Raw evidence |
|---|---|---|---|---|
| `TOOL-001` | Non-interactive self-test, format, locked test/build, metadata, dependency tree | Windows x86-64 | `OBSERVED` | `/commands`, `/cases/TOOL-001` |
| `DESKTOP-001` | Separate Core-shaped service, restart, idempotent replay | Windows x86-64 | `OBSERVED` | `/cases/DESKTOP-001` |
| `EMBED-001` | Python host loading actual Rust C ABI with `ctypes` | Windows x86-64 | `OBSERVED` host shape; not mobile runtime | `/cases/EMBED-001`, `/cases/FFI-001` |
| `SQLITE-001` | Commit/reopen, four injected rollback stages, integrity | bundled SQLite `3.46.0` on Windows | `OBSERVED` | `/cases/SQLITE-001`, `/assertions` |
| `FAILURE-001` | Contained panic plus abort inside an open transaction and restart | Windows x86-64 | `OBSERVED` | `/cases/FAILURE-001` |
| `IPC-001` | Bounded NDJSON over child stdin/stdout | Windows x86-64 | `OBSERVED` probe transport | `/cases/IPC-001`, `/cases/DESKTOP-001` |
| `FFI-001` | Actual two-pass C ABI, finite request limit, serialized pending response, panic recovery | Windows x86-64 PE DLL | `OBSERVED` | `/cases/FFI-001` |
| `PACKAGE-001` | Release artifacts, hashes, binary formats, exports/imports, Cargo graph | `x86_64-pc-windows-msvc` | `OBSERVED` | `/cases/PACKAGE-001`, `/commands/cargo_metadata`, `/commands/cargo_tree` |
| `ANDROID-BUILD-001` | Locked offline `cargo-ndk` release build | `aarch64-linux-android`, API 21 | `BUILD-ONLY` | `/cases/ANDROID-BUILD-001` |

### 4.1 Produced artifact inventory

The build products were fingerprinted before the temporary directory was
removed:

| Artifact | Format/target | Size | SHA-256 |
|---|---|---:|---|
| `nabla-core-probe-service.exe` | PE x86-64 | 2,012,160 | `96c32abfd669426d0a674115f56014b1eaf8c322609393a8bb7af297d5426893` |
| `nabla_core_portability_probe.dll` | PE x86-64 | 1,958,912 | `2c3ac2e2fe415e6ac49f939bb396194708158f86f2c150e40a810f3f829180b5` |
| `libnabla_core_portability_probe.so` | ELF aarch64, Android API 21 build | 2,748,600 | `8a211e7f0f3cd9babd53ff728abe6bb53bc82bff21e1d15e395ae18bb7b4a85f` |

`objdump` completed for all three artifacts. The host DLL exports the five
expected `nabla_core_probe_*` symbols. Host native imports are recorded in the
bounded raw observation; no external `sqlite3.dll` is present because this
probe builds bundled SQLite. That observation does not prove installer
completeness or support on another Windows installation.

### 4.2 Transaction and failure observations

- A synthetic command committed one row in each of `facts`, `idempotency`,
  `audit`, and `outbox`; restart reported counts `1/1/1/1` and
  `integrity: "ok"`.
- Failure injected after each of `fact`, `idempotency`, `audit`, and `outbox`
  left counts `0/0/0/0`, including after reopen.
- The process-only crash probe committed a baseline command, aborted after the
  second command's outbox insert but before commit, and exited with Windows code
  `3221226505`. Restart retained only the baseline `1/1/1/1`, reported integrity
  `ok`, and accepted the formerly interrupted request as a new command.
- FFI `panic_probe` returned status `7`; the same handle subsequently completed
  `integrity` successfully. This proves only the measured unwind-enabled Rust
  panic path. It does not cover `panic=abort`, OOM, native faults, or the
  service-only abort hook.
- A request deadline is checked before writer admission, after waiting for the
  writer lock, and before commit. The locked test verified that a request whose
  deadline elapsed while waiting did not commit.
- Inspect counts were read while the harness had one idle logical writer. They
  are not evidence of an atomic diagnostic snapshot under concurrent writers.

## 5. Assertion results

All 18 required assertions in `/assertions` passed.

| Assertion | Evidence-backed result |
|---|---|
| Shared command meaning | Full typed `inspect`, `apply`, `replay`, post-state, and `integrity` responses matched between process and FFI adapters |
| Recorded caller storage behavior | Both recorded callers used only their adapter; no access-control boundary is claimed |
| Durable commit | Committed state survived close/restart with counts `1/1/1/1` and integrity `ok` |
| Atomic injected rollback | All four pre-commit stages left no partial row before or after reopen |
| Abrupt process recovery | Abort during the open transaction left the prior commit intact, removed the in-flight mutation, and allowed restart/retry |
| Actual host FFI | The release DLL was dynamically loaded and exercised through its exported C ABI |
| Finite FFI sizing | Oversized request is rejected before slice/allocation; one pending response per handle prevents unbounded interleaving |
| Host packaging | Service and DLL existed, were fingerprinted, and completed native dependency inspection |
| Android packaging | arm64 API 21 `.so` compiled offline; classification remains `BUILD-ONLY` |
| Non-interactive execution | All commands completed with full capture, no shell, bounded output, machine-readable result, and successful cleanup |

The harness-level timeout bounds the experiment. `PRAGMA integrity_check` and
an individual service request do not yet expose a production cancellation
primitive; this remains an ADR/runtime input rather than a solved production
property.

## 6. Measured support boundary

| Boundary | Classification | Permitted conclusion |
|---|---|---|
| Desktop process-shaped Core on Windows x86-64 | `OBSERVED` | The measured Rust candidate can run as a separate local child service with the tested synthetic contract |
| Embedded shape on Windows x86-64 | `OBSERVED` | The measured Rust DLL can be hosted through the tested C ABI |
| SQLite transaction/recovery on Windows x86-64 | `OBSERVED` | The synthetic bundled-SQLite fixture showed the recorded commit, rollback, reopen, and crash behavior |
| NDJSON stdio on Windows x86-64 | `OBSERVED` | The bounded probe transport worked; no production IPC or security conclusion follows |
| Windows release artifacts | `OBSERVED` | The exact recorded PE artifacts were produced and inspected |
| Android arm64 API 21 artifact | `BUILD-ONLY` | The same library source cross-compiled to the exact recorded target |
| Android runtime on device/emulator | `NOT TESTED` | No mobile runtime, application host, JNI integration, or on-device SQLite behavior is proven |
| Other desktop/mobile platforms | `NOT TESTED` | No support claim is permitted |
| Non-interactive agent/tooling on the measured host | `OBSERVED` | The canonical offline command produced a passing bounded result and removed its temporary state |

## 7. Conclusions supported by measurements

1. Rust remains a viable candidate input to ADR-001 for a Windows x86-64 Core
   boundary: the same synthetic typed semantics were observed through a
   separate process and a dynamically loaded C ABI.
2. Bundled SQLite `3.46.0` provided the measured single-writer transaction,
   rollback, reopen, integrity, and abrupt-process recovery behavior for the
   disposable fixture.
3. The candidate source produced an Android aarch64 API 21 shared library with
   the recorded locked offline toolchain. This is compile evidence only.
4. The experiment is usable by non-interactive tooling on the measured host
   with finite subprocess/output limits, path sanitization, deterministic
   source/artifact inventory, non-zero failure behavior, and verified cleanup.

These conclusions do not select Rust or any adapter as the final architecture.

## 8. Negative and inconclusive results

- Android runtime, JNI/application integration, and a real Mobile Embedded Core
  were not tested.
- iOS, macOS, Linux, Windows ARM64, and other host/target combinations were not
  tested.
- The C ABI header was exercised indirectly through `ctypes`; compiling a
  native C/C++ consumer and establishing ABI compatibility across toolchain
  upgrades remain untested.
- ABI version `1` is a probe constant, not a stability guarantee.
- The host panic result covers a controlled Rust unwind only.
- The probe did not create an installer, sign artifacts, test upgrade/remove,
  or validate store distribution.
- No OS-native IPC, authentication, authorization, peer identity, cancellation
  contract, or production Core lifecycle was measured.
- The fixture does not measure production schema, migration, load, backup,
  privacy, or long-duration reliability.
- The harness detects incomplete stream capture and fails the run, but it is not
  a production process supervisor or a proof for arbitrary descendant-process
  behavior.

## 9. ADR-001 inputs

| ADR input | Measurement basis | Input carried forward |
|---|---|---|
| Candidate language/runtime feasibility | Windows process + DLL runtime; Android arm64 build | Rust is viable for further decision work on the measured boundaries, not yet selected |
| Desktop process model | Separate bounded child service, restart, crash recovery | A process boundary is feasible; production local IPC and lifecycle remain open |
| Embedded/mobile feasibility | Windows ctypes host observed; Android `.so` build-only | FFI is feasible on the host and cross-compiles; real mobile integration is still required |
| IPC/FFI constraints | NDJSON probe and serialized two-pass ABI | Choose/version a production transport; specify ownership, auth, cancellation, buffer and concurrency rules |
| SQLite ownership/transactions | Single harness writer, WAL/FULL, four rollback stages, abort/reopen | Preserve Core-owned writes and transactional failure tests; do not reuse fixture DDL |
| Packaging | Exact PE/ELF artifacts and native imports | Decide runtime linkage, installer/signing, target matrix, and upgrade policy |
| Tooling | Locked offline build, bounded runner, temp cleanup | Pin supported toolchains and reproduce the matrix in CI before a support claim |
| Failure modes | Controlled unwind, lock deadline, injected rollback, process abort | Distinguish recoverable handler errors, embedding-host failures, and process failures in ADR/release gates |

ADR-001 must still decide:

- the final runtime and supported target matrix;
- Desktop service lifecycle and production local IPC;
- embedded/mobile host and binding strategy;
- ABI/versioning and concurrency ownership;
- SQLite linkage/update policy;
- packaging, signing, installer, upgrade, and rollback;
- production cancellation, resource, and crash diagnostics behavior.

## 10. Unresolved risks and required follow-up

| Risk | Why this experiment does not resolve it | Required follow-up |
|---|---|---|
| Real mobile runtime | Android evidence is build-only | Run the embedded library in a representative Android application/device or emulator with SQLite and lifecycle tests |
| Production IPC security/lifecycle | NDJSON stdio is only a probe | Resolve ADR-010 and test the selected authenticated local transport |
| Stable FFI/ABI | One host/toolchain and ctypes caller were measured | Compile native consumers, define ABI ownership/version rules, and test supported toolchain/target combinations |
| Panic/native fault coverage | Only a controlled unwind and process abort were measured | Define release panic policy and add OOM/native-fault/process-supervision tests where support is claimed |
| Distribution packaging | Raw artifacts are not a product package | Build/sign/install/upgrade/uninstall on every supported platform |
| Production persistence | Fixture DDL and idle inspect are deliberately narrow | Adopt approved DDL/migration decisions and run production transaction, backup, restore, load, and corruption suites |
| Request cancellation | Harness timeout is not Core cancellation | Define and implement cancellation/deadline behavior for long integrity and application operations |
| Platform matrix | Only Windows runtime and Android build were observed | Add CI/runtime evidence for every platform ADR-001 proposes to support |

## 11. Evidence index

| Evidence item | Path/reference | SHA-256 or immutable reference |
|---|---|---|
| Structured raw result and embedded raw stdout/stderr | `tests/spikes/core-portability/results/windows-x86_64.json` | `58ac966c3ceba16e06743f58daf09fda992fbba164d7304fe7c6dba8871c10ec` |
| Experiment source inventory | Raw result `/source_inventory` | Each file has an individual SHA-256 in the raw result |
| Host service artifact | Raw result `/cases/PACKAGE-001/artifacts/0` | `96c32abfd669426d0a674115f56014b1eaf8c322609393a8bb7af297d5426893` |
| Host C ABI artifact | Raw result `/cases/PACKAGE-001/artifacts/1` | `2c3ac2e2fe415e6ac49f939bb396194708158f86f2c150e40a810f3f829180b5` |
| Android build-only artifact | Raw result `/cases/ANDROID-BUILD-001/artifacts/0` | `8a211e7f0f3cd9babd53ff728abe6bb53bc82bff21e1d15e395ae18bb7b4a85f` |
| Prepared context | `.nabla/context/SPIKE-CORE-PORTABILITY-001/manifest.json` (generated, not committed) | `05e2d865ce91ed1e0b73da2a1cb8d6eb74bb968179772081e7b197bc488a6079` |
| Owner approval | Pending explicit owner review of this measured report | Pending |
| Pull request | [#10](https://github.com/colibri-the-bird/Nabla/pull/10) | Published as draft |
