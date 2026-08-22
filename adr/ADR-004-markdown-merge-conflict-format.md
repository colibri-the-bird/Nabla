# ADR-004: Deterministic Markdown merge and explicit conflict format

- **Status:** Proposed — owner approval required
- **Date:** 2026-08-22
- **Task:** `ADR-REVISION-IDENTITY-001`
- **Decision owner:** Nabla project owner
- **Related decisions:** `ADR-002`, `ADR-009`, `ADR-012`
- **Supersedes:** None

## Context

Concurrent offline edits can produce several descendants of one revision.
`CON:I3` requires every branch to survive until an automatic or user resolution
and prohibits silent last-write-wins. The active draft Architecture calls for
deterministic fast-forward, three-way merge where supported, explicit conflict
state otherwise, and a resolution revision with multiple parents. Knowledge
and Documents further require branches and unknown schemas to remain
exportable, delete-versus-revise to be explicit, and anchor or active-version
conflicts not to be guessed away.

Markdown is source text, not a stable universal abstract syntax tree. Parser
versions can disagree about malformed input, extensions, whitespace, source
ranges, and serialization. A parser-driven rewrite could therefore change
content even when a user did not edit that region. Conversely, raw Git-style
markers stored inside canonical Markdown conflate unresolved state with user
content and make literal marker text ambiguous.

`REVISION-SYNC-PREPARATION-SPIKE-v1` measured preservation of two heads,
rejection of a partial merge intent with no command receipt, revision, frontier
change, or outbox row, a successful explicit two-parent fixture merge, typed
missing-parent buffering, duplicate suppression, and one final digest across
all 24 arrival permutations. The maximum drain was 3 passes under a bound of 6.
It did not measure audit/log behavior for rejected intent or exercise a Markdown
algorithm, merge bases, Unicode/line endings, more than two heads, persisted
conflict records, delete-versus-revise, unknown schemas, or merge UX.

## Decision

### 1. Frontier is the conflict authority

For a revisioned entity, the authoritative conflict input is the exact current
head frontier defined by ADR-002. Heads are a semantic set. Canonical ID sorting
is used only for equality, serialization, hashing, and stable display grouping;
it never chooses a winner.

A merge command supplies the exact ADR-002 `FrontierRefV1` plus its bounded
selected heads. Core compares the reference atomically with the full current
frontier before expensive merge work is committed. A stale, partial, duplicate,
or foreign-entity selection returns `REVISION_CONFLICT` with a safe current
frontier ref and creates none of the four effects measured by the spike:
command receipt, revision, frontier change, or outbox row. Logging/audit policy
for a rejected attempt is a separate unmeasured contract and is not claimed as
zero-effect here.

Missing parents yield typed pending `MISSING_PARENT`. Cycles, cross-entity
parents, a second root/no-common-root closed lineage, or the same revision ID
with a different fingerprint are integrity failures and quarantine, not
user-resolvable content conflicts. V1 cannot graft unrelated lineages through
a Markdown resolution.

### 2. Automatic Markdown merge eligibility

The v1 automatic profile is
`nabla.markdown-line-three-way/1.0.0`. It is eligible only when:

- the exact frontier contains two and only two concurrent heads;
- both heads and their required ancestry are present and digest-verified;
- both heads use the same compatible Markdown payload schema and canonical
  line profile;
- there is exactly one maximal common ancestor;
- the exact merge-profile ID, version, and contract hash are registered; and
- all input-derived ancestry, byte, line, hunk, and output ceilings pass, and
  runtime admission separately grants a finite execution budget.

The set of maximal common ancestors is computed from revision ancestry, not
wall clock, device sequence, logical time, or ID order. Multiple maximal common
ancestors, 3 or more heads, an unknown schema, an inactive owner module, or an
unsupported profile requires explicit resolution/reduction. No common root in
a closed ancestry is ADR-002 `ENTITY_LINEAGE_CONFLICT`, not a user merge base.
V1 does not synthesize a recursive virtual base or fold several heads in an
arbitrary order.

### 3. Source-preserving three-way profile

The profile operates on the exact canonical Markdown source and never
round-trips through a Markdown parser.

1. Content is already canonical valid UTF-8 with LF line endings according to
   its payload schema. The final-newline bit is significant. The merge profile
   performs no Unicode normalization, case folding, whitespace cleanup, EOL
   conversion, or syntax formatting.
2. Base, left, and right are tokenized into exact line tokens including their
   terminators. Empty lines, trailing spaces, and the absence of a final LF are
   preserved.
3. Base-to-head edits are produced by the versioned reference diff algorithm.
   Its shortest-edit tie break and adjacent-hunk coalescing rules are part of
   the profile and have cross-platform golden fixtures; an implementation may
   optimize only if it yields identical normalized hunks.
4. The equality shortcuts are exact: `left == right` yields that value;
   `left == base` yields right; `right == base` yields left.
5. Non-overlapping normalized hunks are applied in base position order. Exact
   identical replacements of the same base interval are applied once.
6. Divergent replacements of overlapping intervals, delete-versus-change, or
   non-identical insertions at the same base boundary are unresolved. V1 does
   not order concurrent insertions by device, time, hash, or ID.
7. The merged bytes must satisfy the same schema, digest, and finite limits.
   A Markdown parser may validate or diagnose a candidate but cannot rewrite
   canonical source or turn parser recovery into hidden merge semantics.

Typed envelope fields outside the Markdown body use the same exact three-way
equality shortcuts. A field changes automatically only on one side or to an
identical value on both sides. Maps, lists, lifecycle, anchors, relations, and
other structured values are atomic unless their owning accepted contract
registers a separate exact merge profile. ADR-004 does not invent a generic
relation or anchor merge.

### 4. Conflict descriptor is deterministic derived state

The canonical conflict is the revision graph plus its exact ADR-002 frontier.
`ConflictDescriptorV1` is a rebuildable `DD` projection for bounded diagnosis
and resolution; it is not a second mutable source of conflict truth:

```text
ConflictDescriptorV1 {
  conflict_key: ConflictKey
  entity_id: EntityId
  frontier: FrontierRefV1
  frontier_pages: FrontierPageSummaryV1
  base_candidate_count: uint64
  base_candidate_set_digest: Digest
  base_candidate_sample: BoundedSet<RevisionId>
  merge_profile: ExactMergeProfileRef | absent
  reasons: BoundedSet<ConflictReason>
  regions: BoundedList<BoundedConflictRegion>
  definition: ExactProcessorRef
  canonical_input_digest: Digest
  descriptor_digest: Digest
}

FrontierPageSummaryV1 {
  page_count: uint64
  page_size_profile: ExactPageProfileRef
  page_digest_root: Digest
}

BoundedConflictRegion {
  kind: text | field | lifecycle | schema
  base_span: TokenSpan | absent
  head_spans: BoundedMap<RevisionId, TokenSpan | absent>
  slice_digests: BoundedMap<RevisionId, Digest>
}
```

`conflict_key` is a domain-separated digest of the entity ID, full frontier
digest/count, full base-candidate count/set digest, and the exact merge profile
or an explicit `absent` tag. It is a derived hash, not ADR-009 `NablaIdV1`, an
authority token, or a substitute for current frontier validation. Large head or
base sets are represented by count/digest commitments and bounded pages/samples,
not copied into one unbounded descriptor. `merge_profile` is absent when schema
or profile resolution itself failed; the processor definition and absence tag
still make the descriptor deterministic. Page construction and any displayed
base sample use the exact page profile and canonical ID-byte order; that order
is diagnostic only and cannot select content or a merge base.

The closed v1 reason set is:

```text
overlapping_text
field_divergence
delete_vs_revise
ambiguous_base
unknown_schema
unsupported_profile
n_way_manual_required
deterministic_static_limit_exceeded
```

Regions contain bounded positions and digests, not copied raw note/document
text. The owning entity contracts still govern access. Core's Revision
Conflict Processor is the sole `processor` writer; exact graph/frontier/body
inputs, merge-profile and processor versions, and parameters give it a complete
rebuild path. Its technical purpose and consumers are conflict Query/UI,
resolution preflight, diagnostics, and maintenance export. Dropping every
descriptor cannot remove a branch or change current state.

`open`, `resolved`, and `superseded` are computed from the current frontier and
resolution ancestry, not stored as mutable meaning. A migration or resolution
changes canonical graph inputs; the processor deterministically builds the new
descriptor and may discard the stale projection. Descriptor failure marks only
the conflict projection unavailable.

Generated `<<<<<<<` marker buffers may exist only as transient, clearly
labelled UI projections. They are never stored as a canonical merge result,
revision body, descriptor excerpt, event, or audit payload. Literal marker-like
text authored by a user remains ordinary Markdown and is not globally banned.

### 5. Resolution always creates a revision

Every automatic, manual, or branch-selection action creates a new ADR-002
revision. A payload-bearing result uses `FullSnapshot`; a deleted result uses
`DeletedBody`. It never mutates a branch and never merely moves a pointer.

The resolution command declares:

```text
entity_id
expected_frontier: FrontierRefV1
selected_parents: Set<RevisionId>          // 2..8 current heads
conflict_key: ConflictKey | absent         // diagnostic DD binding, not authority
resolution_method: automatic | manual | choose_branch | lifecycle_choice |
                   frontier_reduction
base_revision_ids: BoundedSet<RevisionId>
merge_profile: ExactMergeProfileRef | absent
resolved_payload or deleted lifecycle intent
resolution_input_digest
```

The committed revision maps `expected_frontier`, `selected_parents`,
`base_revision_ids`, `merge_profile`, and `resolution_input_digest` directly
into ADR-002 `ConflictResolutionProvenanceV1`; `resolution_method` maps to
`method`. `frontier_reduction` maps to `completeness = partial_reduction`, and
every other successful whole-frontier resolution maps to `final`. `entity_id`,
target lifecycle, and resolved payload remain in the ordinary envelope/body.
If supplied, `conflict_key` is only a validated hint against current `DD`; it is
not copied into the canonical revision. The provenance carrier is immutable
`CE`, whereas the descriptor and key remain discardable `DD`.

When the frontier has 2–8 heads, final resolution selects and names all of them
as parents. When it has more than 8, `frontier_reduction` binds the whole
frontier but selects 2–8 parents; its new head replaces only those parents,
leaves every other head unchanged, and records `partial`. Each reduction must
decrease the head count and is itself ancestry-preserving. Repeated reductions
make final resolution possible without an unbounded parent list.

`choose_branch` copies the selected materialized payload into the new revision;
it does not discard the other selected or unselected branches. A compatible
active handler validates every selected input and target schema before commit.
Core cannot generically reduce or choose an opaque unknown-schema head and
declare it valid current content.

One transaction records idempotency/command outcome, the full-snapshot or
deleted resolution/reduction revision, the exact frontier transition,
its `conflict_resolution` provenance, required audit, and outbox event. Previous
heads, bases, and bodies remain reachable and exportable; conflict descriptors
are rebuilt from the new graph. Retention/purge remains a separate boundary.

### 6. Lifecycle and schema conflicts

Concurrent `deleted` or `archived` versus live revision is never resolved by
time or by preferring deletion. It produces `delete_vs_revise`. An explicit
resolution creates either:

- a deleted multi-parent revision with `DeletedBody`; or
- a live/archived full-snapshot revision restoring or merging the chosen
  content.

Two exact-identical lifecycle changes may pass the normal equality shortcut,
but purge is never a merge result.

Unknown or incompatible schema/profile branches are retained opaque,
read-only, and exportable. Automatic merge resumes only after exact compatible
code is available or ADR-012 creates an explicit semantic-upgrade revision.
Physical migration cannot silently upcast a branch, change a conflict key, or
alter the frontier.

### 7. Failure and bounded-work semantics

Conflict detection and merge evaluation have finite input-derived ceilings for
bytes, lines, ancestry nodes, selected heads, hunks, regions, and output bytes.
Crossing one deterministically yields the derived reason
`deterministic_static_limit_exceeded` for the exact frontier and stores no
partial candidate.

CPU admission, memory pressure, deadline, cancellation, retry exhaustion, I/O,
or internal failure is operational and may vary by platform/runtime. It returns
a typed error with zero revision/frontier effect and does not create a semantic
reason or descriptor result. A later retry against the same frontier may
succeed.

Failure of a Markdown parser, suggestion engine, or conflict UI leaves the
revision graph and descriptor intact. It does not block unrelated entities,
offline history, maintenance export, backup, or recovery.

## Compatibility constraints

1. Head order, wall clock, device sequence, logical time, and lexical IDs never
   choose content.
2. Automatic Markdown merge is limited to two heads, one maximal common
   ancestor, one exact compatible profile, and bounded verified inputs.
3. Canonical Markdown is source-preserving; generated conflict markers are UI
   projections only.
4. Final resolution names the complete 2–8-head frontier; larger frontiers use
   explicit partial reductions that preserve unselected heads and ancestry.
   Payload results are full snapshots and deleted results use `DeletedBody`.
5. Unknown schemas, lifecycle disagreement, ambiguous bases, and n-way heads
   remain explicit and exportable.
6. Stale intent and operational failure create no revision or frontier mutation;
   the measured stale-selection case also lacked command receipt and outbox row,
   while contract-specific audit/log behavior remains separate.
7. Physical migration cannot reinterpret or erase a conflict.

## Consequences

### Positive

- Conservative textual semantics avoid parser-version rewrites.
- Exact frontier and base rules make results deterministic across platforms.
- Rebuildable descriptors expose machine-readable conflict state without
  marker ambiguity or a second canonical truth.
- Full-snapshot resolutions remain reconstructible independently of a chosen
  parent patch chain.

### Costs and risks

- Same-line or same-boundary edits conflict more often than heuristic tools.
- V1 does not automatically merge more than two heads or criss-cross histories.
- Retained ancestry consumes canonical storage; optional descriptor projections
  consume rebuildable derived storage.
- The algorithm and UI have not yet been measured on large real Markdown or
  mobile hardware.

## Alternatives considered

| Alternative | Disposition | Reason |
|---|---|---|
| Conservative exact line three-way merge | Selected | Source-preserving, bounded, testable, and independent of parser recovery. |
| Markdown AST merge and reserialization | Rejected for v1 | Parser/extensions/formatting can change unedited source and compatibility. |
| Store Git conflict markers as content | Rejected | It confuses unresolved state with user-authored Markdown and can leak into export/query. |
| Timestamp or device-priority winner | Rejected | It silently loses a valid offline branch. |
| Arbitrary automatic pairwise fold of 3–8 heads | Rejected | Hidden fold order changes outcomes; explicit frontier reduction instead binds the full frontier and records selected parents. |
| Recursive synthetic merge bases | Deferred | It needs a separately versioned, measured profile and stronger graph evidence. |
| Mutable canonical conflict row | Rejected | The graph/frontier is truth; descriptor is a deterministic rebuildable projection. |

## Validation obligations

Before production Markdown merge is accepted, evidence must cover:

1. unique, ambiguous, missing, and no-common-root ancestry; second roots,
   cycles, and foreign parents remain integrity failures;
2. exact/stale/subset inline and paged frontiers; 2, 3, 8, 9, and larger-head
   reductions reach final resolution without branch loss;
3. equality, one-sided, disjoint, identical-overlap, divergent-overlap,
   deletion, and same-boundary insertion fixtures;
4. duplicate lines, blank lines, trailing spaces, EOF/no-final-LF, literal
   marker text, Unicode, and rejected noncanonical EOL/encoding;
5. golden diff hunk and merged-byte fixtures on Desktop, Mobile, and a reference
   evaluator;
6. proof that no generated markers or raw conflict excerpts enter canonical
   payloads or descriptors, and that diagnostics follow the owning contract;
7. `delete_vs_revise`, archive/live, unknown schema, inactive module, and
   unsupported-profile preservation/export;
8. `N-1/N/N+1` for deterministic bytes, lines, selected heads, ancestry, hunks,
   regions, and output plus operational memory/deadline failures that create no
   semantic descriptor;
9. stable derived conflict keys/digests, full rebuild after deletion, and one
   descriptor result across replay permutations;
10. automatic, manual, choose-branch, partial reduction, live full-snapshot,
    and deleted-body resolution with historical reachability;
11. crash before and after the atomic resolution commit and idempotent retry;
12. physical/content migration cases proving physical stability and
    deterministic descriptor rebuild/replacement for branch-preserving upgrades;
13. fault isolation for parser, UI, storage body, and suggestion failures;
14. benchmark and UX evidence before claiming acceptable large-file latency or
    automatic-merge rate.

## Deferred decisions and unmeasured assumptions

This ADR does not select a Markdown parser, UI, diff library, concrete limits,
anchor/relation merge, more-than-two-head automatic merge, recursive merge
bases, network sync, retention, or purge. The exact normalized shortest-edit
algorithm and canonical payload encoding must be published with golden fixtures
before implementation freeze. The replay spike supplied graph/atomicity input
only; it did not validate Markdown semantics or performance.

## Supersession rules

A compatible specification may publish the exact diff profile, wire format,
limits, UI projection, and domain field profiles without superseding this ADR
only if it preserves conservative source text, complete-frontier binding,
ancestry-preserving reductions, deterministic derived descriptors, no canonical
markers, snapshot/deleted resolution modes, and explicit unknown/lifecycle/n-way
conflict behavior. Relaxing any boundary requires an accepted superseding ADR.

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
- Approved `REVISION-SYNC-PREPARATION-SPIKE-v1`: partial-frontier rejection with
  no command receipt, revision, frontier change, or outbox row; two-parent
  merge; typed missing parents; 24 convergent schedules; maximum 3 passes under
  6; semantic digest
  `f60a38c640d5b8c7bdd9b3f6bdbf727f3ebf9932746c04494421790495223771`;
  and raw-result SHA-256
  `b9ea6908f265440f36add96ac2f8123ea37e50610e3e6360dd81a75e1e0a3b9c`.
- Approved `SPEC-NAVIGATION.md` v0.4: `NAV:6` execution and evidence protocol.
- Prepared task context manifest:
  `6785c3183b4f810a523888e32152edec74db73f40a128cfdcd1a93bba1b84185`.

## Approval

Owner approval is pending. Until explicit approval, this ADR remains Proposed,
`governance/decisions.yaml` keeps ADR-004 `required`,
`ADR-REVISION-IDENTITY-001` remains `ready`, and no successor is activated.
