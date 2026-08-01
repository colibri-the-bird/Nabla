# ADR-010: Authenticated local IPC and Core Service lifecycle

- **Status:** Proposed — owner approval required
- **Date:** 2026-08-01
- **Task:** `ADR-RUNTIME-BOUNDARY-001`
- **Decision owner:** Nabla project owner
- **Related decision:** `ADR-001`
- **Supersedes:** None

## Context

`ARCH:5.2` requires the Desktop UI and CLI to use one typed local IPC boundary
to a separate Core Service. The Core is the only logical writer, should start on
demand, and must not require a public network listener. `CON:I15` requires UI,
client, request, module, processor, and provider failures to remain localized.
`CAP:24` requires finite limits, deadlines, cancellation, backpressure, and
bounded retry.

The owner-approved `CORE-PORTABILITY-SPIKE-v1` demonstrated a bounded Rust
process adapter over NDJSON stdin/stdout, restart after a selected crash,
transaction rollback, idempotent replay, deadline checks around writer
admission, and an embedded C ABI shape on Windows x86-64. It explicitly did not
measure OS-native IPC, peer credentials, install-scoped authentication,
authorization, production cancellation, multi-client supervision, or a product
lifecycle. Its transport is therefore evidence that a process boundary is
feasible, not the production transport selection.

The prepared task manifest records `ARCHITECTURE.md`,
`CAPABILITY-CONTRACT.md`, `DATA-CLASSIFICATION.md`, and `MODULE-MANIFEST.md` as
“project for approval”. The task card requires
`required_spec_status: approved`. This record may be reviewed as a proposed
decision, but it cannot become accepted and the decision registry cannot change
until both an authoritative source-status correction and explicit owner
approval of this ADR are recorded. This ADR task does not modify those
normative sources.

## Decision

### 1. Desktop transport

Windows x86-64 Desktop v1 uses a user-scoped Windows named pipe in byte-stream
mode. The endpoint name includes a stable installation/profile identifier and
the data-plane pipe is created with an explicit access-control list limited to
the owning user SID. Broad groups such as `Everyone` or all authenticated users
are not granted access. Release management does not gain a business-data path
through this pipe. The server creates the pipe with
`PIPE_REJECT_REMOTE_CLIENTS` or an equivalent verified platform control and
rejects every remote pipe client; a user-scoped DACL alone is not treated as a
non-network guarantee.

The Core exposes no TCP listener, public network listener, browser port, or
machine-wide shared endpoint. A future desktop platform may provide a
user-scoped Unix-domain socket or another OS-native local transport through the
same transport port, but it is unsupported until its peer identity, filesystem
permissions, lifecycle, and failure behavior are tested. A transport adapter
cannot change command/query semantics.

The probe's stdin/stdout NDJSON channel remains test-only. Standard input and
output are not the production multi-client transport.

### 2. Framing and protocol negotiation

The pipe carries a versioned, length-prefixed UTF-8 JSON protocol. Each frame
has a four-byte unsigned big-endian byte length followed by one strict JSON
message. The wire specification must define a finite protocol maximum,
stricter per-kind limits, and streaming frame types before implementation.
Blob, backup, export, and other large payloads use bounded chunk streams and
never hidden full-buffer messages.

Every connection begins with a control handshake. No business request is
accepted until the peers negotiate:

- protocol major and supported minor range;
- Core installation/profile identity;
- server instance identity;
- self-asserted client kind and release version for compatibility/diagnostics,
  never as an authority grant;
- authentication described below;
- effective frame, concurrency, deadline, and stream limits.

An unknown major, incompatible range, malformed frame, any duplicate JSON
object key, unknown required message kind, invalid UTF-8, excessive nesting, or
oversized value fails closed before dispatch. Backwards-compatible optional
fields require a negotiated minor. There is no floating `latest` protocol.

Each request includes a unique request ID, exact command/query contract
reference, bounded payload, and relative deadline or no-later-than budget. The
Core evaluates elapsed time with a monotonic clock. Request IDs are diagnostic
correlation, not command idempotency. Mutating retries use the contract's full
idempotency scope and key.

### 3. Local authentication and authorization

Authentication uses both the OS endpoint boundary and an install-scoped `P4`
credential:

1. the named-pipe ACL restricts connection to the owning installation user;
2. the server impersonates and inspects the named-pipe client token, verifies
   that its user SID is the expected installation owner, and rejects a token it
   cannot validate or an unexpected integrity/session context;
3. the client and server each contribute a fresh 256-bit OS-CSPRNG nonce to a
   canonically encoded transcript that binds both advertised ranges, the exact
   selected major/minor, every negotiated effective limit, installation,
   profile, endpoint, server instance, client kind, and both nonces;
4. the server first proves possession of the install secret with
   HMAC-SHA-256 over a direction-labelled server transcript;
5. only after verifying the server, the client proves possession with a
   distinct direction-labelled HMAC over the same transcript;
6. authentication failure or replay closes the connection with no business
   dispatch and participates in finite rate limiting.

The secret is generated from the OS cryptographic RNG at installation or first
trusted initialization. It is classified `P4/SE` and stored outside the
canonical database through the platform Secret Service. UI, CLI, and ordinary
Core code receive only a purpose-bound authentication handle/use operation;
the raw value is not returned through a query or general application API. It is
never passed in command-line arguments, environment variables, exports, audit
bodies, logs, crash diagnostics, AI context, or protocol error text, and is
never transmitted as a bearer value. The versioned protocol contract fixes the
transcript canonicalization and direction labels so two implementations cannot
authenticate different bytes.

The install uses one current credential shared through the protected Secret
Service, not per-client pairing. Rotation invalidates existing sessions and old
handles; trusted installed clients reopen the current purpose-bound handle.
Missing or corrupt credentials fail closed; the Core does not fall back to
unauthenticated operation. Repair is a separately scoped administrative
workflow executed by the signed installed repair tool under the owner OS
identity with explicit confirmation. It stops and verifies the Core instance
before credential replacement and exposes no unauthenticated business or raw-
storage endpoint.

This handshake establishes membership in the local installation, not authority
over all Nabla data. Every request still passes capability version,
actor/consumer, data-scope, sensitivity, and policy authorization. There is no
administrative `execute arbitrary operation`, raw SQL, raw filesystem, or raw
database endpoint.

The verified session actor is derived inside the Core from the inspected OS
identity and server-owned installation/session policy. Administrative grants
come only from registered administrative capabilities and server-side policy.
A client-supplied actor, consumer kind, role, or `administrative` flag is
self-asserted input and cannot create or widen a grant; a mismatch is rejected
and audited without sensitive payload content.

UI and CLI share one `local_install_client` consumer authority in Desktop v1.
Their self-asserted kind may select diagnostics or compatible presentation, but
not a different permission set. Module, AI, device, migration, recovery, and
other actor/consumer identities are never accepted merely because an IPC client
names them; they require their own server-verified invocation path.

The process boundary is not claimed to isolate Nabla from malicious code already
running as the same OS user. The shared credential proves possession of the
current installation secret, not the identity or integrity of a client binary.
Unless a supported platform Secret Service enforces a separately tested
application/package-bound use policy, same-user rogue code may obtain the same
`local_install_client` authority. This is an explicitly accepted residual under
the `ARCH:18.1` local-rogue-process threat, not a claimed security boundary.
ACL, peer identity, and handshake reject cross-user and clients lacking the
current installation credential; capability authorization and data policy
remain mandatory defense inside the Core.

### 4. Single instance and startup

One Core Service runs for one canonical storage root. The installed launcher
uses a fixed product-manifest path and direct argv execution without a shell.
UI and CLI follow this bounded algorithm:

1. connect to the expected protected endpoint;
2. if absent, invoke the trusted launcher once;
3. wait for authenticated health/readiness with a finite timeout and bounded
   backoff;
4. surface a typed unavailable, incompatible, recovery, or repair state rather
   than starting an alternate writer.

The Core loads the purpose-bound credential first, then acquires an OS-backed
exclusive instance/storage lock before binding the data-plane pipe or opening a
write connection. Only the lock winner creates the pipe and enters
authentication-ready health; a concurrent launch loser never exposes an
endpoint and instead connects to the winner or exits. A PID or readiness file
is diagnostic only and cannot replace the OS lock or authenticated connection.

Startup proceeds through explicit health states:

```text
starting
-> credential_ready
-> instance_locked
-> endpoint_auth_ready
-> storage_recovered
-> integrity_checked
-> migrations_checked
-> registry_activated
-> ready
```

An incompatible schema, failed recovery, failed integrity check, migration
block, registry failure, or missing credential enters a typed degraded or
blocked state. Ordinary commands are not admitted before `ready`. If the
credential is available, a minimal authenticated health and recovery surface
may remain available without exposing raw storage. If it is unavailable, the
Core publishes no unauthenticated IPC repair surface; the trusted launcher
reports a bounded local status and directs the owner to the signed out-of-band
repair workflow defined above.

### 5. Runtime, idle, and shutdown lifecycle

The Core starts on demand under the owning user's session; it is not a mandatory
boot service. It remains alive while at least one client session, accepted
durable workflow, scheduled or due processor/job, migration/recovery operation,
backup, or other declared keep-alive reason exists. A future durable timer that
must run while the user session remains active keeps the Core alive until it is
due or cancelled. Desktop v1 does not claim an OS wake or post-reboot timing
guarantee; work persisted across logout, reboot, or stopped Core resumes at the
next successful start and reports its lateness.

When none exists, the Core may shut down after a finite configured idle grace.
Graceful shutdown:

1. changes health to `draining` and rejects new ordinary work;
2. permits in-flight transactions to finish or cancel within their declared
   bounds;
3. persists durable workflow/outbox state and stops processors;
4. performs the configured SQLite checkpoint/close and blob-staging cleanup;
5. closes the endpoint, releases the instance lock, and removes only ephemeral
   endpoint metadata.

Shutdown never deletes canonical data or performs purge. If a requested
shutdown exceeds its declared deadline, only the signed launcher/updater
running under the owner identity may terminate the exact authenticated Core
instance. It verifies process identity and exit, never breaks or forges the
storage lock, and does not start a replacement until the old process is gone and
the OS lock can be acquired normally. The next start follows the unclean
recovery path. UI exit alone does not kill a Core that still has a declared
keep-alive reason.

The signed launcher owns restart backoff and a protected crash-attempt ledger.
UI/CLI may ask that launcher to relaunch Core after a disconnect but does not
act as a supervisor or bypass its policy; without a running launcher/client,
Desktop v1 makes no autonomous restart guarantee. Relaunch uses finite backoff
and a finite crash-loop threshold. Once the threshold is reached, launch stops
and the UI/CLI surfaces a blocked health state and the trusted repair path; it
does not create an unbounded restart loop.

### 6. Disconnect, cancellation, retry, and crash behavior

A client disconnect cancels only work that remains safely cancellable. It does
not roll back a transaction that has committed and does not imply that an
in-flight command failed.

After timeout, disconnect, or Core crash:

- queries may retry within their finite policy;
- a mutation with the exact idempotency scope, key, and fingerprint may retry
  and receive its committed result;
- a mutation without that protection is never retried automatically when its
  commit status is unknown;
- outbox and durable jobs resume idempotently after recovery;
- clients receive a typed `CORE_UNAVAILABLE` or `OUTCOME_UNKNOWN` category and
  a correlation ID, without sensitive payloads in diagnostics.

A malformed or failing client connection is its own failure domain. Parser,
authentication, or authorization failure closes that connection and cannot
crash the Core or affect another client. A handler exception rolls back only its
transaction. A Core process failure may interrupt every client. The single-
writer lock and SQLite transaction/recovery design are normative protections;
the portability spike observed one bounded synthetic abort/reopen case only.
Production claims still require integrity, corruption, backup, restore, disk,
and OS-failure evidence required by `CON:I15`.

### 7. Upgrade and compatibility lifecycle

UI, CLI, and Core are released as one compatible signed product set, but stale
clients are expected. Handshake negotiation rejects incompatible protocol or
installation identities before a business request. Each release declares exact
supported protocol ranges and test fixtures; compatibility is not inferred
from version ordering.

An updater requests graceful drain, verifies process exit and lock release,
then atomically activates one signed product generation. Side-by-side Core
versions never write the same storage root. Package rollback cannot silently
roll back an incompatible schema; migration and recovery remain governed by
ADR-012 and the applicable backup decision.

Mobile Embedded Core does not use Desktop IPC or the install handshake. Its
host adapter must preserve the same command meaning, authorization, finite
limits, transaction ownership, and error semantics; ADR-001 and a future
platform contract own its ABI and host-specific lifecycle rather than reusing
Desktop transport states by implication.

## Compatibility constraints

1. Named-pipe access and a successful handshake are both required before any
   business dispatch; neither replaces per-capability authorization.
2. The Core endpoint is local, user-scoped, non-public, and non-networked.
3. Only the lock holder may open the canonical database for write.
4. Transport adapters preserve exact command/query meaning and error categories.
5. Major protocol incompatibility, unknown installation identity, and failed
   authentication fail closed.
6. Requests, frames, streams, queues, deadlines, concurrency, and retries have
   finite declared limits.
7. Unknown mutation outcome is resolved through scoped idempotency, never blind
   replay.
8. Startup and upgrade never expose a partially activated Registry generation
   or silently downgrade schema.

## Consequences

### Positive

- Windows named pipes satisfy the local, user-scoped, no-public-listener
  boundary without opening a TCP port.
- OS ACL, peer inspection, and transcript authentication provide layered proof
  of OS-user and current-installation credential possession while retaining
  capability authorization and explicitly not claiming same-user binary
  identity.
- A strict framed protocol is independently fuzzable and portable to another
  local byte-stream transport.
- Single-instance and explicit readiness states preserve one writer and make
  recovery visible to UI and CLI.
- Idempotency rules give clients a safe response to ambiguous disconnects and
  process crashes.

### Costs and risks

- Windows security descriptors, peer-token inspection, secret storage, and
  rotation require dedicated implementation and adversarial tests.
- Same-user malicious code remains outside the claimed isolation boundary.
- JSON framing is not free; large data requires a separate bounded streaming
  path and strict parser limits.
- On-demand launch, racing clients, idle shutdown, update drain, and stale
  endpoints create a non-trivial lifecycle state machine.
- Unix-domain-socket and other platform adapters remain unmeasured and may
  require platform-specific authentication appendices.
- The portability spike did not test the selected named pipe or handshake, so
  production implementation is gated by integration and fault-injection tests.

## Alternatives considered

| Alternative | Disposition | Reason |
|---|---|---|
| Windows named pipe with ACL, peer check, and install handshake | Selected for Desktop v1 | It is OS-native, local, user-scoped, supports multiple clients, and introduces no public listener. |
| Probe NDJSON over child stdin/stdout | Rejected for production | It was measured only as a bounded probe and does not provide the selected multi-client identity, lifecycle, or endpoint model. |
| Loopback TCP with install authentication | Rejected for v1 | `ARCH:5.2` allows it conditionally, but it adds a listener, port discovery, firewall/proxy ambiguity, and a broader attack surface without measured benefit. |
| Unauthenticated pipe protected only by endpoint secrecy | Rejected | Endpoint names are not credentials and do not bind a client to the installation. |
| ACL-only authentication | Rejected | It provides no installation or protocol-transcript binding; the selected shared credential adds those properties but still does not establish same-user binary identity. |
| UI-hosted in-process Core | Rejected for Desktop production | It violates the required process and storage-ownership boundary and couples UI failure to Core availability. |
| Machine-wide always-on service | Rejected | It expands privilege, multi-user, upgrade, and secret-management scope beyond the user-scoped offline product. |
| Public or remote RPC endpoint | Rejected | It violates the local-only Desktop boundary and would require a separate network authority, pairing, transport-security, and threat-model decision. |

## Validation obligations

Before Desktop production use, the acceptance suite must cover:

- named-pipe DACL and peer identity under allowed and denied Windows accounts,
  plus rejection of remote named-pipe connections;
- mutual transcript-HMAC success, wrong server/client proof, replay, transcript
  mismatch, secret rotation, missing-secret repair, and redaction;
- actor/consumer/admin spoof attempts and server-side session binding;
- strict framing, parser fuzzing, nesting/size limits, malformed input, and
  bounded stream backpressure;
- concurrent launch races, stale diagnostics metadata, single lock ownership,
  readiness timeout, and no second writer;
- clean and forced shutdown at each lifecycle phase, startup recovery, and
  preservation of committed state;
- scheduled-work keep-alive, resume-after-restart lateness, bounded restart
  backoff, and crash-loop cutoff;
- disconnect and deadline points before, during, and after commit, including
  safe idempotent retry and explicit unknown outcome;
- UI, CLI, connection, handler, module, processor, provider, and Core process
  failure domains;
- stale/incompatible clients and signed upgrade/rollback flows.

Exact wire schemas, frame limits, error codes, endpoint identifiers, and secret
storage adapters must be frozen in versioned implementation contracts before
code is accepted. They may refine this decision but cannot weaken its boundary.

## Deferred decisions

This ADR does not authorize network synchronization, remote clients, a browser
listener, cross-user sharing, machine-wide service mode, arbitrary operations,
or dynamic executable modules. It does not choose sync pairing, transport
encryption, production DDL, migrations, backup format, or Mobile wrapper
details.

## Supersession rules

A new accepted ADR must explicitly supersede ADR-010 before Nabla can:

- use TCP, a public listener, or any remote endpoint for Desktop UI/CLI access
  to the local Core (this does not govern the separately authorized v2 sync
  transport);
- remove either the OS access boundary or install-scoped authenticated
  handshake;
- replace the four-byte JSON framing or mutual transcript-authentication
  scheme with an incompatible design;
- permit multiple Core writers for one storage root;
- make the production Desktop Core in-process or machine-wide;
- automatically replay mutations with unknown outcomes without scoped
  idempotency; or
- weaken fail-closed major-version, installation-identity, or startup gates.

A platform-local transport adapter or backwards-compatible protocol minor does
not require supersession only when it preserves the authentication,
authorization, single-writer, lifecycle, limit, and failure semantics above and
adds platform-specific evidence.

## Sources and evidence

- `CONSTITUTION.md` v0.1: `CON:I15` and the conformance rules in `CON:7`.
- `ARCHITECTURE.md` v0.1: `ARCH:5`, `ARCH:6`, `ARCH:20`, `ARCH:24`, and
  `ARCH:24.3`, subject to the source-status gate above.
- `CAPABILITY-CONTRACT.md` v0.1: `CAP:24`, subject to the source-status gate
  above.
- `DATA-CLASSIFICATION.md` v0.1: `DATA:6` and `DATA:12`, subject to the
  source-status gate above; the install credential is `P4/SE` and
  `PROTECT_SECRET_STORE`.
- `MODULE-MANIFEST.md` v0.1: `MOD:9` and `MOD:13`, subject to the source-status
  gate above.
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
proposed and `governance/decisions.yaml` remains `required` for `ADR-010`.
