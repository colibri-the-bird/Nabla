# ADR-009: Typed global IDs, device sequence, and causal time

- **Status:** Accepted — owner approved in PR #20 workflow
- **Date:** 2026-08-22
- **Task:** `ADR-REVISION-IDENTITY-001`
- **Decision owner:** Nabla project owner
- **Related decisions:** `ADR-002`, `ADR-004`, `ADR-012`
- **Supersedes:** None

## Context

Nabla creates entities, revisions, facts, relations, commands, events,
migration runs, stores, and blob manifests while offline. Their identities must survive
export/import, backup/restore, future synchronization, path/title changes, and
schema migrations without a central allocator. The active draft Architecture
therefore requires globally unique offline IDs from v1, one identity and
monotonic sequence for each writable installation, and causal ordering that
does not treat wall clock as truth.

`CON:I3` makes entity and revision identity part of immutable history.
`CON:I12` requires writes to proceed without a network allocator. `CON:I15`
requires an identity or replay defect to quarantine the affected origin or
record instead of corrupting unrelated state. ADR-002 uses these identities in
the revision graph, ADR-004 forbids them from becoming an implicit conflict
winner, and ADR-012 preserves them through physical and semantic migrations.

`REVISION-SYNC-PREPARATION-SPIKE-v1` generated 512 deterministic fixture IDs
from `(kind, origin device, local sequence)` on two devices with zero collisions
and an interleaving-independent set digest. It also measured monotonic local
sequences, graph-depth fixture logical values, equal logical depth for
concurrent branches, transactional sequence allocation, and causal replay. The
fixture hash prefix was expressly not a production ID choice or proof of
global collision freedom; device enrollment, clones, rotation, production
entropy, logical-clock rules, and event-envelope lifecycle were unmeasured.

## Decision

### 1. `NablaIdV1` is a typed random UUID

The v1 identity primitive for independently created records is a 128-bit UUID
version 4 using the RFC 9562 `10` variant and 122 bits supplied by the platform
cryptographically secure random generator.

```text
NablaIdV1 {
  bytes: 16                       // UUID v4 bits fixed
}
```

Canonical text is lowercase `8-4-4-4-12` hexadecimal with hyphens and no braces,
URN prefix, whitespace, or alternate alphabet. Canonical storage, hashing, and
equality use the 16 bytes. Decoders reject noncanonical persisted/wire text
rather than accepting several spellings for the same identity.

Generation fails closed if secure randomness is unavailable. There is no
fallback to wall time, MAC address, process ID, path, title, account name,
device sequence, counter-only identity, or a hash truncated by an implementation.
UUID v4 provides probabilistic uniqueness, not mathematical collision proof;
every store and import boundary still enforces uniqueness and fingerprint
checks.

The same primitive is wrapped in non-interchangeable types:

```text
EntityId      RevisionId      FactId        RelationId
CommandId     EventId         MigrationRunId
DeviceId      BlobManifestId  StoreId       RequestId
CorrelationId
```

Code, schemas, and capability contracts cannot cast one ID type to another or
compare unlike types after stripping the wrapper. A kind prefix in a UI or
export is a presentation/schema discriminator, not part of the UUID bytes.
Every new persistent ID kind requires an owning contract and cannot reuse an
existing field because the shapes happen to match.

An ID field inherits the owning record's Data Catalog class, owner, sensitivity,
sync/export/backup/retention, and purge policy; the UUID primitive is not a
separate canonical record class. Its structural technical purpose is stable
identity across integrity checks, references, history, idempotency,
import/export, backup/restore, and future transport. Only the registered writer
for the owning record may persist that field, and an ID is never reset or
recycled while its record or any retained reference can exist.

Content digests, conflict keys, contract hashes, and blob byte addresses are
algorithm-tagged hashes, not `NablaIdV1`, and cannot be used where a record ID
is required. Equal content may occur in distinct causal revisions; therefore a
payload digest is never a revision ID.

### 2. Identity acceptance and import

An ID is opaque and conveys no authority, ownership, chronology, locality, or
existence permission. Receiving or guessing an ID never grants read or write
access.

Every immutable record has a versioned semantic fingerprint. Import/replay of
an already known ID with the same fingerprint is an idempotent duplicate. The
same typed ID with a different fingerprint is
`IDENTITY_INTEGRITY_CONFLICT`: both inputs are preserved for quarantine and
diagnostics, no existing canonical row is overwritten, and independent origins
continue where safe.

Export/import preserves every included record ID byte exactly. It does not mint
replacement entity, revision, relation, command, event, migration-run, or store
IDs merely because the destination uses a different path, account label,
storage backend, or schema layout. A derived ADR-004 conflict key is rebuilt
from the imported graph and is not an imported record identity. A deliberate
generic entity copy is not defined in v1. A future accepted owning command must
mint a new `EntityId` and define its exact provenance relation; import cannot
pretend to be that command.

`RequestId` identifies one transport/request attempt. `CorrelationId` links a
bounded trace or workflow across declared retries and service boundaries. They
are distinct typed IDs, neither is an idempotency key or authority, and neither
supplies causal or content order.

### 3. Store lineage and writable installation incarnation are distinct

A `StoreId` is a `NablaIdV1` allocated only by Core's Store Identity Service
when a fresh logical store lineage is created. Core's Store Compatibility
Service is the sole writer of the persistent current field under ADR-012; it may
persist only an allocator-issued value. The ID is active `OT` technical state used
by store integrity, migration, backup/restore, diagnostics, and future replica
reconciliation; it is not an account, authority, encryption key, or writer
identity. It is retained in full backups while the store lineage exists and is
excluded from ordinary user-data export. A portable export may define its own
package/provenance identity but cannot expose or reuse `StoreId` as authority.

In-place migration and recovery of the same logical store preserve `StoreId`.
An explicitly declared fork/copy into a distinct logical store creates a new
`StoreId` and records the source in recovery evidence; it never silently edits
the source header. Only fresh-store creation or verified restore/fork activation
may establish the current value. Resetting application UI or local caches does
not change it.

A `DeviceId` is a `NablaIdV1` generated before the first local canonical write
of a fresh writable installation incarnation. It identifies the origin of
commits, not a person, authorization grant, machine name, network address, or
future pairing credential.

Core's Identity/Commit Service is the sole writer of the current device ID,
device sequence, and logical counter through its `kernel_service` port. These
fields are operational provenance `OT` whose technical purpose is offline allocation, idempotent replay, causal
diagnostics, and future sync preparation. Consumers are Commit, Revision,
Event/Outbox, Replay, Integrity, Diagnostics, Backup/Restore, and future Sync
services; domain modules may record returned stamps but do not allocate or reset
them. Active values are included in full backup/recovery state, excluded from
ordinary portable export as device-local operational state, and retained until
the installation is retired and no recovery/replay window depends on them.
Historical origin stamps embedded in retained canonical records inherit those
records' policies and are never scrubbed by current-device reset.

Creating a new writable incarnation is the only reset path for current
device-origin state: it generates a new `DeviceId`, starts its
`DeviceSequence` allocation at 1, and initializes the local logical counter from
the maximum verified counter in the activated store (or zero for an empty
store). Fork-health/quarantine state is `OT` owned by Core Integrity and written
only through its `kernel_service` port, backed up while active, excluded from
ordinary export, and cleaned only after explicit re-identification/reconciliation
closes every recovery consumer.

Historical device IDs remain in revisions/events after uninstall, restore, or
revocation. A restored backup, writable clone, factory reset, or new embedded
installation generates a new current `DeviceId` before accepting writes. It
must not reactivate the source installation's counter as if it were the same
writer. Future pairing may bind authentication keys and a user-visible device
lineage to this ID, but key format, enrollment, revocation transport, and
recovery remain outside this ADR.

A byte-for-byte uncontrolled clone can still copy a current device ID and
counter. Production writers must therefore persist origin fingerprints and
detect two different committed fingerprints for the same
`(device_id, device_sequence)`. This is `DEVICE_SEQUENCE_FORK`; the affected
origin is quarantined from automatic replay until an explicit re-identification
and reconciliation path completes. Nabla does not pretend that offline software
can prove absence of undisclosed clones.

### 4. Device sequence is a commit-local order

Each writable `DeviceId` owns an unsigned 64-bit `DeviceSequence`. Values begin
at 1 and increase strictly for successfully committed syncable transactions.
The atomic commit stamp is:

```text
OriginStampV1 {
  device_id: DeviceId
  device_sequence: uint64
}
```

Allocation occurs inside the same transaction as the command receipt,
revisions/facts, frontier transition, and outbox append. A rolled-back command
does not publish a stamp. Gaps are valid after reservation/recovery and cannot
be interpreted as missing user content. A committed sequence is never reused
under the same device ID. Exhaustion fails closed with
`DEVICE_SEQUENCE_EXHAUSTED`; it never wraps.

One transaction has one origin stamp. Several events within it use a bounded
zero-based `event_ordinal`, giving the local tuple
`(device_id, device_sequence, event_ordinal)`. Ordinal order is meaningful only
inside that committed transaction. Device sequences from different devices are
not comparable and cannot define a global total order or conflict winner.

On replay, the same origin stamp with the same commit fingerprint is duplicate
evidence. The same stamp with a different fingerprint is a device-sequence
fork. A missing earlier sequence may be reported diagnostically but does not by
itself block a causally independent event whose declared dependencies exist.

### 5. Logical time is Lamport metadata, not content authority

Each committed syncable transaction also carries `LogicalTimeV1`, an unsigned
64-bit Lamport counter. Before commit, Core computes:

```text
logical_counter =
  max(local_persisted_counter,
      every explicitly observed parent/dependency logical_counter) + 1
```

The new counter and local persisted counter are committed atomically with the
origin stamp and effects. Roots still advance the local counter. Overflow fails
closed with `LOGICAL_TIME_EXHAUSTED`.

Revision ancestry and explicit event dependencies are the authoritative causal
relations. Same-device sequence orders commits from one origin. Logical time is
a compact monotonic observation used for diagnostics, bounded scheduling, and
sanity checks; `a.logical < b.logical` alone does not prove that `a` is an
ancestor of `b`. Concurrent branches may have equal or different logical
counters without either winning.

When deterministic serialization or a replay work queue needs a stable order
among already dependency-ready records, it may use:

```text
(logical_counter, device_id bytes, device_sequence, event_ordinal, event_id)
```

This is a processing tie-break only. It cannot select a current head, resolve a
field, discard a tombstone, choose a merge base, determine authorization, or
change canonical domain meaning.

### 6. Wall clock is explicit metadata

Core may record `accepted_at` and an origin-observed timestamp in the exact
timestamp type/profile declared by the record contract. These values support
UX, diagnostics, audit policy, and approximate chronology. They are not inputs
to ID generation, idempotency identity, revision ancestry, head selection,
merge resolution, sequence validation, or causal acceptance.

Clock rollback, leap handling, timezone changes, coarse resolution, missing
origin time, or a malicious peer cannot cause silent overwrite. If a contract
needs a real-time deadline or retention timestamp, that policy validates its
own trusted clock separately and does not reinterpret revision causality.

### 7. Versioned event identity and causal envelope

Every syncable canonical commit emits one or more immutable, versioned events.
The minimum logical envelope is:

```text
EventEnvelopeV1 {
  event_id: EventId
  event_type: ExactEventTypeRef
  command_id: CommandId
  correlation_id: CorrelationId
  owner_module: ModuleId
  subject_ids: BoundedSet<TypedRecordId>
  origin: OriginStampV1
  event_ordinal: uint32
  logical_time: LogicalTimeV1
  dependencies: BoundedSet<EventId | RevisionId | FactId>
  sensitivity_class: ExactSensitivityRef
  occurred_at: WallClockMetadata | absent
  committed_at: WallClockMetadata
  payload: ExactVersionedMinimalPayload
  payload_fingerprint: Digest
  schema: ExactSchemaRef
  event_fingerprint: Digest
}
```

The envelope is a versioned delivery/notification record, not a second source of
domain truth and not evidence that Nabla is fully event-sourced. A reconstructible
domain event and its outbox/inbox delivery state are `OT`: the owner module
declares the exact event contract, and Core Event/Outbox Service is the sole
writer through its `kernel_service` port. Full backup retains them while replay/delivery can depend on them,
ordinary export excludes them, and cleanup follows the declared
acknowledgement/replay window. If an external or historical observation is not
reconstructible and has lasting value, its owning contract records it separately
as exactly one `CF` or `CA`; it does not promote this transport envelope into
canonical truth. `CA` audit evidence is a distinct Audit Service record and is
never inferred merely from event delivery.

The event payload is the bounded minimum declared by the exact event contract;
it cannot silently copy a whole sensitive entity. `occurred_at` and
`committed_at` retain their declared provenance/trust distinction and remain
non-causal wall-clock metadata under section 6. `event_fingerprint` is a
domain-separated digest over every other canonical envelope field in exact
schema order, including `payload_fingerprint`; `event_fingerprint` itself is
excluded from its input. Duplicate/quarantine checks use `EventId` plus this
full fingerprint, never payload fingerprint alone.

Delivery order is not event meaning. A consumer applies an event only when its
typed dependencies exist and validate; otherwise it stores bounded typed
pending state. Duplicates are suppressed by event ID plus full event fingerprint. Unknown
event/schema versions are preserved opaque and cannot be treated as current
state. ADR-012 may provide an exact registered reader/upcaster view, but the
original event ID, bytes, version, origin, and fingerprint remain unchanged.

Network synchronization, cursors, peer authentication, and reconciliation are
future protocol decisions. This envelope only ensures that v1 records do not
need identity replacement when that protocol arrives.

### 8. Failure boundaries and observability

| Condition | Result |
|---|---|
| secure random generation unavailable | `IDENTITY_GENERATION_UNAVAILABLE`; no record |
| known typed ID, same fingerprint | idempotent duplicate |
| known typed ID, different fingerprint | `IDENTITY_INTEGRITY_CONFLICT`; quarantine |
| same device/sequence, different commit fingerprint | `DEVICE_SEQUENCE_FORK`; quarantine origin |
| missing causal dependency | typed pending `MISSING_DEPENDENCY` |
| unknown ID/event/schema type | preserve opaque or reject at declared boundary |
| sequence/logical counter overflow | fail closed; no wrap or partial commit |

Diagnostics may expose type, shortened/correlation-safe identity, device health,
sequence ranges, reason codes, and counts under policy. IDs are not secrets, but
logs do not treat them as harmless content or authority and do not attach raw
entity payloads merely to explain a collision.

## Compatibility constraints

1. Persisted v1 record IDs are typed canonical UUID v4 values and never remap
   during import, sync, or migration.
2. Secure randomness failure cannot fall back to time, path, title, MAC, or a
   local counter.
3. `DeviceSequence` orders commits only inside one writable device incarnation.
4. Revision ancestry and explicit dependencies, not clocks, define causality.
5. Logical and lexical ordering is a deterministic processing tie-break, never
   a content or lifecycle winner.
6. Restore/clone creates a new writer device ID; duplicate origin stamps with
   different fingerprints fail closed.
7. Unknown canonical record versions remain opaque/exportable; unknown event
   versions remain opaque for compatible transport/recovery and are never
   silently rebound or treated as current domain state.
8. Hash identities and record IDs remain separate typed domains.

## Consequences

### Positive

- Every device can create IDs immediately without a network or central range.
- Random IDs contain no required wall-clock, MAC, account, or path component.
- Typed wrappers prevent accidental cross-domain joins and authority mistakes.
- Separate origin, logical, and wall-clock fields make causal claims auditable.
- Stable event/revision identities survive future store and protocol migration.

### Costs and risks

- UUID v4 is probabilistic and random insertion order may cost more than a
  time-ordered key in some unmeasured storage engines.
- Writable clone fencing and future device credentials need implementation and
  recovery evidence.
- Lamport counters do not replace graph traversal for causal truth.
- Origin metadata adds durable bookkeeping that diagnostics and export must
  handle through their existing owning contracts.

## Alternatives considered

| Alternative | Disposition | Reason |
|---|---|---|
| Typed UUID v4 from CSPRNG | Selected | Offline, standard, opaque, independent of clocks and device enrollment. |
| UUID v7 / ULID as universal ID | Rejected for v1 identity | Embedded wall time invites chronological/causal misuse and leaks timing; sortability alone is not semantic evidence. |
| `(device_id, sequence)` as every record ID | Rejected | Clone/counter lifecycle becomes a collision boundary and couples identity to origin bookkeeping. |
| Central integer or server range | Rejected | Breaks offline creation and portable import. |
| Content hash as every ID | Rejected | Equal content may have distinct causal identity; schema/hash evolution would remap records. |
| Wall-clock last-write-wins / hybrid logical clock winner | Rejected | A clock cannot erase concurrent user content under `CON:I3`. |
| Lexical UUID winner | Rejected | Deterministic data loss is still data loss. |

## Validation obligations

Before production identity support is accepted, evidence must cover:

1. canonical UUID bit, binary/text, casing, malformed, and wrong-type fixtures;
2. secure-random failure with no fallback or partial persistent record;
3. bounded high-volume multi-device generation and collision/fingerprint
   handling, without calling the sample a proof of global uniqueness;
4. export/import round trips preserving every typed ID byte;
5. same ID/same fingerprint duplicate and same ID/different fingerprint
   quarantine for every immutable record class;
6. transactional sequence allocation, rollback, retry, gaps, restart,
   near-exhaustion, and no reuse;
7. restore/clone creates a new device ID and a simulated duplicate stamp yields
   `DEVICE_SEQUENCE_FORK` without overwriting either input;
8. Lamport roots, parent observation, same-device commits, concurrent branches,
   remote jumps, restart, and exhaustion;
9. proof that wall-clock and deterministic ready-queue ordering never select a
   head or conflict value;
10. multi-event commit ordinals, duplicates, missing dependencies, unknown
    versions, and every arrival permutation of bounded fixtures;
11. physical and semantic migrations preserving IDs, origin stamps, dependency
    identity, and fingerprints;
12. Desktop/Mobile/CLI golden compatibility and fault isolation across devices,
    entities, and event types;
13. diagnostic/export review for persistent device and record identifiers;
14. quantitative storage/index evidence before a performance claim or alternate
    ID version is introduced.

## Deferred decisions and unmeasured assumptions

This ADR does not choose device authentication keys, pairing/enrollment,
revocation transport, account identity, clone-detection mechanism, network sync,
blob byte-address profile, database index layout, or concrete retention periods
beyond the class/lifecycle baselines above. UUID collision risk, platform CSPRNG
behavior, random-key storage cost, clone recovery, and cross-platform event
performance require implementation evidence. The spike's 512 fixture values and
SHA-256 prefix are not that evidence.

## Supersession rules

A compatible specification may define typed wrappers, storage columns, event
wire encoding, device enrollment, and numeric limits without superseding this
ADR only if it preserves canonical UUID v4 record IDs, exact import identity,
per-device sequence scope, ancestry/dependency causality, non-authoritative
logical/wall clocks, and fail-closed collision/fork behavior. A different
persistent ID version or causal winner rule requires a superseding ADR and an
explicit migration that never silently remaps existing IDs.

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
- Approved `REVISION-SYNC-PREPARATION-SPIKE-v1`: 512 fixture IDs, two devices,
  zero measured collisions, transactional local sequence, causal graph/replay,
  24 convergent schedules, semantic digest
  `f60a38c640d5b8c7bdd9b3f6bdbf727f3ebf9932746c04494421790495223771`,
  and raw-result SHA-256
  `b9ea6908f265440f36add96ac2f8123ea37e50610e3e6360dd81a75e1e0a3b9c`.
- Approved `SPEC-NAVIGATION.md` v0.4: `NAV:6` execution and evidence protocol.
- Prepared task context manifest:
  `c2e2f9ab5128c589585333ef40c367661383f1c03336d65e33992f9a0281a1c0`.

## Approval

The Nabla project owner explicitly approved this ADR in the Codex task
conversation on 2026-08-22 for PR #20. ADR-009 is Accepted,
`governance/decisions.yaml` records it as `accepted`,
`ADR-REVISION-IDENTITY-001` is `completed`, and the sole successor
`ADR-DOCUMENT-ENGINE-001` is `ready`.
