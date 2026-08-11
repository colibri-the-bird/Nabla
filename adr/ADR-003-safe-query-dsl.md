# ADR-003: Bounded safe Query DSL

- **Status:** Proposed — owner approval required
- **Date:** 2026-08-11
- **Task:** `ADR-QUERY-DSL-001`
- **Decision owner:** Nabla project owner
- **Related decision:** `ADR-007`
- **Supersedes:** None

## Context

Nabla needs dynamic and eventually saved queries for layouts, views, AI context
selection, and other read-only consumers. A query language is nevertheless an
authority and execution boundary: an overly expressive language can expose
restricted records through predicates, ordering, relations, counts, cursors,
errors, or resource behavior even when the returned fields appear harmless.

`CON:I6` forbids arbitrary SQL or executable code received from a user, AI,
document, or data module. `CON:I13` treats AI output and retrieved content as
untrusted data and allows AI reads only through registered queries and the
Context Broker. `CON:I15` requires malformed queries, failed sources, and
derived-index failures to remain explicit failure domains without corrupting
canonical state or disabling independent functionality.

`CON:I4` requires any derived query source, projection, index, or cache to be
rebuildable from exact canonical inputs, a versioned definition, processor or
algorithm version, and explicit parameters; it can never become canonical
truth or the sole export source.

The active draft `CAPABILITY-CONTRACT.md` requires Query to be read-only,
bounded, permission-checked, versioned, and explicit about consistency,
freshness, pagination, ordering, provenance, redaction, audit, and cache
behavior. The active draft `DATA-CLASSIFICATION.md` also makes field,
relation, count, existence, and derived-output sensitivity part of the query
boundary. This pre-baseline task consumes those documents under the explicit
`draft-allowed` gate; it neither approves nor modifies them.

Accepted ADR-007 permits only declarative data to select implementations that
are already registered in the signed Core release. A Query program is such
data. It cannot register an operator, activate a module, load executable code,
or widen a capability's effective authority.

No repository artifact demonstrates a production parser, query planner,
backend lowering, cursor format, cost model, or cross-platform conformance
suite. This ADR therefore fixes the semantic and security boundary that those
artifacts must satisfy without claiming they have been implemented.

## Decision

### 1. Contract boundary and representation

The public Safe Query DSL is a closed, versioned structural abstract syntax
tree, not a SQL-like string and not a host-language expression. Its logical v1
shape is:

```text
QueryProgramV1 {
  dsl_version: "nabla.query/1.0.0"
  required_features: [FeatureRef]
  source: ExactQuerySourceRef
  parameters: [ParameterDecl]
  select: [FieldRef]
  predicate: Predicate | absent
  order_by: [OrderTerm]
}

QueryInvocationV1 {
  bindings: Map<ParameterId, TypedValue>
  page: PageRequest
}
```

`QueryProgramV1` is inert declarative data. An invocation supplies values and
page state separately; neither object contains executable code. The exact wire
encoding and canonical bytes remain an implementation specification, but every
encoding must preserve the closed schema, reject duplicate or unknown fields,
and decode to the same abstract semantics.

A program selects exactly one registered `QuerySource`. Its persistent source
reference pins a stable ID, semantic version, contract hash, and owner module;
the invocation separately resolves and pins one compatible Registry generation.
The registered source contract fixes:

- exact available fields, types, nullability, and sensitivity metadata;
- which fields may be projected, filtered, or ordered;
- the permitted operator/type pairs;
- its consistency, freshness, snapshot, provenance, redaction, audit, and
  cache contract;
- a stable unique pagination key;
- finite cardinality, time-range, work, and output ceilings;
- the capability and DataScope closure through which it is exposed.

The DSL may request only a stricter limit or behavior than the registered Query
Descriptor. It cannot weaken consistency, freshness, redaction, audit,
sensitivity, authority, or cost policy.

The enclosing registered Query capability is identified independently by the
exact `(capability_id, semantic_version, contract_hash)` tuple required by the
Capability Contract. The program cannot select or replace that capability.
Each source contract supplies exact `DataAccessRule` entries for its Catalog
fields, purpose, consistency, sensitivity ceiling, and selector limits. A
derived source/field also supplies the applicable `DataOutputRule`, provenance,
algorithm/service version, sensitivity inheritance, and rebuild/reset behavior.

### 2. Closed v1 grammar

The v1 predicate grammar is:

```text
Predicate :=
    all([Predicate; 2..N])
  | any([Predicate; 2..N])
  | not(Predicate)
  | compare(eq | ne | lt | lte | gt | gte, FieldRef, ParamRef)
  | in(FieldRef, ListParamRef)
  | is_null(FieldRef)
  | is_not_null(FieldRef)
  | is_missing(FieldRef)
  | is_present(FieldRef)
```

The opcode spelling in this grammar is shorthand, not a floating name. For
`nabla.query/1.0.0`, each opcode maps to one exact built-in
`(operator_id, semantic_version, contract_hash)` tuple declared by the DSL
profile. The pinned Registry generation must resolve that same tuple, and the
resolved tuple is included in the normalized and bound identities. A source
declares which exact tuples it permits; it cannot redefine opcode semantics.

Each `FeatureRef` is likewise the exact
`(feature_id, semantic_version, contract_hash)` tuple. Feature refs are sorted,
unique, and cannot use a range, alias, or `latest`.

An absent predicate means `true`. Projection is a non-empty, duplicate-free
list of exact fields; wildcard projection does not exist. Ordering is a finite
ordered list of exact source fields and explicitly fixes direction, one total
value-state bucket order, and comparison profile.

Every source, field, parameter, feature, and operator identifier occupies a
dedicated AST slot. A parameter can never stand for an identifier, operator,
field path, source, direction, query node, or fragment of syntax.

The generic v1 DSL has no:

- raw SQL, table, column, index, storage path, or backend plan reference;
- expression string, template interpolation, script, bytecode, shell, or
  host-language callback;
- arbitrary function, runtime-supplied operator, or executable extension;
- join, subquery, recursion, graph traversal, or unbounded relation expansion;
- aggregation, grouping, window function, implicit total count, or computed
  projection;
- arithmetic, regex, fuzzy matching, full-text/vector/geospatial search, or
  relevance/random ordering;
- mutation, event, workflow, job, network call, or external effect.

A registered source may expose a relation-derived or search-derived value as
an ordinary typed field only when its own contract supplies `DataAccessRule` or
`DataOutputRule` ownership, authorization, sensitivity, freshness, provenance,
rebuild/reset, and finite-cost semantics. The generic v1 registered-join set is
empty; such a field does not turn the DSL into a relation traversal, storage
join, or search language.

### 3. Type and null semantics

The filter/order scalar types admitted by v1 are an exact subset of the
Capability Contract type system:

```text
boolean
int32 | int64
decimal(precision, scale)
string(comparison_profile, normalization_policy)
enum(exact_contract_ref)
date
timestamp(serialization, resolution)
local_datetime(timezone_and_ambiguity_policy)
duration(unit)
entity_id(entity_kind)
revision_id
hash(algorithm)
List<T>  // parameter value for `in` only
```

Bounded composite values and `blob_handle` may be projected only when the
source contract permits them; they are not generic v1 filter or order operands.
`secret_handle` is neither a generic Query operand nor output and remains under
`SecretAccessRule`. `cursor` is control state, not a source-field value.
Floating-point values, `NaN`, infinity, ambient-locale types, and values whose
comparison semantics are not versioned are not admitted.

Types are exact. There is no implicit numeric widening, string-to-ID or
string-to-time conversion, timezone assumption, enum-by-label conversion, or
backend coercion. Decimal scale and precision, timestamp resolution, stable-ID
or revision-ID kind, and enum contract are part of the type identity. Overflow
and loss of precision are binding errors.

The mandatory v1 text comparison profile is versioned binary UTF-8 with the
explicit normalization policy `none`. It performs no ambient locale
comparison, case folding, accent folding, or implicit Unicode normalization.
Additional comparison/normalization profiles require an explicit DSL feature
and source/operator contract before use.

Missing and explicit null remain distinct. A registered `optional with default`
source field applies its declared default before DSL evaluation; other absent
optional fields evaluate as `Missing`. A comparison whose field value is
`Missing` or null evaluates to `Unknown`; `not(Unknown)` remains `Unknown`, and
a row is selected only when the final predicate is `True`.

The strong-Kleene operators are exact: `not(True)=False`, `not(False)=True`,
and `not(Unknown)=Unknown`; `all` is `False` when any child is `False`, `True`
when every child is `True`, and otherwise `Unknown`; `any` is `True` when any
child is `True`, `False` when every child is `False`, and otherwise `Unknown`.

`is_null` is `True` only for explicit null, `False` for present non-null, and
`Unknown` for `Missing`; `is_not_null` is the corresponding `False`, `True`,
and `Unknown`. `is_missing` is `True` only for absence and `False` otherwise;
`is_present` is its exact inverse and is `True` for both null and non-null
presence. An `in` field value of null or `Missing` evaluates to `Unknown`; its
binding is non-empty, homogeneous, finite, and contains neither null nor a
missing sentinel.

### 4. Binding, validation, and canonical identity

Each `ParameterDecl` fixes an ID, exact type, null policy, maximum encoded
bytes, and, for a list, maximum item count. Invocation bindings form a separate
typed map. Missing, duplicate, extra, nullable-policy-violating, oversized, or
wrong-type bindings are rejected before source data is read.

`ParameterId` values are unique. Every `ParamRef` resolves to exactly one
declaration, and every declaration is referenced; duplicate, conflicting, or
unused declarations are invalid. The normalized declaration list and binding
map are sorted by `ParameterId`, while user-significant projection, predicate,
and ordering sequences retain their declared order.

Every v1 parameter used by `compare` or `in` has `null_policy: forbidden`.
Null/missing field states are queried only by the dedicated predicate nodes;
there is no bound null or missing sentinel.

Parameter bytes are parsed exactly once as values. They are never reparsed as
DSL, SQL, a field name, a path, or an operator. Any backend lowering uses fixed
registered mappings and parameter binding; string concatenation into backend
syntax is prohibited. The same rule applies to user, import, document, tool,
and AI-originated programs and values. User confirmation does not convert AI
origin into user authority.

The Core decodes, validates, and normalizes in this order:

1. enforce encoded-byte, nesting, node, arity, string, and collection limits;
2. validate the exact DSL version, closed schema, and required features;
3. authenticate origin and consumer and pin the exact Query capability identity
   and one ADR-007 Registry generation before policy/handler execution;
4. resolve source, field, feature, and operator refs under the caller's
   discovery envelope without exposing detailed type information;
5. expand every registered source/capability default, missing-field default,
   derived input, and opaque stable order tie-breaker to exact refs, resolving
   every introduced ref under the same discovery envelope;
6. compute and enforce the static source/ref/operation/field authority and
   sensitivity closure over the fully expanded program, collapsing hidden or
   denied identities before any detailed type or binding error is public;
7. statically type-check the authorized operators/defaults/order, canonicalize
   the fully expanded program, and compute its
   `normalized_program_hash`;
8. bind, type-check, and canonicalize every exact value;
9. recompute the invocation-specific DataScope selectors, record policies,
   time/cardinality
   bounds, complete authority intersection, and sensitivity closure over the
   expanded program and bindings, including every default, derived input, and
   opaque tie-breaker;
10. compute a sensitivity-safe bound-request identity;
11. validate the closed page request and any cursor against the program/bound
    identities, then perform freshness, audit, and finite cost admission.

Normalization rejects unknown or duplicate fields. It does not apply De
Morgan transformations, constant folding, predicate deduplication, or another
algebraic rewrite whose behavior could vary with null or future semantics.
Normalization is idempotent. Backend plans are derived artifacts and never
part of the public program identity.

The canonical semantic representation includes the DSL schema version,
deterministic field ordering, normalized exact numbers/timestamps, an explicit
absent-versus-null distinction, the selected string normalization profile, and
no duplicate map keys. A wire encoding may differ but cannot change that
fingerprint or reinterpret known fields.

Sensitive binding values are not stored in a public hash, cursor, log, or
diagnostic. Every bound-request, cursor, and reusable cache identity must bind
a sensitivity-safe keyed digest of the exact canonical typed bindings, scoped
to the installation and policy. The exact keyed-digest mechanism must be
specified before implementation.

### 5. Authority, visibility, and classification

Query evaluation applies the effective intersection fixed by the capability
and ADR-007 boundaries:

```text
capability and source maximum
∩ verified actor/consumer grant
∩ module and exact DataScope policy
∩ record/container policy
∩ sensitivity/outbound policy
∩ destination and platform/runtime policy
```

Deny wins. A Query program can narrow this intersection but never widen it.
Registry presence, a source reference, a cursor, a cache entry, an AI tool
schema, or a previously successful page is not an authority grant.

Every field that influences an observable result requires authority: projected
fields, predicates, ordering, source-derived relation values, provenance,
freshness, `has_more`, and any separately registered count. V1 has no general
"use without disclose" privilege. A field unavailable to the current actor and
consumer cannot be used merely because it is later redacted from projection.

This rule covers every caller-selected, registered-default, derived, and opaque
tie-breaker input. Core-injected mandatory policy predicates are evaluated only
under the Policy Service's exact declared access and may only narrow the
visible set; they neither become caller-selectable fields nor grant the caller
"use without disclose" authority.

Record policy is logically applied before the user predicate, ordering,
pagination, relation-derived values, and cardinality metadata. A physical
optimizer may reorder work only when it proves observational equivalence to
that policy-first model. Page size, cursor issuance, `has_more`, and errors are
computed over the authorized visible set and do not count hidden rows.

Unknown, undiscoverable, and policy-hidden sources or fields share the same
public unavailable response. A public error must not become an oracle for a
restricted schema, record, relation, policy, or derived index. Internal audit
may retain a more precise classified reason when policy permits.

Result sensitivity is at least the maximum sensitivity of every projected,
predicate, ordering, relation-derived, provenance, and cardinality input that
affected it. Aggregation and redaction do not automatically declassify data.
Raw `P4` secret values are not representable Query results or predicates;
secret use remains a separate purpose-bound capability operation.

When an actual record is more sensitive than the effective ceiling, the Query
Descriptor's declared output policy performs full deny, explicit field
redaction, or partial-item denial. It never silently returns the field. Typed
responses carry the declared consistency plus applicable freshness, source
generation, provenance, redaction/partial state, and bounded pagination
metadata. Those metadata are themselves classified Query output.

For an AI consumer, the actor origin remains `ai`, Tool Gateway exposure may
only narrow the registered query, and Context Broker outbound policy is
re-evaluated before disclosure. Query text or retrieved content cannot change
the model's exposure level, tools, grants, confirmation, budget, or system
policy.

This ADR does not claim constant-time behavior or complete prevention of every
statistical inference attack. It requires collapsed sensitive error shapes,
policy-first cardinality, bounded work, and measured leakage tests against the
declared threat model before a stronger claim can be made.

Production activation of any relation-derived, backlink, existence, or
cardinality source additionally requires paired absent-versus-denied/hidden
timing and cardinality tests under the declared local-rogue-process threat
model. The source contract records a measured threshold and mitigation. If the
threshold is not met, that source/operation remains unavailable or fails
closed; the implementation cannot replace this gate with a global
constant-time claim.

### 6. Ordering, snapshots, and pagination

Ordering is total and platform-stable. Each term pins field, direction, the
comparison profile, and `state_order`: one exact permutation of
`[Missing, null, value]`. Direction applies only inside the present non-null
`value` bucket, so Missing and null never share an ambiguous placement. The
normalized ordering ends with the source-declared stable unique key. The key
may remain opaque in output but is bound into pagination state and included in
the authority/sensitivity closure; if no policy-safe stable key exists,
paginated activation is rejected.

Ambient database iteration order, wall clock, random order, floating relevance
score, unspecified collation, or a non-unique sort key is invalid. A relative
time such as "now" must be supplied as an explicit typed binding fixed for the
request; it is not an evaluator function.

`PageRequest` is the following closed, mutually exclusive tagged union:

```text
PageRequest :=
    { kind: none }
  | { kind: cursor_first, limit: PositiveInt }
  | { kind: cursor_resume, limit: PositiveInt, cursor: OpaqueCursor }
  | { kind: bounded_offset, limit: PositiveInt, offset: NonNegativeInt }
```

Unknown or mixed variant fields are rejected. `none` is valid only when the
effective maximum cardinality and output bytes fit one bounded result. Cursor
pagination is the default for lists. Bounded offset is allowed only when the
Query Descriptor explicitly declares `bounded_offset`, a finite `max_offset`,
the dataset ceiling, and its concurrent-mutation consistency behavior.
Unbounded offset is prohibited.

An opaque, integrity-protected cursor binds at least:

- exact query capability `(id, semantic_version, contract_hash)`, DSL/features,
  and source/operator contracts;
- normalized program hash and an opaque binding identity;
- exact expanded ordering and the continuation key;
- actor, consumer, destination, grant, and policy generation;
- Registry generation and source snapshot/generation;
- page-size ceiling and finite expiry.

The cursor contains no raw program, parameter, secret, unrestricted record
value, backend plan, or authority token. Every page revalidates actor,
capability, source, grant, policy, sensitivity, and runtime limits. Revocation
or an incompatible Registry/policy change invalidates continuation even when a
snapshot still exists.

`cursor_bound` promises one stable source snapshot. Loss or expiry of that
snapshot returns a typed failure and never silently restarts against current
state. `snapshot: request` fixes consistency only within one invocation/page;
it is released with that page, and any cursor continuation opens a new request
snapshot under the descriptor's declared keyset drift semantics. A descriptor
using `snapshot: none` likewise exposes its exact drift semantics and cannot
claim request- or cursor-wide snapshot stability. No total count is returned
implicitly.

### 7. Finite planning and admission

Every registered source/operator and invoked query has finite ceilings for:

- encoded request and cursor bytes;
- AST nodes, depth, boolean arity, and total predicate count;
- parameters, binding bytes, text bytes, and `in` item count;
- projected fields, order terms, page size, offset, and cursor lifetime;
- candidate cardinality, scanned rows/work units, and time range;
- output rows and bytes;
- deadline, memory class, concurrency, queue depth, and retry;
- snapshot count, retained bytes, and lifetime;
- audit/cache bytes and retention.

The effective ceiling is the minimum of the capability, source/operator,
DataScope/grant, consumer, platform/runtime, and request ceilings. A request
may reduce but never increase it. `unbounded` is not a valid value.

Source contracts provide deterministic static cost rules for every allowed
field/operator/order combination. A plan whose work cannot be bounded, whose
required index/projection is unavailable, or whose maximum exceeds admission
policy is rejected before execution. Runtime saturation returns bounded
backpressure metadata and does not create an unbounded queue or silently fall
back to a broader scan with different cost/freshness semantics.

Exact numeric ceilings and cost coefficients require measured implementation
evidence and belong to the subsequent DSL/source specifications. Their absence
does not permit implementation with implicit or infinite defaults.

### 8. Read-only execution and failure isolation

One accepted invocation executes against the declared canonical/projection
source and returns either one complete bounded page or a typed failure under
the descriptor's declared consistency/snapshot contract. No partial page is
returned. The v1 generic DSL does not define streaming. Compilation and
evaluation cannot write canonical state, create a domain event, start a
workflow/job, invoke a Command, or perform an external effect.

Security audit and bounded derived cache are Kernel Services with their own
classification, owner, purpose, retention, and failure policy. They do not
make the Query a Command. When `security_audit: required`, the minimized audit
admission receipt must be durable before any sensitive result bytes are
released; audit failure is fail-closed.

The receipt has an allowlisted schema: exact capability/source/DSL identity or
a sensitivity-safe keyed program/bound-request digest; verified actor reference
and origin kind; declared purpose; grant/policy generation; allow/deny/outcome;
correlation/time; sensitivity class; and bounded resource-summary fields. It
contains no raw AST, bindings, results or bodies, record IDs, unrestricted
schema/plan detail, or exact sensitive cardinality unless a separate exact,
classified `CA` purpose and policy explicitly requires that field. Raw `P4`
values and credentials are never admitted.

Every reusable cache key binds exact program/source/operator/Registry identity,
the sensitivity-safe keyed digest of exact canonical typed bindings, source
snapshot/freshness generation, the exact page variant/limit/offset or
integrity-verified continuation identity, and actor/consumer/destination plus
grant/policy generation. Cache reuse never skips current authorization or
sensitivity checks, never crosses actor/policy partitions without an explicitly
proven safe shared representation, and is invalidated by incompatible source,
snapshot/freshness, binding, page/continuation, grant, or policy change. A cache
miss or failure may use uncached execution only when the same authority,
freshness, and finite-cost contract still passes.

A reproducible result/projection cache is `DD` (or short-lived `OR` only where
the registered purpose says so), never canonical truth. It binds exact
canonical input cursor, normalized definition/program identity, source and
processor/algorithm version, and explicit parameters; it carries input
provenance, maximum input sensitivity, and a rebuild/reset contract. Deleting
all such cache/index state cannot lose canonical information, and it is never
the sole export/sync source. A historically valuable non-reproducible result
cannot be relabeled as cache; its later canonical representation is outside
this ADR.

Logs and public diagnostics contain a correlation ID and minimized typed
metadata, not raw AST, parameters, results, record IDs, hidden schema names,
backend SQL/plans, secrets, or unrestricted error bodies. Audit/cache data
inherits the maximum applicable sensitivity and outbound policy.

Malformed input, type or policy rejection, deadline, cancellation, source
failure, and derived-index failure affect only that request and its declared
source. No partial page or cursor is returned after failure. An unavailable
projection/index yields its declared freshness/source failure; it does not
silently change consistency or run an unbounded canonical scan.

A derived processor failure marks its dependent projection stale or
unavailable while leaving canonical inputs intact. Rebuild follows the
registered processor's exact input cursor, definition, algorithm/model version,
parameters, seed where applicable, checkpoint, and resource contract. Query
execution never starts that processor as a hidden fallback.

A registered source/operator implementation remains trusted built-in code
under ADR-007. Its ordinary error or audited unwind failure is localized to the
request/module boundary and leaves canonical state unchanged. Abort, memory
corruption, process-wide invariant failure, or out-of-memory termination still
has ADR-007's honest shared-process limit and is not claimed as isolated.

### 9. Versioning and compatibility

The DSL version pins grammar, type, null, comparison, ordering, normalization,
and public error semantics.

- A major version changes incompatible semantics.
- A minor version may add only an explicit feature/node/operator; a program
  declares every required feature and an evaluator must understand all of them.
- A patch version cannot change observable semantics.
- Unknown major, minor feature, node, field, operator, or semantic option fails
  closed; unknown data is never ignored.

Source, field, enum, operator, capability, and Registry references are exact
version/hash identities. Floating `latest`, name-based rebinding, or silent
selection of a compatible-looking field is prohibited.

Unknown input/AST fields always fail closed. A client within a compatible
capability major may ignore an unknown optional typed response field only when
the Query contract explicitly declares that it cannot change interpretation of
known fields.

Any future persisted saved query must retain its DSL version, exact refs,
normalized program hash, parameter declarations, provenance, owner, and
sensitivity. An incompatible query becomes typed unavailable and is never
silently reinterpreted. This ADR does not choose its record class, storage
schema, writer, revision identity, history, or migration representation; those
remain with `ADR-REVISION-IDENTITY-001` and a later saved-query specification.

For the same supported platform contract, Registry/source generation,
authorized snapshot, policy generation, normalized program, bindings, and
limits, evaluation produces the same typed rows, ordering, and semantic error.
Resource pressure may still produce a declared `RESOURCE_EXHAUSTED` or deadline
failure; it cannot change successful result semantics.

### 10. Deterministic rejection and public errors

Validation has this exact primary-error precedence and does not continue into a
later stage merely to expose more information:

1. pre-decode hard limits (`QUERY_STATIC_LIMIT_EXCEEDED`), ordered by stable
   limit ID and then earliest byte offset;
2. decode/closed-schema defects (`QUERY_ENVELOPE_INVALID`), ordered by earliest
   byte offset and then canonical AST path;
3. DSL/feature version (`UNSUPPORTED_VERSION`), ordered by exact feature tuple;
4. authentication, discoverable exact-reference resolution, default expansion,
   and static ref/operation/field authority (`PERMISSION_DENIED` or
   `QUERY_UNAVAILABLE`), ordered by canonical ref;
5. authorized operator/type/order validation (`QUERY_TYPE_INVALID` or
   `QUERY_ORDER_INVALID`), ordered by canonical AST path;
6. binding validation (`QUERY_BINDING_INVALID`), ordered by `ParameterId`;
7. invocation-specific authority and sensitivity (`QUERY_UNAVAILABLE`,
   `PERMISSION_DENIED`, or `POLICY_DENIED`), ordered by canonical ref;
8. closed page variant and cursor (`QUERY_PAGE_INVALID`, then cursor integrity,
   expiry, compatibility/snapshot state), ordered by variant field/path;
9. freshness, required audit, and static cost admission, in that order;
10. runtime resource, deadline, cancellation, source, and internal failures.

Within runtime execution the first terminal event wins and the page is
discarded. Resource availability may vary, but the semantic validation outcome
and safe public mapping do not vary for the same declared inputs/context.

The public taxonomy is:

| Code | Meaning |
|---|---|
| `QUERY_STATIC_LIMIT_EXCEEDED` | Structural/input finite ceiling is exceeded. |
| `QUERY_ENVELOPE_INVALID` | Malformed encoding, duplicate/unknown field, or invalid AST shape. |
| `UNSUPPORTED_VERSION` | DSL version/feature is unsupported; this is the Capability Contract version error. |
| `QUERY_UNAVAILABLE` | Source/field/operator is missing, undiscoverable, disabled, or policy-hidden. |
| `QUERY_TYPE_INVALID` | Authorized field/operator/type combination is invalid. |
| `QUERY_BINDING_INVALID` | Binding is missing, extra, duplicate, oversized, null-invalid, or wrong-type. |
| `QUERY_ORDER_INVALID` | Ordering is unsupported, non-total, or lacks a stable key. |
| `QUERY_PAGE_INVALID` | Page size/offset/mode violates the descriptor. |
| `CURSOR_INVALID` | Cursor is malformed, forged, or bound to a different request/context. |
| `CURSOR_EXPIRED` | Cursor or required snapshot exceeded finite lifetime. |
| `CURSOR_STALE` | Registry, source, grant, policy, or compatibility generation changed. |
| `SNAPSHOT_UNAVAILABLE` | A required request/cursor snapshot was lost without an allowed fallback. |
| `PERMISSION_DENIED` | A visible operation is outside effective authority; no hidden existence detail. |
| `POLICY_DENIED` | Sensitivity/consumer/destination policy denies disclosure where that code is safe. |
| `FRESHNESS_UNAVAILABLE` | Required projection freshness cannot be met. |
| `AUDIT_UNAVAILABLE` | Required security audit cannot be recorded; no result is released. |
| `QUERY_COST_REJECTED` | Static finite work/cost cannot be proved or admitted. |
| `RESOURCE_EXHAUSTED` | Runtime admission/backpressure limit is saturated. |
| `DEADLINE_EXCEEDED` | Declared deadline expired. |
| `CANCELLED` | Caller/runtime cancellation completed at the read boundary. |
| `SOURCE_UNAVAILABLE` | Authorized source/index/module failed without an allowed fallback. |
| `INTERNAL` | Minimized unexpected failure with correlation ID only. |

Retryability and bounded retry metadata belong to the code, never to a backend
message. Public errors do not include raw values, backend SQL, table/field
existence, restricted counts, plans, stack traces, or policy internals. Missing
and forbidden references are deliberately collapsed whenever distinguishing
them would reveal sensitive existence.

## Compatibility constraints

1. A DSL program is data and cannot activate code or bypass ADR-007.
2. The same DSL/source/operator versions preserve domain meaning and comparison
   semantics on Desktop, Mobile, CLI, and every backend.
3. Every value is separately typed and bound; parameter bytes never become
   syntax or an identifier.
4. Policy-filtered records and fields form the only observable query universe.
5. Projection, predicate, ordering, cursor, freshness, relation-derived values,
   and cardinality metadata all participate in authority and sensitivity.
6. Query never mutates canonical state or performs an external effect.
7. Unknown versions/features/fields/operators and unbounded work fail closed.
8. Pagination is total-order based, policy-bound, finite, and never an
   authority grant.
9. A backend optimization or fallback cannot change consistency, visibility,
   ordering, null, error, or cost semantics.
10. A support or privacy claim requires evidence on the exact platform,
    Registry/source generation, backend, policy, and failure mode claimed.

## Consequences

### Positive

- A small closed AST is easier to validate, fuzz, authorize, cost, and lower
  safely than a general query language.
- Separate typed bindings remove identifier and syntax interpolation paths.
- Exact source/operator identities and deterministic normalization make saved
  query compatibility and evidence auditable.
- Policy-first evaluation covers hidden fields, rows, relations, order, counts,
  and cursors instead of treating projection redaction as sufficient.
- Finite admission and explicit source degradation localize expensive or broken
  queries without changing canonical state.
- AI and user-authored programs share one untrusted-data boundary.

### Costs and risks

- V1 cannot express joins, arbitrary relation traversal, aggregation, regex,
  full-text/vector search, computed fields, or custom functions.
- Every source must publish a detailed field/operator/cost/security contract
  and a platform-stable unique ordering key.
- Exact hashes and fail-closed compatibility make source upgrades visible and
  require explicit compatibility handling under later persistence decisions.
- Cursor-bound snapshots and policy rebinding consume finite resources and may
  expire during long navigation.
- Binary text comparison is deterministic but does not provide user-locale
  search semantics.
- Error collapse and policy-first evaluation reduce existence leakage but do
  not establish constant-time execution or eliminate statistical inference.
- Concrete cost coefficients, cursor protection, backend lowering, and
  cross-platform conformance still require implementation evidence.

## Alternatives considered

| Alternative | Disposition | Reason |
|---|---|---|
| Closed typed structural AST with separate bindings | Selected | It gives finite grammar, exact type/ref validation, deterministic identity, and no string interpolation path. |
| Raw SQL or a sanitized SQL allowlist | Rejected | It exposes storage identity and backend semantics and leaves composition, functions, cost, and inference too broad. |
| SQL-like textual DSL with escaping | Rejected for v1 | Escaping does not solve authority, type, feature, cost, version, or hidden-existence semantics; authoring syntax may later compile into the structural AST. |
| GraphQL/OData or another general public query language | Rejected as the Core contract | Their generic traversal/selection surface is broader than the selected source and cost boundary; an adapter may only translate a strict subset into the same AST. |
| Host-language lambdas, scripts, or module callbacks | Rejected | They are executable authority and violate `CON:I6` and ADR-007. |
| Post-query row/field redaction | Rejected | Filtering, ordering, count, cursor, and timing can already disclose unauthorized data before redaction. |
| General joins, traversal, aggregation, regex, and ranking in v1 | Deferred | Each needs separately registered type, authority, sensitivity, determinism, and finite-cost semantics. |
| Offset as the universal pagination model | Rejected | Large offsets are expensive and mutation-sensitive; only explicitly bounded local use remains available. |
| Silent saved-query rebinding after schema change | Rejected | It changes historical meaning without a new version, review, or evidence. |

## Validation obligations

Before production Safe Query support is accepted, tests and evidence must cover:

1. golden AST accept/reject fixtures, duplicate/unknown fields/features, and
   exact version negotiation;
2. byte/nesting/node/arity/parameter/`in`/projection/order boundary and fuzz
   tests, including malformed Unicode and duplicate object keys;
3. the complete type/operator matrix, overflow, timestamp resolution, binary
   text comparison, missing/null predicate truth tables, and
   `[Missing, null, value]` state-order permutations on every backend;
4. an injection corpus containing quotes, SQL comments, separators, NUL,
   Unicode confusables, paths, code/tool instructions, and oversized values,
   proving each value remains data or is rejected before source access;
5. missing/extra/duplicate/wrong-type binding, duplicate/conflicting/unused
   parameter declarations, exact `ParamRef` resolution, and every attempt to
   bind an identifier, source, field, operator, direction, or AST node;
6. projection/predicate/order authority matrices, row-policy-before-filter,
   hidden field/relation/count/error collapse, record-level policy, P2/P3/P4
   plus AI-consumer cases, and paired absent-versus-denied timing/cardinality
   measurements against each declared threshold and mitigation;
7. output sensitivity inheritance from non-projected predicate/order inputs,
   Context Broker enforcement, audit receipt allowlist/minimization for P2/P3
   bindings and results, and proof that P4/raw secrets never enter result,
   cursor, cache, audit, log, or diagnostics;
8. normalization idempotence, golden hashes, preservation of meaningful list
   order, exact feature/operator tuple resolution, and identity changes for
   every semantic version/ref change;
9. total ordering with ties/missing/null, closed page variants, bounded offset,
   cursor tamper/expiry, cross-actor reuse, changed bindings, revoked grants,
   incompatible Registry, and policy generation changes;
10. request, cursor-bound, and declared non-snapshot concurrent-mutation tests,
    including exact drift behavior and explicit snapshot loss without silent
    restart;
11. `N-1/N/N+1` tests for every finite limit, static cost rejection, index loss,
    queue saturation, cancellation, deadline, memory pressure, and bounded
    backpressure without starving integrity/backup work;
12. deterministic error-stage precedence and public-detail tests proving no
    backend, schema, restricted existence, value, plan, or policy leakage;
13. read-only conformance proving canonical state, events, jobs, workflows, and
    external effects remain unchanged, including audit-required failure before
    result release and prohibition of raw AST/bindings/results/record IDs or
    exact sensitive cardinalities in the ordinary receipt;
14. same-program/different-binding/page/continuation cache isolation,
    actor/consumer/destination partitioning, snapshot/freshness and grant/policy
    invalidation, DD/OR rebuild/reset, source disable/upgrade/unavailability,
    and no unsafe fallback;
15. fault injection for parser, source, index, handler, and module failures,
    proving canonical integrity and availability of independent queries while
    recording ADR-007's shared-process fatal-fault limit;
16. a reference evaluator versus every backend lowering, with Desktop/Mobile
    golden result, ordering, null, and error compatibility fixtures.

## Deferred decisions

This ADR does not choose or implement:

- the public byte/wire encoding, authoring syntax, parser library, backend SQL,
  query planner, optimizer, indexes, or physical source schema;
- numeric limit defaults, cost coefficients, benchmark thresholds, or the
  concrete admission scheduler;
- cursor cryptography, key rotation, server-state representation, snapshot
  mechanism, or exact expiry values;
- saved-query/layout persistence, record class, revision identity/history,
  ownership/writer schema, UI/query builder, collaboration, or migration
  representation/tooling; these remain with `ADR-REVISION-IDENTITY-001` and a
  later saved-query specification;
- joins, generic relation traversal, aggregation/count/group/window,
  differential privacy, anonymization, or declassification;
- regex, locale/case-insensitive text, full-text, fuzzy, vector, geospatial,
  graph, recursive, or relevance-ranked search;
- cross-device/federated queries, portable cursors, or sync execution;
- persistent cache encryption and exact audit/cache retention, which remain
  constrained by ADR-005 and ADR-008;
- production runtime code, dependencies, or amendments to active draft
  normative specifications.

These open parameters do not permit raw SQL/code, implicit coercion, floating
refs, unbounded execution, authority widening, hidden mutation/effects, secret
disclosure, post-hoc security filtering, or silent semantic fallback.

## Supersession rules

A future accepted ADR must explicitly supersede every affected accepted
decision and remain consistent with the Constitution and applicable normative
specifications. Expanding the DSL cannot by itself supersede ADR-007 or create
runtime operator/module loading. Any executable extension must separately
satisfy the ADR-007/ADR-001 supersession and evidence requirements.

An additive DSL specification may register a new type, operator, source
feature, comparison profile, traversal, aggregate, or search mode without
superseding ADR-003 only if it preserves the closed structural representation,
separate typed binding, exact versioning, effective-authority intersection,
policy-first observability, finite cost, deterministic errors, read-only
boundary, and explicit compatibility behavior fixed here. Otherwise it
requires a superseding ADR.

## Sources and evidence

- `CONSTITUTION.md` v0.1: `CON:I4`, `CON:I6`, `CON:I13`, `CON:I15`, and
  `CON:4.2`.
- Active draft `ARCHITECTURE.md` v0.1: `ARCH:8`, `ARCH:9`, `ARCH:17`,
  `ARCH:18`, `ARCH:20`, `ARCH:24`, and `ARCH:24.1`, consumed under the
  pre-baseline `draft-allowed` gate.
- Active draft `DATA-CLASSIFICATION.md` v0.1: `DATA:4.6`, `DATA:6`, and
  `DATA:12`, consumed under that gate.
- Active draft `CAPABILITY-CONTRACT.md` v0.1: `CAP:3.4`, `CAP:6`, `CAP:7.4`,
  `CAP:8.4`, `CAP:9`, `CAP:10`, `CAP:12`, `CAP:12.8`, `CAP:14`, `CAP:24`,
  `CAP:25`, and `CAP:31`, consumed under that gate.
- Accepted `ADR-007`: registered declarative inputs, exact Registry generation,
  effective-authority intersection, finite limits, and no runtime executable
  extension through query data.
- Approved `SPEC-NAVIGATION.md` v0.4: `NAV:6` execution and evidence protocol.
- Prepared task context manifest:
  `f1d4cdc84c4772fb51009792d7aa43d6d9a9a0c79dde7bdc7432fbdd2488fe89`.

## Approval

Pending explicit owner approval. Until approval is recorded, this ADR remains
proposed, `governance/decisions.yaml` remains `required` for `ADR-003`, and
`ADR-REVISION-IDENTITY-001` remains blocked.
