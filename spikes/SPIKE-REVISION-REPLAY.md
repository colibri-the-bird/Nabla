# SPIKE-REVISION-REPLAY-001: offline revision, outbox and replay preparation

| Field | Value |
| --- | --- |
| Task | `SPIKE-REVISION-REPLAY-001` |
| Artifact | `REVISION-SYNC-PREPARATION-SPIKE-v1` |
| Report state | Measured publication candidate; owner approval pending |
| Measurement date | 2026-08-01 |
| Prepared context manifest | `878d7770560e6eb7fc61ec5a8353f47e2a68ed6fc37ef08636aae2b25a40ab94` |
| Raw result | `tests/spikes/revision-replay/results/windows_x86_64.json` |
| Raw result SHA-256 | `b9ea6908f265440f36add96ac2f8123ea37e50610e3e6360dd81a75e1e0a3b9c` |
| Semantic result digest | `f60a38c640d5b8c7bdd9b3f6bdbf727f3ebf9932746c04494421790495223771` |

## Question and boundary

The spike asks whether a small offline runtime can preserve the already active
identity, revision, optimistic-concurrency, transactional-outbox, idempotency,
and replay constraints before a runtime boundary or revision schema is chosen.

The experiment is test-only. It does not implement network synchronization or
production persistence, and it does not select revision DDL, a backend, an ID
encoding, a snapshot/patch representation, transport semantics, or a conflict
resolution policy.

## Reproducible setup

The standard-library harness is in `tests/spikes/revision-replay/`. It creates
isolated SQLite databases under a temporary root, uses deterministic fixture
inputs, and records semantic state through canonical sorted JSON. No temporary
path, PID, duration, timestamp, unordered SQL result, or wall clock participates
in a pass condition or semantic digest.

Measured environment:

- Windows 11 x86_64;
- Python 3.12.7;
- SQLite 3.45.3;
- SQLite `journal_mode=WAL` and `synchronous=FULL`;
- fixture SHA-256
  `aeaa5aaec57884bf7acc73134d9cf6174e0404caf49b87cc3816c3414706a4d3`.

Three process-kill points are coordinated by durable marker files rather than
timing:

1. producer writes the transaction but is killed before commit;
2. producer commits and is killed before returning the result;
3. consumer commits its local inbox receipt and effect, then is killed before
   producer acknowledgement.

The measured commands were:

```text
python -B tests/spikes/revision-replay/run_experiment.py --output tests/spikes/revision-replay/results/windows_x86_64.json
python -B tests/spikes/revision-replay/run_experiment.py --verify tests/spikes/revision-replay/results/windows_x86_64.json
```

The output command produced the checked-in raw result. The recorded acceptance
verifier exited `0` and reported `verification=match`.

## Results

Seven cases and 124 assertions passed.

| Scenario | Bounded observation | Result |
| --- | --- | --- |
| Offline identity | 256 candidates on each of two devices; forward and reverse generation | 512 unique, 0 collisions, identical set digest |
| Revision graph | shared ancestor, two independent offline descendants, explicit two-parent merge, tombstone | two heads preserved; merge and tombstone each moved the frontier without deleting history |
| Stale optimistic conflict | ordinary command against the former head | `REVISION_CONFLICT`; command/revision/head/outbox delta all 0 |
| Partial merge conflict | merge intent naming only one of two heads | rejected with the full two-head frontier; command/revision/head/outbox delta all 0 |
| Idempotency | same scope/key/fingerprint retry; six changed-fingerprint variants; same literal key in five complete scopes | original receipt returned once; all mismatches gave `IDEMPOTENCY_CONFLICT`; scopes remained independent |
| Producer crash | kill before commit and kill after commit-before-response | before: 0 command/revision/head/outbox rows; after: exactly 1 of each; same-key retry added 0 effects |
| Delivery crash | duplicate delivery and kill after local consumer commit but before producer ack | two attempts, one local effect; retry was `DUPLICATE_SUPPRESSED`; outbox ended acknowledged |
| Dependency/replay | child before parent, one unresolvable parent, all 24 permutations of root/A/B/merge with duplicates | typed `MISSING_PARENT`; independent event applied; 24 final states had one digest, at most 3 passes under bound 6 |

### Identity

The fixture candidate function accepts only kind, origin device, and local
sequence. Its 512-value sample had no collision, and reversing device and
sequence traversal produced the same mapping and digest. This demonstrates the
mechanics of device-scoped sequence input without wall-clock causality.

It does not prove global collision freedom. The deterministic SHA-256 prefix is
only a reproducible fixture encoding; production entropy, namespace, device
provisioning, clone handling, and exact entity/revision/event ID formats remain
unselected.

### Immutable revision frontier and conflict

An attempted revision update was rejected by the experimental immutable-store
guard and left the ancestor payload unchanged. An ordinary command whose
`expected_revision` referenced the former ancestor returned the complete
current frontier and created no command receipt, revision, head change, or
outbox entry.

The two concurrent heads were not produced by accepting a stale command in one
store. Device A and device B each created a valid descendant while independently
based on the same ancestor; replaying both descendants preserved both heads.
This distinction is required to keep optimistic concurrency and offline branch
preservation compatible.

The experimental logical sequence followed graph depth: ancestor 1, both
concurrent descendants 2, merge 3, and tombstone 4. Device-local sequences were
A: 1/2, B: 1, and C: 1/2. Equal logical depth did not select a winner, and a
device-local number was never compared as a global total order.

A partial merge intent was rejected with both current heads. The successful
fixture merge named both heads as parents and reduced the frontier to one merge
revision. The old branches remained immutable and reachable. The merge payload
was supplied explicitly by the fixture, so this result says nothing about an
automatic merge algorithm or user experience.

A later tombstone was another revision with the merge as parent. Five revisions
remained replayable after it became the sole head; no purge, retention, or
garbage collection behavior was exercised.

### Scoped idempotency

The experiment stored idempotency under the complete measured scope:

```text
(verified_actor, origin_device, capability_id, major_version, idempotency_key)
```

The fingerprint covered target entity, exact capability version, contract hash,
canonical payload, expected revisions or merge intent, tombstone intent, and
stable options. A retry with a new request ID and a new proposed command ID returned
the original committed receipt and command ID, with zero additional command,
revision, head, or outbox effect.

Changing target entity, payload, expected revisions, exact version, contract
hash, or stable options under the same scope and key produced six typed
`IDEMPOTENCY_CONFLICT` results. Reusing the literal key in a different actor,
device, capability, or major-version scope created independent intents.

The test did not model a non-transactional external effect, unknown effect
status, idempotency-record retention, or the lifecycle of an uncommitted first
intent.

### Transaction and crash boundaries

At the pre-commit checkpoint, killing and reopening the producer left zero
command receipts, revisions, heads, outbox rows, and committed device counters.
At the post-commit/pre-response checkpoint, reopening showed exactly one
command receipt, revision, head, and outbox row. Repeating the same scoped intent
returned the stored receipt without another effect, and the next committed
device sequence was 2.

This supports one local transaction boundary for command acceptance,
idempotency receipt, device-sequence allocation, immutable revision, frontier
update, and outbox append in the measured adapter.

At the consumer checkpoint, the local consumer effect and inbox receipt had
committed while the producer outbox remained pending. Redelivery found the
receipt, suppressed the duplicate effect, and then acknowledged the producer
outbox. The accurate claim is at-least-once handoff with effect-once behavior
for a transactional local consumer. The experiment does not establish
exactly-once transport, external effects, or distributed transactions.

### Causal and deterministic replay

A child delivered before its parent produced `MISSING_PARENT`, a durable typed
pending row, and no partial effect. Once the parent arrived, both events applied
and the child became the head. A separate event with a permanently missing
parent reached a fixed point in two passes and stayed typed pending, while an
independent root event still applied.

The complete root/branch-A/branch-B/merge set was replayed under every one of
its 24 arrival permutations. Each schedule also injected two duplicate
deliveries. All schedules drained their causal dependencies, retained the merge
as sole head, and produced the same semantic digest
`18df030d5ca57c8277b99352dfceb7025ac562e2afd8f254d02dbb95b1dccee7`.
The maximum observed drain was 3 passes under the explicit bound of 6.

Parent availability determined application. Per-device sequence was not
treated as a global order, and canonical sorting was used only for comparison
and serialization—not to choose a winning concurrent head.

## Normative properties exercised, not reopened

The measurements are consistent with and do not replace the active sources:

- immutable parented revisions and a set-valued head frontier;
- no silent overwrite or wall-clock last-write-wins;
- offline operation as a baseline;
- optimistic revision conflict;
- the specified idempotency scope;
- transactional outbox and versioned events;
- bounded work and localized failure.

## Inputs for ADR-RUNTIME-BOUNDARY-001

The measured successor inputs are:

1. one local atomic boundary for command acceptance, scoped idempotency receipt,
   device sequence, revision, head update, and outbox append;
2. atomic monotonic local sequence allocation after the runtime receives the
   already normative device identity; device provisioning and identity
   durability were not measured;
3. a replay-worker boundary separating outbox attempt, transactional local
   inbox/effect receipt, and producer acknowledgement;
4. at-least-once handoff with effect-once limited to adapters that can transact
   the local effect and receipt together;
5. causal dependency buffering, finite drain bounds, typed unresolved state,
   and failure isolation between independent events;
6. persistence-port requirements for atomicity, uniqueness, restart recovery,
   and deterministic canonicalization;
7. a versioned event envelope whose delivery order is separate from revision
   graph semantics.

These are evidence for the runtime-boundary decision. The spike does not make
that ADR decision.

## Deferred decisions and unmeasured claims

- production entity, revision, command, and event ID encodings;
- device enrollment, rotation, cloning, and global collision strategy;
- production logical-sequence computation and event-envelope shape/version
  lifecycle;
- revision DDL, indexes, backend, and snapshot/patch/hybrid representation;
- exact multi-head command API and merge-intent representation;
- automatic conflict resolution and merge UX;
- network transport, authentication, reconciliation, cursors, backpressure,
  and synchronization;
- external-effect exactly-once semantics and distributed transactions;
- failed-intent retention and version-pinning lifecycle;
- compaction, retention, tombstone collection, and purge;
- production durability, power-loss, corruption, performance, scale, capacity,
  timeout, and retry thresholds;
- runtime portability and extension boundaries owned by
  `ADR-RUNTIME-BOUNDARY-001`.

Process termination at three named checkpoints is narrower than power loss or
an arbitrary instruction-boundary crash. SQLite results do not select SQLite as
the production backend or establish behavior for another adapter.

## Publication and successor gate

This report is a measured publication candidate. Until explicit owner approval:

- `REVISION-SYNC-PREPARATION-SPIKE` remains `required`;
- `SPIKE-REVISION-REPLAY-001` remains `ready`;
- `ADR-RUNTIME-BOUNDARY-001` remains `blocked`.

After owner approval is recorded, the intended final transition is to mark the
artifact available with this report reference, complete this spike card, and
activate `ADR-RUNTIME-BOUNDARY-001` as the sole successor. No other successor is
authorized by this task.
