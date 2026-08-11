# ADR-007: Module packaging, trust, activation, and failure isolation

- **Status:** Proposed — owner approval required
- **Date:** 2026-08-11
- **Task:** `ADR-MODULE-TRUST-001`
- **Decision owner:** Nabla project owner
- **Related decisions:** `ADR-001`, `ADR-010`
- **Supersedes:** None

## Context

Nabla needs versioned modules without turning documents, manifests, AI output,
or downloaded data into executable authority. `CON:I6` permits executable v1
modules only as trusted compile-time packages with runtime activation. It also
requires a separately accepted and implemented installation boundary before
future executable loading can be considered. `CON:I15` requires module and
processor failures to remain explicit failure domains without corrupting
canonical state or disabling unrelated functionality.

Accepted ADR-001 chooses Rust compile-time domain packages inside the signed
Core release. Its embedded C ABI is a platform-host interface, not a module or
plugin ABI. Accepted ADR-010 authenticates Desktop UI and CLI clients to the
Core; that local IPC identity is neither package provenance nor module trust,
and modules do not own IPC endpoints.

The active draft `MODULE-MANIFEST.md` and `CAPABILITY-CONTRACT.md` describe
module identity, exact contract bundles, dependency resolution, authority
envelopes, lifecycle states, immutable Registry generations, and finite
capability limits. This pre-baseline task consumes those documents under the
explicit `draft-allowed` gate. This ADR records an outcome for later baseline
incorporation; it neither approves nor modifies the draft specifications.

No repository artifact demonstrates a production external package format,
publisher PKI, revocation service, installer, executable loader, sandbox, or
native-fault containment boundary. ADR-007 therefore fixes the v1 boundary and
the fail-closed prerequisites for any future widening; it does not claim that
external executable modules are supported.

## Decision

### 1. Executable distribution boundary for v1

Every executable v1 module is:

```text
distribution.kind = built_in
distribution.trust_tier = core_release
distribution.install_source_policy = core_release_manifest_only
```

Its Rust implementation is compiled into the same pinned Core product set
selected by ADR-001. A build-time generated or statically compiled inventory
binds each module to its exact manifest and artifact identities. Runtime may
activate or disable an inventory member, but it does not discover executable
code in mutable directories and does not load code supplied after the product
was built.

The compiled inventory, installed product manifest, release lock, and signed
product artifact must agree. A mismatch in one module binding blocks that
candidate; failure of the enclosing product signature or release lock blocks
ordinary Core startup rather than treating an unverified release as a degraded
module set.

The following remain prohibited in v1:

- downloaded or side-loaded native libraries;
- executable `external_package` or `first_party_package` bundles installed
  independently of the Core release;
- WASM, scripts, bytecode, generated Rust, shell, SQL, or another general code
  payload treated as a module;
- executable code obtained from a document, AI response, import, sync peer, or
  manifest field;
- reusing the Desktop IPC protocol or the Mobile host C ABI as a plugin ABI;
- resolving an executable through `PATH`, a working directory, environment
  variable, user-writable search path, or floating package reference.

Declarative manifests and contract artifacts are data. They can select only
implementations already present in the trusted release inventory and cannot
create a new handler, Kernel port, capability kind, or executable entrypoint.

### 2. Canonical identity and immutable bundle

The runtime candidate identity is:

```text
ModuleCandidateId = (module_id, module_version, bundle_hash)
```

The candidate also carries exact:

```text
manifest_schema_version
package_format_version
manifest_hash
artifact_set_hash
publisher_id
distribution.kind
distribution.trust_tier
kernel compatibility range
platform support declaration
```

`manifest_hash` commits to the canonical manifest representation.
`artifact_set_hash` commits to every exact contract and implementation artifact
declared for that module and platform. `bundle_hash` commits to both identities
and their binding. For a built-in module, the implementation artifact may be a
compile-time registration identity within the signed Core binary rather than a
separately loadable file; the release lock still binds it to the exact product
artifact hash.

Before production implementation, the canonical serialization and hash-input
specification must be versioned and covered by cross-implementation fixtures.
Until that exists, no independent package-verification compatibility claim is
made.

The release lock resolves exact `(module_id, module_version, bundle_hash)`
tuples. Duplicate identities, conflicting bundles for one exact version,
unknown manifest versions, unresolved hashes, self-dependencies, dependency
cycles, and floating `latest` references fail closed. Resolution is
deterministic and cannot use activation order as an override mechanism.

`owner_id` is project responsibility metadata, not a signer, credential, or
runtime actor. `publisher_id` is a provenance identity and must agree with the
verified release/signing identity; it is likewise never an authority grant.

### 3. Trust tiers and provenance

Trust is evidence about origin and admitted execution mode. It is not a data or
capability permission.

`first_party_package` and `external_package` are schema-reserved distribution
kinds but are not executable activation candidates in v1.

#### `core_release`

This is the only activatable v1 tier. The module is built, reviewed, locked,
and distributed as part of the signed Core product generation. Its individual
manifest signature may be absent or may refer to release-signing metadata;
the signed product set and release lock are the authority for provenance.

`core_release` does not imply correctness, fault containment, access to all
records, secret access, network access, administrative authority, or immunity
from quarantine. The module must still satisfy every contract, authority,
policy, limit, and conformance check.

The revocation and replacement unit for v1 executable code is the signed
product release. An affected built-in module may be disabled or quarantined at
runtime, but replacing its code requires a new signed product generation.
ADR-007 makes no online or real-time revocation claim.

#### `signed_trusted`

This token is reserved for a future installation boundary and is not
activatable by this ADR. A signature can authenticate bytes and publisher
identity, but cannot prove safety, compatibility, minimal authority, or
correct behavior.

#### `restricted_external`

This token is reserved for a future explicitly isolated execution model and is
not activatable by this ADR. It cannot mean “signed native code in the Core
process”. Its future use requires an accepted boundary with independently
tested isolation, a narrow versioned protocol, bounded resources, and denial
of raw Core authority.

Unknown tiers are rejected. Relabeling a bundle or changing publisher,
distribution kind, trust tier, artifact membership, or authority requires a
new committed identity and cannot preserve the old `bundle_hash`.

Any future executable external activation requires a new owner-approved ADR
that explicitly supersedes the v1 subdecision in ADR-001 and this section. It
must be accompanied by implemented evidence for:

- canonical package format and signature verification;
- publisher identity, trust-root distribution, key rotation, revocation, and
  compromised-publisher response;
- explicit installation and authority preview;
- source policy, update, rollback, uninstall, and offline behavior;
- an isolation model and its failure/resource tests;
- compatibility, migration, data-survival, and recovery behavior.

Signing private keys and other release credentials are `P4/SE` and never enter
module bundles, manifests, canonical data, logs, audit bodies, exports, or AI
context. The runtime may receive versioned public trust metadata in a future
design, but this ADR does not choose its algorithm, storage, transport, or
revocation service.

### 4. Authority is computed and intersected

The manifest `authority_envelope` is an upper bound, not a grant. Registry
construction computes the exact required authority as the normalized union of
the module's capabilities, workflows, processors, exporters, adapters,
migrations, renderer actions, and other declared artifacts:

```text
computed_required_authority ⊆ manifest_authority_envelope
```

A missing declaration or required authority outside the envelope blocks the
module. Unused broad authority is a conformance defect and must not be silently
retained for convenience. Wildcard or unjustified broad authority blocks a
production activation claim.

Authority contributed by an optional integration remains separately
attributable to that declared integration and disappears when the integration
is absent or disabled.

At invocation time, effective authority is the intersection of:

```text
manifest envelope
∩ artifact descriptor maximum
∩ verified actor/consumer grant
∩ record/container policy
∩ sensitivity/outbound policy
∩ platform/runtime policy
```

Denial wins. Trust tier, package signature, installation approval, dependency,
or presence in the Registry never widens this intersection.

Modules receive only versioned Kernel ports. Ordinary modules do not receive a
raw database connection, unrestricted filesystem handle, shell, environment
credentials, arbitrary network client, global service reflection, or IPC
listener. External effects use declared Workflow adapter rules; local files use
staged user-selected grants; secrets use purpose-bound handles and never return
raw values to an ordinary query. Installation, trust configuration, and module
security controls are administrative capabilities unavailable to generic
discovery and AI.

Discovery is filtered by active state, platform, consumer type, potential actor
scope, and administrative policy. Presence in the complete Registry is never a
permission or a promise that a particular caller can invoke the module.

### 5. Declarative registration and activation

Registration input is inert metadata until the Core completes validation.
Module-owned constructors, background jobs, network calls, migrations, and
other effects do not run merely because a candidate was discovered or parsed.

Parsing and activation use finite limits for manifest/package bytes, nesting,
strings and lists, artifact/reference counts, dependency nodes/edges/depth,
authority entries, hash/signature work, activation time, memory, concurrency,
generation retention, and diagnostics buffers. Exceeding a limit returns a
typed failure before publication.

For one proposed Registry generation the Core performs, in order:

1. select candidates only from the exact installed release set and lock;
2. enforce bounded input and source/distribution/trust policy;
3. verify product, manifest, artifact-set, and bundle integrity;
4. strictly parse the supported manifest schema and reject unknown fields
   outside a versioned extension point;
5. validate module, owner, publisher, namespace, version, and platform identity;
6. verify Kernel and manifest-schema compatibility;
7. resolve exact dependencies and optional integrations and reject cycles;
8. verify contract-bundle closure, ownership, hashes, and binding uniqueness;
9. validate schemas, Catalog references, data scopes, capabilities, workflows,
   loops, renderers, adapters, migrations, and finite limits;
10. compute required authority and compare it with the manifest envelope;
11. validate platform degradation, data-survival, maintenance, and conformance
    declarations;
12. perform the separately governed migration/backup/recovery preflight when
    applicable;
13. execute only the versioned, separately authorized migration plan when the
    ADR-012 framework permits it;
14. run post-migration integrity and compatibility checks;
15. construct a complete immutable Registry generation off to the side;
16. atomically publish that generation;
17. only then admit invocations and start declared processors or jobs.

ADR-012 owns migration execution and recovery details. A module cannot supply
arbitrary migration code through its manifest, and a candidate requiring an
unsupported migration remains blocked before storage mutation. Until ADR-012
is accepted and its applicable framework is implemented, any candidate that
requires a migration cannot pass step 12.

Failure before storage mutation leaves the prior generation active. Once a
migration begins, ADR-012 determines recovery and whether the old generation is
still schema-compatible; it may remain active only with explicit compatibility
evidence. Otherwise ordinary dispatch stays blocked behind the Core-owned
maintenance/recovery surface. No failure exposes a partial new Registry. A
failed module and its required dependants are typed `blocked`, `incompatible`,
`migration_failed`, or `quarantined`; unrelated modules remain available only
when their storage and contracts are proven unaffected. Activation order is
topological by required dependency, then stable by `module_id` and exact
version/hash.

An invocation or durable workflow pins the Registry generation and exact
contracts with which it began. It either completes under that generation or
enters a declared cancellation/recovery state; a new generation does not
silently change its semantics.

Retained generation count, bytes, and pin duration are finite policy values.
A live invocation is not evicted from beneath execution, but durable workflows
persist exact contract references and use declared migration, recovery, or
maintenance behavior instead of retaining executable memory indefinitely.
Security deny or revocation policy applies to new calls and external effects;
an old generation pin cannot create new authority.

### 6. Failure-isolation contract

The v1 built-in model is a trust boundary, not a memory sandbox. Rust modules
share the Core process and failure consequences must be stated honestly.

| Failure | Required behavior |
|---|---|
| Manifest, identity, hash, dependency, authority, or contract validation failure | Do not publish the candidate; block it and required dependants; retain the previous generation and unrelated modules. |
| Declared handler/domain error | Return a typed error and roll back only the current canonical transaction. |
| Processor/job failure | Stop or back off only the declared processor/job chain, preserve durable state, and expose bounded diagnostics. |
| Panic at an explicitly audited unwind boundary | Roll back current work, invalidate affected handles, mark failed health, and quarantine or disable new calls until required invariant checks pass. |
| Abort, memory corruption, unsafe/native fault, process-wide invariant failure, or out-of-memory termination | The shared Core or embedded host may terminate; restart recovery and integrity checks apply. This is a release conformance defect, not evidence of module isolation. |
| Corrupt or provenance-invalid installed artifact | Quarantine the candidate without executing it; keep data and maintenance/export paths available where the healthy Core can do so. |

Catch-unwind is not a general recovery promise. A module cannot claim `I15`
conformance merely because ordinary Rust errors or one panic are caught.
Hazardous native libraries, untrusted parsing, and other work that needs
stronger isolation must use an already authorized isolated processor/adapter
boundary with its own evidence, or the module is not eligible for the claimed
production use.

Every module and processor declares finite payload, output, memory class,
deadline, concurrency, queue, retry, and cost limits. Resource exhaustion
applies backpressure and typed failure; it does not create an unbounded queue
or a second execution path.

Desktop and Mobile preserve the same module contracts, authority, results, and
typed failures. The Mobile Embedded Core may terminate with its application on
a fatal shared-process fault. Platform packaging or renderer degradation must
be explicit and cannot silently weaken permissions or change domain meaning.

### 7. Disable, quarantine, upgrade, and removal

Planned disable creates a new immutable Registry generation that admits no new
ordinary invocations for the affected module. Required dependants are blocked
unless a compatible declared degraded path exists. In-flight work is drained,
cancelled, or recovered according to its pinned lifecycle contract.

Quarantine is stricter. The Core immediately denies new calls, scheduling, and
external effects for the suspect module, cancels or terminates affected work at
the nearest Core-controlled safe boundary, and exposes only Core-owned
maintenance/recovery paths. A generation pin does not authorize suspect code
to finish normally after an integrity, provenance, binding, or invariant
violation. If work cannot be stopped safely, the Core follows ADR-010 shutdown
or unclean-restart recovery; possible fatal shared-process corruption is never
reported as localized quarantine.

The Core performs quarantine from verified release metadata and its own
maintenance surface; suspect module code is not invoked to quarantine itself,
and quarantine never starts an automatic retry loop.

Runtime reason states are distinct: `blocked` means a dependency, closure, or
policy prerequisite is missing; `incompatible` means the version, Kernel, or
platform contract cannot be satisfied; `migration_failed` records the
separately governed migration failure; `disabled` is an intentional lifecycle
decision; and `quarantined` records integrity, provenance, binding, invariant,
or policy-defined unsafe-failure evidence. None of these states rewrites the
manifest release status.

Disable, quarantine, upgrade, rollback, archive, or executable removal never
performs purge and never deletes canonical facts, revisions, relations, blobs,
audit evidence, or historical contract metadata. The release must preserve an
independent maintenance surface sufficient to inspect health, export data, and
execute separately authorized recovery/migration paths. If accumulated data
cannot remain interpretable and exportable, executable removal is blocked.

Reactivation repeats the complete validation pipeline; old trust, bindings,
dependencies, policies, or health are not assumed valid. Rollback cannot start
an older module or Core against an unsupported future schema. Exact migration
and rollback mechanics remain owned by ADR-012 and applicable backup decisions.

Registry rollback may consider only an exact previously verified generation,
but previous verification is insufficient. Before republication it must pass
the complete current activation pipeline against the installed release lock,
current trust/revocation state, policies, authority calculation, dependencies,
artifacts, and current schema/data compatibility. Alternatively, the trusted
updater may perform an atomic signed-product rollback whose exact generation
passes the same current compatibility and ADR-012 recovery gates. Registry
rollback never rolls back canonical data or a completed migration and never
silently selects an older installed candidate.

V1 installation and update occur only as an atomic compatible signed product
generation through the trusted product updater. Users cannot install or update
one executable module independently. Runtime enable/disable remains an
administrative policy action over implementations already present in that
generation.

### 8. Activation evidence and diagnostics

Each attempted generation records content-minimized evidence containing:

- release and Registry generation identities;
- exact module/version/bundle tuples and dependency resolution;
- validator and supported manifest-schema versions;
- trust tier, publisher identity, and integrity result without private key or
  secret material;
- computed authority comparison and policy result;
- migration/preflight references when applicable;
- activation, block, incompatibility, quarantine, or disable reason;
- conformance and health references.

Diagnostics do not include record bodies, document text, raw secrets, signing
credentials, or unrestricted manifest payloads. Security evidence inherits the
applicable sensitivity and outbound policy.

## Compatibility constraints

1. The same module and capability version has the same domain meaning across
   Desktop, Mobile, CLI, and every host adapter.
2. An exact module version cannot resolve to two different bundle hashes within
   one release set.
3. Unknown manifest, contract, Kernel, package, trust-tier, or protocol majors
   fail closed.
4. Package provenance never grants data, network, secret, filesystem, or
   administrative authority.
5. A dependency grants neither direct data access nor an activation-order
   override.
6. No Registry generation becomes visible until its complete closure validates
   and publishes atomically.
7. Disable and executable removal preserve canonical data, historical meaning,
   maintenance, and export; physical deletion requires a separate purge.
8. Desktop IPC authentication and the Mobile host ABI cannot be reused as
   module trust, installation, or executable loading boundaries.
9. A support or isolation claim requires evidence on the exact platform,
   packaging, runtime, and failure mode being claimed.

## Consequences

### Positive

- V1 keeps one small executable trust boundary aligned with ADR-001.
- Exact immutable identities make release composition, dependency resolution,
  activation evidence, and rollback analysis deterministic.
- Trust, authority, compatibility, and runtime health remain separate gates.
- A broken candidate cannot publish a partial Registry or silently acquire
  broad authority.
- Data survival and maintenance are independent of executable availability.
- Future external packaging has explicit prerequisites rather than an implied
  signature-only path.

### Costs and risks

- Every executable module is part of the Core release cadence and requires a
  full product build, review, signing, and update.
- Built-in Rust modules share a process; fatal native faults, aborts, and memory
  corruption are not isolated from the Core.
- Strict bundle hashing, deterministic resolution, conformance matrices, and
  atomic Registry generations add release and tooling work.
- Disabling a module with required dependants may remove a larger feature set
  until a compatible generation is available.
- External ecosystem, marketplace, independent module updates, and sandboxed
  third-party execution remain unavailable.
- Canonical serialization, package signing, publisher PKI, revocation, and
  sandbox choices still require later measured design and implementation.

## Alternatives considered

| Alternative | Disposition | Reason |
|---|---|---|
| Compile-time Rust modules in the signed Core release | Selected for v1 | It matches ADR-001 and is the only executable boundary already admitted by the Constitution and repository evidence. |
| Separately shipped signed first-party package | Deferred | It still needs independent install, revocation, rollback, compatibility, and isolation evidence; first-party identity alone is insufficient. |
| Signed native dynamic libraries loaded in the Core process | Rejected | A signature proves origin, not safety or authority, and the shared process provides no fault or security isolation. |
| Reuse the Mobile C ABI or Desktop IPC as a plugin API | Rejected | Those are host/client boundaries with different identity and authority semantics; reuse would silently widen ADR-001/010. |
| WASM component sandbox | Deferred | It may offer a bounded future model, but no runtime, interface, resource, platform, or fault evidence exists in this task. |
| One OS process per external module | Deferred | It may improve isolation, but protocol, supervision, packaging, authority, persistence, upgrade, and recovery contracts are unresolved. |
| Script or AI-generated module code | Rejected | It violates `CON:I6` and creates an arbitrary execution path. |
| Signature-only trust with manifest permissions | Rejected | Publisher authentication does not validate contract closure, effective authority, behavior, compatibility, or containment. |
| Module-owned DB, filesystem, network, or IPC access | Rejected | It bypasses Kernel ports, capability policy, transaction ownership, and auditable external-effect boundaries. |
| Publish every valid module independently into a mutable Registry | Rejected | It can expose incompatible partial generations and order-dependent semantics. |

## Validation obligations

Before production module activation is accepted, tests and evidence must cover:

- reproducible release inventory and exact module/version/bundle lock;
- canonical manifest/hash fixtures and tamper detection;
- duplicate IDs, conflicting hashes, unknown fields/versions, unresolved refs,
  dependency cycles, optional-integration degradation, and deterministic order;
- contract-bundle closure and rejection of undeclared or foreign ownership;
- computed-authority under-declaration, broad unused envelopes, denied effective
  grants, secret-handle non-disclosure, and absence of raw Kernel authority;
- external package, side-load, dynamic-library, script, arbitrary-code, host
  ABI, and module-owned IPC denial;
- activation failure at every stage with no partial generation and preservation
  of the previous healthy generation;
- concurrent invocation across generation publication and pinned-contract
  completion/cancellation behavior;
- disable, quarantine, dependency impact, reactivation, update, rollback block,
  data readability, maintenance, and export survival;
- ordinary error, panic, processor failure, native/fatal process failure,
  restart recovery, and honest conformance reporting for `CON:I15`;
- finite resource limits, backpressure, diagnostics minimization, and
  Desktop/Mobile semantic parity.

No external executable-module support claim may be made until its separately
accepted boundary has equivalent tests for package provenance, PKI/revocation,
installation consent, sandbox escape, resource denial, update/rollback,
platform behavior, and compromised publisher response.

## Deferred decisions

This ADR does not choose or implement:

- an external loader, runtime ABI, sandbox technology, broker, or worker
  protocol;
- an installer, marketplace, repository, network download, or consent UI;
- a signing algorithm, package format, publisher PKI, trust-root transport,
  key-rotation mechanism, revocation service, or private-key storage system;
- production module schemas, DDL, migration engine, backup format, purge,
  recovery implementation, or sync behavior;
- changes to Rust, Core process ownership, SQLite ownership, Desktop IPC, or the
  Mobile host ABI chosen by ADR-001/010;
- production runtime code or dependencies;
- approval or amendment of the active draft capability/module specifications.

These open parameters do not permit external activation, floating identities,
raw authority, partial Registry publication, unsupported isolation claims, or
data deletion during disable/removal.

## Supersession rules

A future accepted ADR must explicitly supersede every affected accepted
decision and remain consistent with the Constitution and applicable normative
specifications. Independent executable loading must at minimum supersede
ADR-007 and ADR-001's v1 executable-extension subdecision. A change to the host
ABI, process, storage, persistence, or IPC boundary must separately supersede
the applicable ADR-001 and ADR-010 decisions. Without all required supersession
and higher-authority compatibility, Nabla cannot:

- download, install, load, or execute a module independently of the signed Core
  release;
- treat `signed_trusted` or `restricted_external` as activatable;
- use a host ABI, client IPC endpoint, script, WASM runtime, native library, or
  another payload as a plugin boundary;
- let package provenance or user installation approval grant authority;
- give a module raw DB, filesystem, network, secret, shell, reflection, or
  listener access;
- publish a partial or order-dependent Registry generation;
- claim same-process fatal-fault isolation; or
- delete canonical data as a consequence of disable or executable removal.

A compatible implementation specification may refine canonical serialization,
hashing, build inventory, diagnostics, and activation APIs without supersession
only when it preserves every decision and compatibility constraint above.

## Sources and evidence

- Accepted `ADR-001`: compile-time Rust module packages, signed Core product
  set, Core-owned storage, host-only C ABI, and shared-process failure limits.
- Accepted `ADR-010`: authenticated local client/Core IPC, single-writer
  lifecycle, and no module-owned endpoint or package-trust implication.
- `CONSTITUTION.md` v0.1: `CON:I6`, `CON:I15`, and `CON:4.2`.
- Active draft `ARCHITECTURE.md` v0.1: `ARCH:18`, `ARCH:20`, `ARCH:24`, and
  `ARCH:24.1`, consumed under the pre-baseline `draft-allowed` gate.
- Active draft `CAPABILITY-CONTRACT.md` v0.1: `CAP:5`, `CAP:9`, and `CAP:24`,
  consumed under that gate.
- Active draft `MODULE-MANIFEST.md` v0.1: `MOD:4`, `MOD:5`, `MOD:8`, `MOD:9`,
  `MOD:13`, and `MOD:26`, consumed under that gate.
- Active draft `DATA-CLASSIFICATION.md` v0.1: `DATA:6` and `DATA:12`, consumed
  under that gate for signing credentials and security evidence.
- Approved `SPEC-NAVIGATION.md` v0.4: `NAV:6` execution and evidence protocol.
- Prepared task context manifest:
  `6be4f929dff2bfb67fe8937c9760e84f4e9b269b76853e5e558e14c496381b58`.

## Approval

Pending explicit owner approval. Until approval is recorded, this ADR remains
proposed, `governance/decisions.yaml` remains `required` for `ADR-007`, and
`ADR-QUERY-DSL-001` remains blocked.
