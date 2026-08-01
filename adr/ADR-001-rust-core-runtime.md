# ADR-001: Rust Core Runtime, packaging, and host model

- **Status:** Proposed — owner approval required
- **Date:** 2026-08-01
- **Task:** `ADR-RUNTIME-BOUNDARY-001`
- **Decision owner:** Nabla project owner
- **Related decision:** `ADR-010`
- **Supersedes:** None

## Context

Nabla requires one portable Core semantics boundary while using different host
shapes on Desktop and Mobile. `ARCH:5` requires a separate Desktop Core Service,
an Embedded Core on Mobile, the same command meaning on every platform, and no
direct storage access from UI or CLI. `ARCH:6` assigns canonical writes to the
Core and makes SQLite the baseline local engine. `CON:I6` permits only trusted,
compile-time executable modules until a later installation-boundary decision,
and `CON:I15` requires explicit failure domains.

The owner-approved `CORE-PORTABILITY-SPIKE-v1` report in
`spikes/SPIKE-CORE-PORTABILITY.md` measured one Rust candidate on Windows
x86-64. The same synthetic typed semantics were observed through a separate
process and a dynamically loaded C ABI. Bundled SQLite commit, rollback,
reopen, writer contention, and selected abrupt-process recovery cases passed.
The source also cross-compiled to an Android arm64 API 21 shared library.

The evidence is deliberately narrow. Android execution, JNI/application
integration, other operating systems and architectures, installers, signing,
upgrade/rollback, stable ABI compatibility, production cancellation, load, and
production DDL were not measured. The probe's NDJSON transport and fixture
schema are not production contracts.

ADR-001 decides the runtime and packaging boundary. ADR-010 decides the
Desktop local transport, authentication, and lifecycle inside that boundary.

The prepared task manifest records `ARCHITECTURE.md`,
`CAPABILITY-CONTRACT.md`, `DATA-CLASSIFICATION.md`, and `MODULE-MANIFEST.md` as
“project for approval”. The task card requires
`required_spec_status: approved`. This record may be reviewed as a proposed
decision, but it cannot become accepted and the decision registry cannot change
until both an authoritative source-status correction and explicit owner
approval of this ADR are recorded. This ADR task does not modify those
normative sources.

## Decision

### 1. Runtime and implementation language

The Nabla Core Runtime will be implemented in an exactly pinned release from
Rust's stable channel.

The production repository will use a Cargo workspace with:

1. a portable Core library containing Application Layer, Kernel, domain-module
   logic, and port definitions;
2. a Desktop Core Service executable that owns the local storage and exposes
   the versioned local protocol selected by ADR-010;
3. an embedded library artifact for Mobile hosts;
4. thin platform adapters that contain OS integration but no divergent domain
   semantics.

The supported Rust toolchain and every dependency are pinned by the release
lock. Production builds use locked, non-interactive commands. Updating the
toolchain, SQLite, or another native dependency is an intentional release
change with reproducibility, compatibility, and license evidence.

Rust types, layouts, allocator objects, and panics are private implementation
details and never cross IPC or the host ABI. Cross-boundary buffer ownership
and copy/free rules are public parts of the C ABI contract defined below.

### 2. Desktop and Mobile host shapes

Desktop production uses at least two OS processes:

```text
Desktop UI / CLI -> versioned authenticated local IPC -> Core Service
                                                        -> canonical SQLite
                                                        -> blob store
```

Exactly one Core Service is the logical writer for one canonical storage root.
The UI and CLI do not open the canonical database or blob store and do not load
the portable Core library as an alternate write path. A single-process Desktop
host remains limited to tests, spikes, and isolated prototypes.

Mobile v2 embeds the same portable Core library in the application process.
The mobile UI and platform background jobs call a narrow host adapter and pass
through the same command/query, policy, transaction, and registry boundaries.
They do not create a second writer.

The embedded boundary is a versioned C ABI with opaque handles, explicit
pointer/length ownership, numeric status categories, and no unwinding across
the ABI. Request and response payload buffers are caller-owned: a bounded
two-pass response call reports the required size and then copies into a
caller-provided buffer. No Core payload allocation crosses the ABI. Opaque Core
handles are created and destroyed only by matching ABI functions. Requests on
one handle are serialized initially. Platform wrappers such as JNI or Swift
interop are adapters over this ABI and may not redefine domain semantics. This
is a host ABI, never a domain-module or plugin ABI. A production ABI
specification and native-consumer tests are gates for Mobile support; the spike
ABI is not reused as that specification.

### 3. Supported platform claims

The initial implementation and qualification target for the production
skeleton is Windows x86-64 Desktop. The approved portability report also
observed an embedded DLL host shape on Windows, but no production-supported
platform exists until the release gates below pass.

Android arm64 API 21 is a build-feasibility observation, not a supported
runtime. Android, iOS, macOS, Linux, Windows ARM64, and any other target remain
unsupported until that exact target has evidence for:

- runtime startup, shutdown, restart, and crash recovery;
- Core-owned SQLite transaction and integrity behavior;
- the selected IPC or embedded-host boundary;
- packaging, signing, install, upgrade, rollback, and removal;
- bounded resources, cancellation, diagnostics, and failure isolation;
- the applicable constitutional conformance matrix.

Adding a target after those gates does not require superseding ADR-001 when it
preserves this runtime, ownership, and contract model. A target-specific
availability or renderer difference must be declared as degradation and cannot
change the meaning of an existing capability version.

### 4. SQLite ownership and linkage

The Core release owns the exact SQLite library version, compile options, and
upgrade policy used for the canonical store. Supported Desktop packages use a
Core-bundled native SQLite build rather than silently binding an ambient system
SQLite. Mobile packaging follows the same rule unless a platform distribution
policy makes it impossible; such a platform is not supported until an explicit
compatibility decision and equivalent transaction, recovery, backup, and
migration evidence exist.

All canonical write connections live inside the Core. The Core enforces one
logical writer and the transaction boundary in `ARCH:6.3`. A database engine or
encryption-provider change requires the applicable ADR, migration/recovery
plan, and compatibility suite. This record does not choose production DDL,
encryption, or a migration framework.

### 5. Packaging and executable extension boundary

A Desktop release is one signed, versioned product set containing compatible
UI, CLI, Core Service, native dependencies, contracts, and release lock. The
launcher resolves the Core executable from the installed product manifest, not
from `PATH`, a shell command, or user-provided code. The Core is not a
machine-wide shared service and exposes no public network listener.

Mobile packages the Core library inside the signed application bundle. A Core
library is not shared between unrelated applications or loaded from a mutable
user path.

For v1, executable domain modules are Rust compile-time packages incorporated
into the trusted Core release and may only be enabled or disabled through the
validated runtime Registry. Declarative manifests and capability data do not
become executable code. Dynamic executable module download or loading,
arbitrary SQL, shell execution, and a universal execution capability are out of
scope and prohibited. ADR-007 may refine package identity, signing, activation,
authority, and failure isolation, but it may not silently widen this executable
boundary. The C ABI above is exclusively a platform-host boundary and cannot be
repurposed as a module/plugin loading interface. Normal modules do not own IPC
listeners, raw database or filesystem access, shell execution, or global
service reflection.

### 6. Persistence port boundary

Portable Core code depends on a typed persistence port, never on a raw SQLite
connection, SQL string, filesystem path, or engine-specific row type. The
SQLite adapter remains inside the trusted Core and must provide:

- one atomic command transaction covering every applicable canonical fact or
  revision, head/tombstone, relation, idempotency receipt, audit record, domain
  event, durable job/event outbox entry, and sync outbox entry for a syncable
  mutation from `ARCH:6.3`;
- exact constraint and contract-defined conflict results rather than silent
  overwrite, without selecting revision or identity semantics owned by later
  ADRs;
- durable commit/rollback, reopen, integrity, and restart-recovery behavior;
- typed reads whose ordering is explicit in the applicable contract rather than
  an accidental engine iteration order;
- finite batch, row, stream, deadline, concurrency, and retry bounds;
- separate administrative migration, integrity, backup, and recovery surfaces
  that cannot be invoked through an ordinary domain capability.

The transaction callback cannot leak a connection or transaction handle beyond
its lifetime. Network, AI, parsing, sync delivery, and other long-running or
non-transactional effects occur outside it; accepted follow-up work is recorded
through the transactional outbox. The exact Rust trait/API and production DDL
remain versioned implementation contracts, but they may not weaken these
semantics or expose storage authority to modules and clients.

### 7. Shared request and failure boundary

IPC and embedded adapters terminate at one typed Core request dispatcher. They
share exact command/query versions, authorization checks, deadlines, finite
limits, idempotency behavior, and error categories. Platform adapters translate
transport and lifecycle events only.

The Core distinguishes:

- request or handler failure, which rolls back only the current transaction;
- recoverable processor, module, provider, index, blob, and client failures,
  which remain localized according to `CON:I15` and `ARCH:20`;
- an embedded-host failure, which may terminate the Mobile application;
- a Desktop Core process failure, which makes all clients temporarily
  unavailable but must not expose a second writer or partial commit.

Rust panics must not cross the C ABI. Ordinary declared module errors are
converted to typed errors at the module/request boundary and roll back the
current transaction. An unwind may be caught only at an explicitly audited
boundary: it aborts the current work, invalidates or quarantines the affected
handle/component, records failed health, and may permit independent work to
continue only after transaction rollback and the required invariant checks.
The spike observed one controlled catch and does not justify a general
recoverable-panic claim. Domain modules cannot introduce unreviewed unsafe code
or native calls; hazardous parsing, native libraries, and untrusted-input work
require a registered isolated processor/adapter boundary before they can claim
`CON:I15` conformance.

A native fault, abort, out-of-memory condition, or invariant failure may still
terminate the shared Core or embedded host. A fatal fault originating in a
module is a conformance defect, not evidence that the module failure was
localized. ADR-007 must assign and test module failure isolation before the
module framework freezes. After any unclean Core stop, startup performs the
recovery and health sequence defined by ADR-010 before accepting ordinary work.

Every request path has finite payload, output, execution, concurrency, queue,
and retry limits derived from `CAP:24`. Long network, AI, parsing, and other
external operations do not run inside the canonical transaction. Cancellation
may stop uncommitted work but never claims to undo a committed transaction.

## Compatibility constraints

1. One capability version has one domain meaning across Desktop, Mobile, IPC,
   and embedded adapters.
2. UI, CLI, platform wrapper, module, and provider code cannot obtain a raw
   canonical database connection or an unrestricted filesystem/runtime handle.
3. IPC and C ABI compatibility are explicit version ranges; an unknown major
   fails closed rather than guessing a representation.
4. A new Core release cannot open an unsupported future schema for write, and
   an old Core cannot silently downgrade it.
5. No packaging change may introduce a second logical writer for one storage
   root.
6. A platform support claim requires runtime evidence on that platform; a
   successful cross-build alone is insufficient.
7. Built-in module activation remains constrained by manifests, exact contract
   hashes, dependency closure, authority envelopes, and immutable Registry
   generations.

## Consequences

### Positive

- One native Core implementation can serve the required separate-process and
  embedded host shapes.
- The selected candidate is supported by the recorded locked Windows runtime,
  C ABI, bundled-SQLite, crash, and Android build observations.
- Storage ownership, module authority, and failure boundaries remain inside a
  small trusted runtime rather than every UI or platform host.
- A pinned native release avoids an undeclared machine-wide runtime and ambient
  SQLite version.

### Costs and risks

- The team must maintain Rust, native build, signing, and cross-compilation
  expertise.
- C ABI and platform wrappers require explicit memory, threading, cancellation,
  and version-compatibility tests.
- A crash in an Embedded Core can terminate the Mobile host; process isolation
  available on Desktop is not promised on Mobile.
- Bundled native dependencies increase package and security-update ownership.
- Windows x86-64 is only the initial implementation and qualification target.
  Broader platform claims require additional evidence and may expose design
  changes.
- The measured probe did not establish production load, ABI stability,
  installer behavior, or arbitrary native-fault containment.

## Alternatives considered

| Alternative | Disposition | Reason |
|---|---|---|
| Separate Core implementation per platform | Rejected | It creates semantic drift and duplicate transaction/security logic, contrary to `ARCH:5.1`. |
| In-process Desktop Core | Rejected for production | It removes the required Desktop process and storage-ownership boundary; it remains valid for tests and spikes only. |
| Rust portable Core with Desktop service and embedded library | Selected | It matches the required host shapes and is the only candidate with the approved measured process, C ABI, SQLite, crash, packaging, and Android build evidence. |
| Managed runtime Core (JVM, .NET, Node.js) | Not selected | No equivalent repository evidence exists, and each adds an unselected runtime/embedding and native SQLite packaging model. |
| C or C++ Core | Not selected | No equivalent evidence exists; it also expands manual memory-safety and ABI risk without a demonstrated benefit for the required boundary. |
| Remote/server-first canonical Core | Rejected | It violates offline baseline, local ownership, and the no-public-listener Desktop requirement. |
| Runtime-loaded executable modules in v1 | Rejected | `CON:I6` requires compile-time packages until a separately approved trusted installation boundary exists. |

## Validation obligations

ADR acceptance authorizes a Windows-targeted production skeleton only. Starting
that skeleton requires accepted ADR-001 and ADR-010, the approved portability
measurement, a locked toolchain/dependency plan, and preservation of the scoped
boundaries above; it does not require a production schema or installer to exist
first.

Before a production release or platform support claim, evidence must cover:

- locked Rust build, dependency/license inventory, and reproducible artifacts;
- Desktop process and selected IPC integration, including single-instance races;
- Core-owned SQLite commit, rollback, integrity, crash, backup, restore, and
  migration paths against the production schema when available;
- C ABI header compilation, memory ownership, panic/fault behavior, concurrency,
  and supported host toolchains before Mobile use;
- persistence-port conformance for atomicity, uniqueness, deterministic reads,
  restart recovery, bounded work, and denial of raw storage authority;
- install, signing, upgrade, rollback, uninstall, and stale-client behavior;
- finite limits, cancellation, backpressure, diagnostics, and fault injection;
- the applicable `CON:I6` and `CON:I15` conformance rows.

## Deferred decisions

This ADR does not select UI technology, production DDL, revision
representation, sync transport, encryption, migration implementation, backup
format, module package trust beyond the v1 built-in boundary, or the exact
Mobile wrapper. Those remain owned by their scheduled specifications and ADRs.

## Supersession rules

A new accepted ADR must explicitly supersede ADR-001 before Nabla can:

- replace Rust as the Core implementation language;
- make the production Desktop Core in-process;
- introduce another canonical writer or a server dependency;
- expose the Core over a public or remote transport;
- silently use an ambient SQLite with an unowned compatibility policy;
- load executable domain modules outside the trusted release boundary; or
- publish a host ABI that exposes Rust layout, allocator, or unwinding details.

A compatible platform adapter, target support appendix, locked toolchain
update, or backwards-compatible ABI minor may amend implementation evidence
without supersession only when it preserves every decision and compatibility
constraint above. ADR-007 is the designated sole successor of this task and may
explicitly supersede only the v1 executable-extension subdecision in section 5;
it does not supersede the Rust, host, process, storage, or persistence-port
decisions unless its owner-approved text says so separately.

## Sources and evidence

- `CONSTITUTION.md` v0.1: `CON:I6`, `CON:I15`, `CON:4.2`, and the conformance
  rules in `CON:7`.
- `ARCHITECTURE.md` v0.1: `ARCH:5`, `ARCH:6`, `ARCH:20`, `ARCH:24`, and
  `ARCH:24.3`, plus the security boundary in `ARCH:18`, subject to the
  source-status gate above.
- `MODULE-MANIFEST.md` v0.1: `MOD:4`, `MOD:5`, `MOD:8`, `MOD:9`, and `MOD:13`,
  subject to the source-status gate above.
- `CAPABILITY-CONTRACT.md` v0.1: `CAP:9` and `CAP:24`, subject to the
  source-status gate above.
- `DATA-CLASSIFICATION.md` v0.1: `DATA:6` and `DATA:12`, subject to the
  source-status gate above.
- Owner-approved `CORE-PORTABILITY-SPIKE-v1`:
  `spikes/SPIKE-CORE-PORTABILITY.md`, especially sections 4–10; raw result
  `tests/spikes/core-portability/results/windows-x86_64.json`, SHA-256
  `58ac966c3ceba16e06743f58daf09fda992fbba164d7304fe7c6dba8871c10ec`;
  owner approval recorded at
  `https://github.com/colibri-the-bird/Nabla/pull/10#issuecomment-5090647252`.
- Prepared task context manifest:
  `4def2994c972deaa9750ea850b6ad2ac58f63f2e22549078a8b6bfacf0ab139d`.

## Approval

Pending explicit owner approval. Until approval is recorded, this ADR remains
proposed and `governance/decisions.yaml` remains `required` for `ADR-001`.
