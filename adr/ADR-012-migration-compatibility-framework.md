# ADR-012: Crash-resumable migration and explicit compatibility framework

- **Status:** Proposed — owner approval required
- **Date:** 2026-08-22
- **Task:** `ADR-REVISION-IDENTITY-001`
- **Decision owner:** Nabla project owner
- **Related decisions:** `ADR-002`, `ADR-003`, `ADR-004`, `ADR-009`
- **Supersedes:** None

## Context

Nabla needs a migration policy before the first long-lived DDL. Physical store
layout, canonical payload schemas, event envelopes, and derived indexes evolve
at different boundaries. Treating them as one in-place database version risks
rewriting immutable revisions, remapping IDs, replaying effects, silently
rebinding saved queries, or leaving an interrupted store half-readable.

`CON:I3` forbids mutation of historical revision meaning. `CON:I12` requires
local canonical data, history, export, backup, and integrity work to remain
available without a network. `CON:I15` requires an interrupted migration or
unsupported module/schema to expose a bounded health/recovery state rather than
damage unrelated data. The active draft Architecture explicitly requires a
separate recovery path for interrupted migration and versioned schemas/events
from v1.

ADR-002 separates the logical revision from snapshot/patch encodings. ADR-004
preserves unknown-schema branches and prohibits migration from resolving a
conflict. ADR-009 fixes persistent IDs, origin stamps, and causal envelopes.
Accepted ADR-003 requires exact saved-query references and says an incompatible
persisted query becomes typed unavailable rather than being silently rebound.

`REVISION-SYNC-PREPARATION-SPIKE-v1` measured one local transaction for command,
sequence, revision, frontier, and outbox state; restart after selected pre- and
post-commit process kills; idempotent duplicate delivery; typed missing-parent
state; and deterministic replay of one fixed event set. It did not run a schema
migration, power-loss recovery, downgrade, mixed-version reader, large-copy
operation, content converter, or mobile migration. Those claims remain open.

## Decision

### Privileged administrative workflow boundary

Physical migration, batch semantic migration, and restore are registered,
versioned privileged administrative workflows, not generic Commands exposed to
UI, AI, imports, or modules. An exact Start Command binds verified actor/policy,
`StoreId`, source fingerprint, plan/backup and recovery-input digests, resource
profile, preview/confirmation, command ID, idempotency scope, and correlation ID
before the workflow is accepted. The Kernel Workflow Service is the sole writer
of durable workflow `OT`; migration/restore step executors return typed bounded
outcomes and never write workflow rows directly. The Audit Service separately
writes mandatory minimized `CA` receipts for significant start, failure,
recovery, cutover/activation, and terminal outcomes.

Per-entity content conversion is performed by the exact registered ADR-002
revision command invoked from that pinned workflow. The workflow does not gain a
generic canonical-table writer, and imported parameters cannot select code or
broaden its declared entity/schema scope.

### 1. Four evolution domains stay distinct

Nabla defines four migration domains:

| Domain | Source of truth behavior | Migration rule |
|---|---|---|
| physical store | tables, indexes, files, body placement, encoding containers | may copy/reindex/re-encode but preserves logical IDs and fingerprints |
| canonical content | versioned entity/fact/relation payload meaning | immutable old record remains; semantic change creates a new revision/fact |
| event/protocol | immutable event envelope/payload plus transitionable outbox/inbox `OT` delivery state | original event remains exact; delivery state preserves identity/idempotency; compatible view is derived by an exact adapter |
| derived state | index, projection, cache, materialized snapshot | drop/rebuild from exact canonical inputs; never migrated as sole truth |

A release cannot label a semantic content rewrite as a physical migration.
Conversely, changing compression or table layout does not create user revisions
when logical bytes, schema meaning, IDs, parents, and digests remain identical.

### 2. Exact schema and migration identity

Every persistent or event schema uses:

```text
ExactSchemaRef {
  schema_id: StableSchemaId
  semantic_version: SemVer
  contract_hash: Digest
  canonicalization_profile: ExactProfileRef
}
```

SemVer alone never grants compatibility. Each release carries an explicit,
finite compatibility matrix mapping exact reader/writer schema refs and required
features. Unknown fields or versions are not ignored merely because a major
number matches. A compatible reader may apply only defaults, field preservation,
and transformations declared by the exact contract and covered by golden
fixtures.

A migration step is also exact:

```text
MigrationStepRef {
  migration_id: StableMigrationId
  semantic_version: SemVer
  contract_hash: Digest
  domain: physical | content | event_view | derived_rebuild
  from_schema: ExactSchemaRef
  to_schema: ExactSchemaRef
  dependencies: BoundedSet<MigrationStepRef>
  reversibility: forward_only | exact_reverse_available
}
```

For one component and source schema there is at most one activated forward step
toward one target generation in a release. Cross-component dependencies form a
finite acyclic plan with one canonical topological order and plan digest.
Ambiguous, missing, cyclic, or hash-mismatched plans fail before data mutation.

Migration parameters are closed validated data. They cannot contain executable
source, storage paths outside the selected store, arbitrary query text, or a
floating implementation name. The release supplies every activated migration
implementation and exact contract; imported data cannot install or replace it.

### 3. Store compatibility header

Every long-lived store has a small independently readable header containing:

```text
StoreCompatibilityV1 {
  store_id: StoreId
  physical_generation: uint64
  active_schema_set_digest: Digest
  required_reader_features: BoundedSet<ExactFeatureRef>
  required_writer_features: BoundedSet<ExactFeatureRef>
  migration_state: idle | active | recovery_required
  active_migration_run_id: MigrationRunId | absent
}
```

`StoreCompatibilityV1` is active `OT`, owned and written only by Core's Store
Compatibility Service through the `kernel_service` administrative port.
Migration, Restore, and Store Identity services provide validated inputs but do
not edit the row directly. Its
technical purpose is writer admission, exact cutover/recovery reconciliation,
and backup/restore compatibility; its consumers are Core startup, Migration,
Integrity, Backup, and Restore services. A full backup includes the active
header. Ordinary portable export includes only the schema/version manifest
needed to interpret exported canonical records, not this operational row. The
header is retained for the lifetime of the store and may be reset or replaced
only by verified fresh-store creation, atomic migration cutover, or atomic
restore activation; ordinary cleanup cannot edit it.

The current binary compares exact feature/schema support before opening a
writer. If it cannot interpret every required writer feature, it does not write,
auto-downgrade, or guess. It enters `STORE_VERSION_UNSUPPORTED` read-only
maintenance mode when the header and opaque-record/export paths are safe;
otherwise it requires an explicitly supported recovery tool.

Unknown canonical records remain byte-for-byte preserved with IDs, schema refs,
fingerprints, parent/dependency refs, and integrity digests. Preservation does
not mean interpretation or activation as current domain state.

### 4. Append-only migration ledger

Core owns an append-only migration-workflow `OT` recovery ledger. The exact
Migration Workflow contract owns its schema, while the Kernel Workflow Service
is the sole writer through the `kernel_service` port. Its technical purpose is
exact restart, status, reconciliation, and linkage to independent audit
evidence; its consumers are Migration, startup recovery, Integrity,
Diagnostics, Backup, and Restore services. It is not user content, is not the
audit source of truth, and cannot authorize schema meaning.

```text
MigrationRunV1 {
  run_id: MigrationRunId
  workflow_ref: ExactWorkflowRef
  start_command_id: CommandId
  start_idempotency_scope_digest: Digest
  actor_ref: ActorRef
  start_audit_ref: AuditRef
  store_id: StoreId
  plan_digest: Digest
  source_generation: uint64
  target_generation: uint64
  binary_contract_digest: Digest
  started_from_store_fingerprint: Digest
}

MigrationCheckpointV1 {
  run_id: MigrationRunId
  checkpoint_sequence: uint64
  previous_checkpoint_digest: Digest | absent
  attempt: uint32
  step_ref: MigrationStepRef
  phase: preflight | expand | copy | validate | cutover | cleanup | complete
  bounded_cursor: OpaqueCheckpoint | absent
  source_digest: Digest
  candidate_digest: Digest | absent
  result: succeeded | retryable_failed | terminal_failed | cancelled
  error_code: StableCode | absent
  checkpoint_digest: Digest
}

MigrationLeaseV1 {
  run_id: MigrationRunId
  lease_generation: uint64
  owner_token_digest: Digest
  expires_at: TrustedDeadline
}
```

`MigrationRunId` is the typed workflow-instance identity for this contract: one
accepted migration workflow has exactly one run ID, and no parallel generic
`WorkflowInstanceId` is persisted. `checkpoint_digest` is the domain-separated
digest of the exact canonical bytes of every checkpoint field except
`checkpoint_digest` itself; `previous_checkpoint_digest` is included.
The predecessor is absent exactly for sequence 1 and otherwise equals the digest
at sequence `n-1`; `attempt` starts at 1 for each step/phase/cursor input and
increments under the workflow's finite retry bound.

Checkpoint records are appended only after a bounded phase/batch succeeds or a
stable typed failure is recorded; in-progress ownership lives in the lease.
`checkpoint_sequence` starts at 1 and increases contiguously inside one run;
each digest covers the complete record and predecessor. The highest contiguous,
digest-verified sequence is the deterministic recovery tip. Same sequence with
different bytes, a gap, or a predecessor mismatch enters
`MIGRATION_STATUS_UNKNOWN` reconciliation. A later attempt at the same
step/phase/cursor may follow `retryable_failed` with a higher sequence; resume
starts from the last succeeded checkpoint and never erases the failed attempt.
`terminal_failed` seals the run and requires a new explicitly started run. A
safe-checkpoint cancellation appends `cancelled` at the next sequence and seals
the run without reverting any committed cutover; later cleanup, if needed, is a
new explicit workflow. Cancellation requested inside an atomic batch/cutover is
deferred until its outcome is known and a safe checkpoint can be appended.

The Kernel Workflow Service is the sole writer of run, checkpoint, and lease
`OT`. A transactionally updated finite lease prevents two local executors; loss
or ambiguity of the lease enters recovery reconciliation rather than starting a
second plan or accepting both outcomes.

The active run, checkpoints, and lease are `BACKUP_REQUIRED` while recovery can
depend on them and are excluded from ordinary portable export. Terminal ledger
records follow the explicit operational retention/cleanup window in the Data
Catalog; cleanup is allowed only after cutover status, rollback/recovery input,
backup coverage, and audit linkage no longer depend on them. A failed or
cancelled run is never reset by deleting ambiguous state. The Audit Service,
not Migration Service, separately appends `CA` evidence for privileged start,
failure, recovery action, and cutover outcome under the applicable audit
retention/privacy policy.

### 5. Expand, migrate, validate, cut over, contract

Every physical migration follows these stages:

1. **Preflight.** Resolve one exact plan; verify source header/ledger, integrity,
   compatible binary, required disk/memory/time limits, cancellation policy,
   and an accepted recovery input appropriate to the step. No mutation occurs
   if any precondition is missing.
2. **Expand.** Create additive candidate structures or a shadow store without
   dropping the active representation. The affected component may enter a
   declared maintenance-read state; unrelated components remain available.
3. **Migrate.** Copy or transform deterministic bounded batches selected by
   stable IDs, not unstable offsets. Every batch is idempotent and records a
   checkpoint only with its candidate writes.
4. **Validate.** Check record counts by class, typed ID sets, parent/relation
   closure, exact schema refs, fingerprints/digests, frontier and outbox/inbox
   state, idempotency outcomes, and domain invariants. Sampling alone cannot
   authorize cutover.
5. **Cut over.** One atomic metadata transaction switches the active physical
   generation, appends the succeeded `OT` cutover checkpoint, and links the
   separately owned `CA` cutover receipt. Before it, the source remains
   authoritative; after it, the validated candidate is authoritative.
6. **Contract.** Removal of the former representation is a separate later step
   requiring a committed cutover, a proven reader/rollback window, backup and
   restore evidence, and applicable retention/purge authority. Until those
   gates exist, the old representation is retained or moved to an explicit
   recoverable quarantine.

No stage silently broadens authority, replays a command/external effect, or
changes logical content. Finite limits cover plan steps, batch items/bytes,
checkpoint bytes, total work, memory, disk headroom, deadline, retries, and
diagnostic output.

### 6. Crash and cancellation semantics

Before cutover, restart reads the ledger, revalidates the source and candidate,
and resumes the same exact step/cursor or discards only the candidate. After a
committed cutover, restart uses the target generation and never automatically
switches back because a cleanup step failed.

If Core cannot determine whether cutover committed, it reconciles the atomic
store header and cutover receipt. It reports `MIGRATION_STATUS_UNKNOWN` until
that check resolves; it does not run the step again against both generations.
Cancellation is honored only at declared safe checkpoints and never in the
middle of an atomic batch or cutover.

An interrupted affected component exposes `migration_active` or
`migration_recovery_required`, bounded progress, last stable error, and allowed
actions. Independent modules, maintenance export of unaffected/opaque records,
backup diagnostics, and integrity checks remain available where their own
dependencies are healthy.

### 7. Canonical content upgrades create history

A transformation that changes canonical payload meaning, schema reference, or
canonical payload digest is not a physical rewrite. It runs as an explicit,
idempotent content-migration command and creates new ADR-002 revisions. A
payload-bearing upgrade uses `FullSnapshot`; a deleted head creates a parented
target-schema revision with `DeletedBody` and no fabricated payload.

For a single-head entity, the upgrade revision names that head as parent. For a
multi-head entity, one command binds the complete ADR-002 `FrontierRefV1`,
validates every paged head, and atomically creates exactly one upgraded child
per head, preserving the same number of branches; it cannot combine them or
commit a subset. Live and archived children contain full snapshots; deleted
children contain `DeletedBody`. An unknown/incompatible head blocks the whole
branch-preserving command and any claim that the entity is upgraded. The
content-upgrade contract declares a finite head-count/byte/work ceiling. If the
complete frontier exceeds it, an explicit ADR-004 frontier-reduction workflow
must first reduce it; migration itself cannot process only a page or subset.
Only ADR-004 resolution can join heads.

Conflict descriptors are ADR-004 `DD` projections, not history. A content
migration changes their canonical graph/frontier inputs, after which the
Revision Conflict Processor deterministically rebuilds the applicable
descriptor and may discard the stale projection. The migration never writes,
links, supersedes, or marks a descriptor resolved.

Each upgrade revision fills the exact ADR-002 `content_migration` field with
`ContentMigrationProvenanceV1`: run ID, exact migration step, source and target
schema/digests, and validation digest. Origin and command identity remain in the
ordinary revision envelope. For a deleted head the source and target payload
digests are absent. Old revisions remain immutable and exportable. Upgrade is
never a hidden read-time write. If an application can read an old version
directly, that is explicit compatibility, not an implicit migration.

For future saved queries, exact DSL/source/operator/field refs from ADR-003 are
retained. An explicit converter may create a new saved-query revision only when
it can prove the exact target refs and normalized meaning. Otherwise the old
query is typed unavailable; a compatible-looking name is never rebound.

### 8. Events, idempotency, and derived state

Physical migration preserves event IDs, command IDs, origin stamps, exact
versions, payload fingerprints, inbox receipts, outbox acknowledgement, and
idempotency outcomes. It does not re-emit old events or re-execute effects.

An event-view adapter may expose an older immutable event to a newer consumer
only under one exact `from`/`to` migration contract. Its output is a deterministic
derived view with provenance; the original event bytes and identity remain the
deduplication/replay evidence. Separate `CA` remains the audit source of truth.
Missing/failed adapters leave typed pending state without blocking independent
event types.

Indexes, projections, search state, caches, and alternate materialized revision
bodies are rebuilt after cutover from exact canonical inputs and algorithm
versions. Rebuild failure marks only that derived component stale/unavailable;
it does not roll back valid canonical cutover or promote derived data to truth.

### 9. Downgrade, rollback, and restore

Application rollback is safe only when the older binary declares exact read and
write compatibility with the current store header. Otherwise it is read-only or
refuses to open the store for normal use.

A schema downgrade is a new exact migration step, never reversal by version
number. It is allowed only when a tested reverse contract proves no information,
identity, ancestry, conflict, event, or idempotency loss. A forward-only step is
recovered by completing it or restoring the pre-migration recovery input; Core
does not destructively guess a reverse transform.

Restore always runs against a staging copy: validate backup manifest/checksums,
exact schema/features, and opaque unknown-module records; apply required
migrations only to staging; verify canonical IDs, graph/relation closure,
fingerprints, blobs, and workflow receipts; then atomically activate the staged
set. Failure before activation leaves the current working set intact. After
activation, derived state is discarded/rebuilt and a bounded post-restore report
and mandatory `CA` receipt are produced.

Recovering the same logical store preserves its historical IDs, revisions, and
ADR-009 `StoreId`, but creates a new current writer `DeviceId` before accepting
new commits. An explicitly declared writable fork instead creates both a new
store lineage `StoreId` and new `DeviceId`, with source provenance in recovery
evidence. Unknown module data remains opaque, integrity-verifiable, backed up,
and maintenance-exportable rather than dropped. Reconciliation with commits
created after the backup is a future sync/recovery protocol, not a migration
shortcut.

### 10. Stable failure codes

| Condition | Result |
|---|---|
| no exact path / ambiguous or cyclic plan | `MIGRATION_PATH_UNAVAILABLE` |
| incompatible writer/store features | `STORE_VERSION_UNSUPPORTED` |
| preflight capacity/recovery gate fails | `MIGRATION_PREFLIGHT_FAILED` |
| source changed or checkpoint fingerprint differs | `MIGRATION_SOURCE_CHANGED` |
| batch/validation invariant mismatch | `MIGRATION_VALIDATION_FAILED` |
| cutover outcome cannot yet be reconciled | `MIGRATION_STATUS_UNKNOWN` |
| unknown content/event schema | `UNSUPPORTED_SCHEMA`; preserve opaque |
| reverse contract absent | `DOWNGRADE_UNAVAILABLE` |
| cancellation accepted at safe checkpoint | `MIGRATION_CANCELLED`; run sealed, committed cutover retained |
| finite resource limit reached | `RESOURCE_EXHAUSTED`; resume only from valid checkpoint |

Errors include correlation IDs and bounded recovery actions, not raw sensitive
payloads, ad-hoc SQL, stack traces, or instructions to delete the store.

## Compatibility constraints

1. Physical migration never remaps record IDs or changes logical revision,
   parent, frontier, conflict, event, command, or idempotency meaning.
2. Semantic payload change creates immutable history and never rewrites an old
   revision.
3. Compatibility is an exact tested matrix, not inferred from a version range
   or matching field name.
4. Cutover is atomic and occurs only after complete deterministic validation.
5. Unknown future schema stays opaque, integrity-verifiable, and exportable;
   it is not silently current.
6. Downgrade requires an explicit lossless reverse contract.
7. Event adapters create derived views and never replace original event
   identity/evidence.
8. Derived-state failure cannot invalidate canonical migration success.
9. Saved queries retain ADR-003 exact refs and fail typed rather than rebind.

## Consequences

### Positive

- Logical history and identity survive physical backend evolution.
- Shadow/copy validation and atomic cutover give a deterministic crash-recovery
  boundary.
- Exact compatibility prevents silent schema and saved-query reinterpretation.
- Unknown future records remain recoverable even without active domain code.
- Content migrations become visible, reversible-by-history operations.

### Costs and risks

- Expand/copy/cutover needs temporary disk space and a migration ledger.
- Supporting mixed canonical schemas increases reader and test complexity.
- Conservative downgrade rules may block an older application from writing.
- Concrete capacity, outage, and mobile limits are unmeasured.

## Alternatives considered

| Alternative | Disposition | Reason |
|---|---|---|
| Versioned expand/copy/validate/atomic-cutover framework | Selected | Separates physical and semantic change and has an explicit crash boundary. |
| In-place best-effort DDL sequence | Rejected | A crash can leave ambiguous partial state and no verified rollback input. |
| Rewrite every historical revision to latest schema | Rejected | Violates immutable history, IDs/digests, conflict evidence, and export fidelity. |
| Lazy hidden migration on read | Rejected | Reads would mutate canonical state and failures would be nondeterministic. |
| SemVer-major compatibility inference | Rejected | Same major cannot prove defaults, unknown-field meaning, or canonical bytes. |
| Auto-downgrade when an older binary opens | Rejected | It can destroy unknown/new information without a reverse proof. |
| Rewrite old events to new envelopes | Rejected | Breaks deduplication, audit linkage, causal references, and replay evidence. |

## Validation obligations

Before production migration support is accepted, evidence must cover:

1. exact plan resolution, missing step, wrong hash, ambiguity, cycle, and
   deterministic cross-component order;
2. store-header compatible reader/writer and unsupported read-only/refusal
   matrices across previous/current/next fixtures;
3. privileged Start Command actor/policy/preview/idempotency binding, sole Kernel
   Workflow `OT` writer, separate Audit `CA`, preflight capacity, integrity,
   recovery-input, and finite-limit boundaries;
4. crash/cancel/restart before and after every checkpoint and immediately around
   cutover, including contiguous hash-chain, duplicate/gap/fork, retryable then
   succeeded, terminal failure, lease-loss, and status reconciliation cases;
5. idempotent batch resume with stable-ID cursors and source-change detection;
6. complete ID, revision graph, frontier, conflict, relation, event, outbox,
   inbox, idempotency, count, and digest validation before cutover;
7. physical migration proving byte/semantic identity and no duplicate effect or
   event emission;
8. single-head and multi-head content upgrade, exact inline/paged frontier
   binding, over-limit refusal/reduction precondition, incompatible branch
   blocking, live/archived full snapshots, deleted bodies, exact
   `ContentMigrationProvenanceV1`, derived descriptor rebuild, and old-history
   export;
9. saved-query exact-ref conversion and typed-unavailable fixtures from
   ADR-003;
10. unknown content/event/module preservation, maintenance export, and later
    compatible activation;
11. event-view determinism, original-event deduplication, missing adapter, and
    independent event progress;
12. derived drop/rebuild failure without canonical rollback or corruption;
13. exact reverse migration, forward-only downgrade refusal, app rollback, and
    staged backup restore that preserves the current working set on failure,
    preserves or explicitly forks `StoreId`, and creates a new writer device ID;
14. Desktop/Mobile/CLI golden fixtures and power-loss/corruption fault injection
    before durability claims;
15. benchmarks for disk headroom, batch size, time, memory, startup recovery,
    and maintenance availability before numeric production limits are fixed.

## Deferred decisions and unmeasured assumptions

This ADR does not choose DDL, a database, migration library, file-swap primitive,
backup format, encryption/key migration, concrete terminal-ledger retention
duration, concrete batch limits, UI, network sync, or cross-device rolling
deployment. The replay spike did not measure any migration; selected process
kills are not evidence for power-loss or corruption durability. Those require
adapter- and platform-exact tests before implementation claims.

## Supersession rules

A compatible implementation specification may define the ledger/storage schema,
batch cursors, exact feature matrix, recovery tooling, and numeric limits
without superseding this ADR only if it preserves domain separation, exact refs,
append-only recovery evidence, full validation, atomic cutover, immutable
content history, stable identity, explicit downgrade, and opaque unknown-schema
preservation. In-place semantic rewrite, silent rebinding, ID remapping, or
unverified rollback requires a superseding ADR.

## Sources and evidence

- `CONSTITUTION.md` v0.1: `CON:I1`, `CON:I2`, `CON:I3`, `CON:I4`, `CON:I7`,
  `CON:I8`, `CON:I10`, `CON:I12`, `CON:I14`, `CON:I15`, and `CON:I16`.
- Active draft `ARCHITECTURE.md` v0.1: `ARCH:7`, `ARCH:9`, `ARCH:10`,
  `ARCH:10.3`, `ARCH:10.4`, `ARCH:16`, `ARCH:18`, `ARCH:19`, `ARCH:20`,
  `ARCH:24`, `ARCH:24.1`, and `ARCH:24.2`.
- Active draft `DATA-CLASSIFICATION.md` v0.1: `DATA:2`, `DATA:4.1`,
  `DATA:4.6`, `DATA:9`, and `DATA:10`.
- Active draft `CAPABILITY-CONTRACT.md` v0.1: `CAP:10`, `CAP:11`,
  `CAP:11.6`, `CAP:11.9`, `CAP:14`, `CAP:17`, `CAP:18`, `CAP:19`, `CAP:20`,
  `CAP:21`, and `CAP:24`.
- Active draft `MODULE-MANIFEST.md` v0.1: `MOD:18` and `MOD:19`.
- Active draft `LOOP-SPEC.md` v0.1: `LOOP:4`, `LOOP:6`, `LOOP:7`, `LOOP:8`,
  and `LOOP:10`.
- Active draft `KNOWLEDGE-MODULE.md` v0.1: `KNOW:26`; active draft
  `DOCUMENT-MODULE.md` v0.1: `DOC:27`. All active draft sources above were
  consumed under the pre-baseline `draft-allowed` gate.
- Accepted `ADR-003`: exact persisted query refs, typed incompatibility, and no
  silent name-based rebinding.
- Approved `REVISION-SYNC-PREPARATION-SPIKE-v1`: transaction/restart,
  idempotency, typed dependency, deterministic replay evidence, semantic digest
  `f60a38c640d5b8c7bdd9b3f6bdbf727f3ebf9932746c04494421790495223771`,
  and raw-result SHA-256
  `b9ea6908f265440f36add96ac2f8123ea37e50610e3e6360dd81a75e1e0a3b9c`.
- Approved `SPEC-NAVIGATION.md` v0.4: `NAV:6` execution and evidence protocol.
- Prepared task context manifest:
  `6785c3183b4f810a523888e32152edec74db73f40a128cfdcd1a93bba1b84185`.

## Approval

Owner approval is pending. Until explicit approval, this ADR remains Proposed,
`governance/decisions.yaml` keeps ADR-012 `required`,
`ADR-REVISION-IDENTITY-001` remains `ready`, and no successor is activated.
