# ADR-002: Hybrid immutable revision representation

- **Status:** Proposed — owner approval required
- **Date:** 2026-08-22
- **Task:** `ADR-REVISION-IDENTITY-001`
- **Decision owner:** Nabla project owner
- **Related decisions:** `ADR-004`, `ADR-009`, `ADR-012`
- **Supersedes:** None

## Context

Nabla must preserve every meaningful state of a revisioned entity while still
supporting local edits, future synchronization, conflicts, export, recovery,
and bounded storage work. `CON:I3` requires stable entity identity, immutable
parented revisions, set-valued heads, non-destructive undo, and tombstones.
`CON:I12` requires revision history to remain usable offline. `CON:I15`
requires malformed or unavailable revision data to fail locally without
damaging independent canonical state.

The active draft Architecture permits full snapshots, patches, or a hybrid but
requires the public revision semantics to remain independent of that physical
choice. It also requires concurrent descendants to remain as separate heads
until an explicit resolution revision joins them. ADR-004 fixes merge and
conflict semantics, ADR-009 fixes typed global identities and causal metadata,
and ADR-012 separates logical content upgrades from physical store migrations.

`REVISION-SYNC-PREPARATION-SPIKE-v1` exercised immutable full-snapshot fixture
revisions, two concurrent heads, a two-parent merge, a tombstone, stale and
partial-frontier rejection, transaction/outbox crash points, missing-parent
buffering, duplicates, and all 24 arrival permutations of one four-event graph.
All seven cases and 124 assertions passed. The spike did not compare production
snapshot and patch encodings, storage size, reconstruction latency, corruption,
power loss, scale, mobile behavior, or compaction. This ADR therefore uses the
measured graph and atomicity properties but does not present an unmeasured
performance choice as evidence.

## Decision

### 1. Logical revision is independent of its body encoding

Nabla adopts a **hybrid revision model**. A logical revision has one immutable
semantic envelope and one or more verified body encodings. Snapshot and patch
are encodings of the same materialized payload, not different public revision
semantics.

The logical v1 envelope is:

```text
RevisionEnvelopeV1 {
  revision_id: RevisionId
  entity_id: EntityId
  entity_type: ExactTypeRef
  schema: ExactSchemaRef
  parents: Set<RevisionId>                 // 0, 1, or 2..8
  lifecycle: live | archived | deleted
  payload_digest: PayloadDigest | absent   // absent only for deleted
  origin_device_id: DeviceId
  origin_device_sequence: DeviceSequence
  logical_time: LogicalTimeV1
  command_id: CommandId
  created_by: ActorRef
  accepted_at: WallClockMetadata
  content_migration: ContentMigrationProvenanceV1 | absent
  conflict_resolution: ConflictResolutionProvenanceV1 | absent
}

ContentMigrationProvenanceV1 {
  migration_run_id: MigrationRunId
  migration_step: MigrationStepRef
  source_schema: ExactSchemaRef
  source_payload_digest: PayloadDigest | absent
  target_schema: ExactSchemaRef
  target_payload_digest: PayloadDigest | absent
  validation_digest: Digest
}

ConflictResolutionProvenanceV1 {
  expected_frontier: FrontierRefV1
  selected_parents: Set<RevisionId>          // exactly the envelope parents
  completeness: final | partial_reduction
  method: automatic | manual | choose_branch | lifecycle_choice |
          frontier_reduction
  base_revision_ids: BoundedSet<RevisionId>
  merge_profile: ExactMergeProfileRef | absent
  resolution_input_digest: Digest
}
```

`ExactTypeRef` and `ExactSchemaRef` include stable ID, semantic version, and
contract hash. Parent order has no meaning. Parents are serialized in canonical
`RevisionId` byte order only for hashing, equality, and transport.

`payload_digest` covers the exact schema reference and the type contract's
versioned canonical payload bytes. A type cannot become revisioned until its
contract registers one deterministic canonicalization profile and golden
fixtures. Ambient locale, map iteration order, platform line endings,
floating-point ambiguity, or an implementation-private serializer cannot
participate in the digest.

The revision fingerprint covers every envelope field, including provenance and
wall-clock metadata, plus the canonical parent set and payload digest. Clock
metadata remains non-causal, but disagreement about stored bytes cannot be
silently ignored. A previously known `revision_id` with a different fingerprint
is an integrity conflict and is quarantined; it is never merged as ordinary
content.

The envelope and its required canonical reconstruction path are revisioned
`CE`; they inherit the owning entity's owner, sensitivity, sync, export, backup,
retention, deletion, purge, and loop policy. Only Core's Revision Service writes
envelopes/bodies through registered commands; the owning module validates its
schema but cannot mutate storage directly. Their structural technical purpose
and consumers are canonical history, current-state reconstruction, conflict
handling, integrity, offline replay, export, backup, and recovery. They are not
resettable caches: removal requires the owning `CE` retention/purge policy and
must preserve every retained reference.

`content_migration` is absent for ordinary revisions. ADR-012 is its only v1
writer path. It gives every semantic upgrade a closed provenance carrier that
is covered by the revision fingerprint; migration provenance is not an ad-hoc
side record or mutable annotation.

`conflict_resolution` is absent for ordinary edits and content migrations.
ADR-004's registered resolution/reduction command is its only v1 writer path.
The carrier inherits the revision's `CE` policy, binds the whole frontier at the
decision point, distinguishes final resolution from partial reduction, and is
covered by the revision fingerprint. A derived conflict key may aid diagnostics
but is never copied into canonical revision provenance and never supplies
authority. `content_migration` and `conflict_resolution` cannot both be present.

### 2. Body encodings

A `RevisionBodyV1` is bound to one revision ID and declares an exact encoding
profile and its own integrity digest. The closed v1 modes are:

```text
FullSnapshot {
  schema: ExactSchemaRef
  canonical_payload_bytes: BoundedBytes
}

ParentPatch {
  base_revision_id: RevisionId
  base_payload_digest: PayloadDigest
  patch_profile: ExactPatchProfileRef
  operations: BoundedPatchOperations
  result_payload_digest: PayloadDigest
  patch_depth: PositiveInteger
}

DeletedBody {}
```

A full snapshot must materialize and hash to the envelope payload digest. A
patch is valid only for a live or archived, single-parent revision; its base is
that immediate parent, its schema is unchanged, and deterministic application
to the verified base must produce the result digest. Unknown operations,
duplicate operation identities, out-of-range paths, failed preconditions, or a
different result digest fail closed.

Patch profiles are closed, versioned data contracts implemented by already
registered trusted code. Patch bytes never select storage paths, execute code,
or invoke a handler by a floating name. An entity type without an accepted
patch profile uses snapshots only.

At least one complete reconstructible encoding is committed with every logical
revision. Additional verified snapshot encodings may be materialized later to
bound reads. They are redundant representations of the same canonical payload,
not a new revision or a new source of truth. An invalid encoding is quarantined
locally; another independently verified encoding may be used only after it
reconstructs the same envelope digest.

Those additional materializations are `DD`, owned by Core Revision Storage and
written only by its exact-versioned Revision Materializer processor. Their
inputs are the retained envelope plus canonical reconstruction closure; their
technical purpose/consumers are bounded reads, integrity repair, export
assembly, and recovery. They are excluded from portable export as independent
truth, optional in backup, and safely reset/rebuilt only while a verified
canonical reconstruction path remains.

### 3. Mandatory snapshots and finite patch chains

A full snapshot is mandatory for every payload-bearing:

- a root revision with no parents;
- multi-parent merge, frontier-reduction, or conflict-resolution revision;
- the first revision using a new entity schema or canonicalization profile;
- restoration from a deleted lifecycle state;
- any revision whose patch profile, byte, operation, work, or depth ceiling
  would otherwise be exceeded; and
- any type whose contract does not prove deterministic bounded patch replay.

A `deleted` revision instead has `payload_digest: absent` and `DeletedBody`,
including a multi-parent deleted resolution. It remains a fully parented logical
revision but does not fabricate an empty payload snapshot. An archived revision
still carries content and follows the ordinary snapshot/patch rules.

Each revisioned type declares finite snapshot bytes, patch bytes, operation
count, path depth, reconstruction bytes/work, and `max_patch_depth`. There is no
unbounded value. An implementation may create a snapshot earlier but cannot
extend the declared chain. Concrete production values require benchmark and
cross-platform evidence; the replay spike did not measure them.

The canonical logical revision is not rewritten when a materialized snapshot
is added. Removing a body encoding is forbidden until an accepted retention
and compaction policy proves that the revision and every retained descendant
remain reconstructible, exportable, and integrity-verifiable. Ordinary cache
eviction may remove only explicitly derived materializations, never the last
canonical reconstruction path.

### 4. Graph and head frontier

The authoritative current-state meaning of an entity is the **set of maxima of
its canonical `CE` revision graph**, not a timestamp-selected row. The graph is
the source of truth. The exact set is identified by:

```text
FrontierRefV1 {
  entity_id: EntityId
  head_count: uint64
  head_set_digest: Digest    // digest of sorted FrontierHeadFingerprintV1
}

FrontierHeadFingerprintV1 {
  revision_id: RevisionId
  revision_fingerprint: RevisionFingerprint
}
```

The head-set digest is domain-separated and covers the exact canonical byte
encoding of every `FrontierHeadFingerprintV1`, sorted only by `RevisionId` bytes.
It therefore binds both membership and the already integrity-checked immutable
revision meaning without using order to choose a winner.

Small frontiers may be returned inline; large frontiers are read in bounded,
digest-verified pages. A command binds the whole current frontier by
`FrontierRefV1` and separately lists only the bounded heads it will transform.
The reference is a precondition, not an authority token.

`FrontierRefV1` is a computed concurrency token. If Core persists a frontier
index for atomic admission, that index is `DD`, owned by Core Revision Storage
and written only by its `kernel_service` Revision Frontier Projector from the
exact revision graph and definition version. Its technical consumers are
command preconditions, current-state Query, conflict processing, replay, and
integrity diagnostics. It is excluded from ordinary export, optional/rebuildable
in backup, and may be reset only by a full graph rebuild. Loss or staleness makes
affected writes typed unavailable until rebuild; it cannot lose a canonical
branch or redefine graph maxima.

Graph admission has two levels. A received revision is locally integrity-checked
for typed ID/fingerprint and raw body digest first. If any declared parent or
ancestor is missing, it remains typed pending and is not a head. It becomes
**structurally verified** and frontier-admissible only when the complete declared
ancestry is present, every parent edge belongs to the same entity, the lineage
has the one accepted root, and no cycle exists. Its schema or body profile may
still be unknown. A revision is **domain-materializable** only when compatible
code can reconstruct and validate its payload meaning.

The causal frontier contains every structurally verified maximum, including an
opaque unknown-schema maximum. The readable frontier is only a view over its
materializable subset. If any causal head is opaque, Core reports typed
`CURRENT_STATE_INCOMPLETE`/`UNSUPPORTED_SCHEMA`; it cannot present the known
subset as a sole current state or accept an ordinary edit against it.

Each `EntityId` has exactly one root lineage. The first accepted revision has
zero parents; every later revision must be reachable from that root once its
ancestry is complete. A second root for the same entity, two closed lineages
with no common root, a cycle, or a cross-entity parent is
`ENTITY_LINEAGE_CONFLICT` and is quarantined. V1 has no lineage-graft command;
generic entity copy is also outside v1. A future accepted owning command must
mint a new `EntityId` and define its exact canonical provenance relation.

An ordinary edit has one parent and requires an exact single-head frontier. A
final merge/resolution has 2–8 parents and names the complete frontier. A stale
frontier reference or invalid selected subset returns `REVISION_CONFLICT` with
a safe current `FrontierRefV1` and creates none of the four effects measured by
the spike: command receipt, revision, frontier change, or outbox row.

A valid frontier can contain more than eight concurrent heads after replay. It
must never become impossible to resolve. ADR-004 therefore defines a bounded
**frontier-reduction revision**: one command binds the complete frontier ref,
selects 2–8 current heads as parents, creates one explicit payload-bearing full
snapshot or one deleted body, and leaves every unselected head unchanged. The
result replaces only its named parents, reduces head count by at least one, and
records `conflict_resolution.completeness = partial_reduction`; it never claims
that the entity conflict is resolved.
Repeated bounded reductions eventually permit one final 2–8-parent resolution
without deleting ancestry. Unknown-schema heads remain blocking until a
compatible handler can validate their reduction input.

ADR-012 defines one additional branch-preserving content-migration operation.
It binds the complete frontier and atomically creates exactly one child for
every head: a full snapshot for live/archived content and `DeletedBody` for a
deleted head. It cannot commit a subset, join branches, or claim conflict
resolution. If the complete frontier exceeds the declared migration batch,
explicit frontier reduction is required first.

Future replay may introduce valid descendants that were independently accepted
from the same ancestor. All remain heads. A child removes only its named parent
heads and adds itself; arrival order, wall clock, device sequence, logical time,
lexical ID order, or body mode never selects a winner. A missing parent remains
typed pending and does not block independent entities or events.

For v1, undo and branch selection create a new revision whose payload copies
the selected historical state. With 2–8 heads it names the whole frontier; with
more heads it is an explicitly partial frontier reduction. Nabla does not
silently move a mutable head pointer back into history. Archive, delete,
restore, and correction likewise create revisions. A deleted revision has no
active payload body, retains its parents and history, and is not physical purge.

### 5. Atomic command boundary and replay

One local transaction accepts a revision-producing command and atomically
persists:

- the scoped idempotency outcome and command receipt;
- the allocated device sequence and logical-time observation;
- the immutable revision envelope and initial body encoding;
- the exact frontier transition; and
- the versioned outbox event for a syncable type.

Before commit none of these effects is visible. After commit, retrying the same
scope/key/fingerprint returns the stored receipt without another revision or
outbox event. Delivery remains at-least-once; duplicate suppression and local
effect-once require a transactional inbox/effect receipt at the consumer.
Exactly-once network or external-effect semantics are not claimed.

Replay is parent-gated and idempotent by exact revision/event identity. It uses
finite passes or work queues, leaves unresolved dependencies typed and
inspectable, and continues independent work. Canonical sorting is permitted for
stable serialization and comparison but not for choosing a concurrent head.

### 6. Conflict, migration, export, and failure boundaries

ADR-004 merge operates on fully materialized, digest-verified snapshots. A
payload-bearing multi-parent result receives a full snapshot, while a deleted
result receives `DeletedBody`; neither depends on an arbitrary primary parent.
Open conflicts retain all heads, bases, and body encodings required for
resolution.

ADR-012 physical migrations may change tables, indexes, compression, or body
placement but cannot change a revision ID, parent set, schema meaning, lifecycle,
or payload digest. A semantic content upgrade creates a new revision with
`content_migration` provenance: payload-bearing heads use full snapshots and
deleted heads use `DeletedBody`. It never edits an old revision in place.
Unknown schema or patch profiles are preserved as structurally verified opaque
causal heads and read-only/exportable records until compatible code is
available.

Export of a revision includes its envelope, exact schema/profile references,
and a closed reconstruction bundle containing either a verified snapshot or
the complete bounded patch/base closure. A partial export cannot claim that a
revision is restorable. Derived materializations are optional and rebuildable.

Failures are localized as follows:

| Condition | Result |
|---|---|
| stale or partial expected frontier | `REVISION_CONFLICT`; no command receipt, revision, frontier change, or outbox row; audit/log policy separate |
| missing parent/body dependency | `MISSING_PARENT` or `REVISION_BODY_UNAVAILABLE`; typed pending |
| same ID with different fingerprint, cycle, second root, cross-entity parent | `REVISION_INTEGRITY_CONFLICT` / `ENTITY_LINEAGE_CONFLICT`; quarantine |
| unknown schema or patch profile | preserve opaque causal head; current state incomplete |
| finite encoding/replay limit exceeded | `REVISION_LIMIT_EXCEEDED`; no partial revision |
| body/result digest mismatch | `REVISION_INTEGRITY_CONFLICT`; quarantine encoding |

A corrupt body or unresolved branch does not damage another entity, block
maintenance export of unaffected data, or authorize deletion. Recovery and
purge remain separate explicit policies.

## Compatibility constraints

1. Entity identity is stable and revision identity never depends on a path,
   title, wall clock, current head, or storage location.
2. A revision and every parent are immutable; representations must reconstruct
   one exact versioned payload digest.
3. Concurrent graph maxima, including opaque maxima, remain heads; final
   resolution names the whole frontier and large frontiers reduce only through
   explicit ancestry-preserving partial revisions.
4. Snapshot versus patch cannot change public content, conflict, ordering,
   authorization, export, or migration semantics.
5. Payload-bearing root, multi-parent, schema-changing, restore, and over-limit
   revisions use full snapshots; deleted revisions use `DeletedBody`.
6. Missing or unknown data fails closed and remains locally isolated.
7. Physical migration and derived compaction cannot rewrite logical history.
8. Tombstone is a revision; physical destruction requires the separate purge
   boundary.

## Consequences

### Positive

- Full checkpoints give bounded reconstruction while patches may reduce common
  single-parent write amplification.
- Logical revision identity remains stable if physical storage evolves.
- Mandatory merge snapshots remove primary-parent ambiguity.
- Exact frontiers and immutable ancestry make conflict, replay, export, and
  recovery evidence auditable.

### Costs and risks

- Hybrid storage needs validators for both snapshot and every registered patch
  profile.
- Retaining immutable history and reconstruction closure costs storage.
- A corrupt base can affect descendant patch readability until another verified
  snapshot is available, although the failure remains localized.
- Numeric limits and production performance remain unmeasured.

## Alternatives considered

| Alternative | Disposition | Reason |
|---|---|---|
| Full snapshot for every revision | Rejected as the only representation | Simple and spike-compatible, but its production storage/write cost was not measured and it prevents safe type-specific deltas. |
| Patch for every non-root revision | Rejected | Long chains amplify corruption, latency, export closure, and migration risk; merge base is ambiguous. |
| Hybrid with mandatory checkpoints | Selected | It preserves one semantic model while bounding replay and allowing measured future optimization. |
| Mutable row plus audit log | Rejected | It cannot prove immutable historical content or preserve concurrent branches. |
| Content hash as revision ID | Rejected | Equal payloads can be distinct causal revisions, metadata changes matter, and hash/profile evolution must not remap identity. |
| Timestamp-selected single head | Rejected | It violates `CON:I3` and loses offline branches. |

## Validation obligations

Before production revision storage is accepted, evidence must cover:

1. golden canonical payload/fingerprint fixtures on Desktop and Mobile;
2. one-root enforcement, single-parent, 2-parent, 8-parent, and 9-plus-head
   frontier reduction without branch loss;
3. snapshot/patch equivalence and `N-1/N/N+1` for every finite limit;
4. wrong base, wrong schema, unknown operation, duplicate operation, digest
   mismatch, missing body, cycle, and cross-entity parent rejection;
5. reconstruction at depth 0, 1, `max-1`, `max`, and forced checkpoint;
6. stale, subset, changed, inline/paged exact frontier refs and atomicity with
   zero-effect proof for command/revision/frontier/outbox;
7. two offline descendants, arrival permutations, duplicates, missing parents,
   and deterministic final frontiers;
8. crash before commit, after commit/before response, consumer before ack, and
   same-key retry;
9. archive, tombstone, restore, undo-copy, payload-bearing snapshot and deleted
   multi-parent history/export behavior;
10. unknown schema/profile opaque-head preservation, incomplete-current state,
    and maintenance export with inactive domain code;
11. physical migration that preserves IDs, parents, fingerprints, digests, and
    reconstruction bundles;
12. corruption and resource fault injection proving independent entity access,
    export, backup, and recovery remain available;
13. benchmark evidence for concrete snapshot, patch, depth, memory, and work
    limits before those values become production claims.

## Deferred decisions and unmeasured assumptions

This ADR does not choose DDL, a database, compression, encryption, concrete
patch algorithms, per-type numeric limits, compaction/GC, retention, purge,
network sync, or automatic conflict resolution. The replay spike used SQLite
full snapshots at selected process-kill checkpoints; it did not prove power-loss
durability, cross-platform conformance, production scale, or hybrid performance.

## Supersession rules

A later specification may define concrete body profiles, limits, storage ports,
and indexes without superseding this ADR only if it preserves the logical
envelope, exact payload digest, immutable parent graph, set-valued frontier,
mandatory snapshot cases, bounded reconstruction, and failure behavior above.
Changing any of those semantics requires an accepted superseding ADR.

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
- Accepted `ADR-003`: exact stable references and no silent compatibility
  rebinding for future persisted saved queries.
- Approved `REVISION-SYNC-PREPARATION-SPIKE-v1`: 7 cases, 124 assertions,
  semantic digest
  `f60a38c640d5b8c7bdd9b3f6bdbf727f3ebf9932746c04494421790495223771`;
  raw result SHA-256
  `b9ea6908f265440f36add96ac2f8123ea37e50610e3e6360dd81a75e1e0a3b9c`.
- Approved `SPEC-NAVIGATION.md` v0.4: `NAV:6` execution and evidence protocol.
- Prepared task context manifest:
  `6785c3183b4f810a523888e32152edec74db73f40a128cfdcd1a93bba1b84185`.

## Approval

Owner approval is pending. Until explicit approval, this ADR remains Proposed,
`governance/decisions.yaml` keeps ADR-002 `required`,
`ADR-REVISION-IDENTITY-001` remains `ready`, and no successor is activated.
