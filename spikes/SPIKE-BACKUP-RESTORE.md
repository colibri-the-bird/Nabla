# Nabla backup/restore spike

## Artifact identity

| Field | Value |
|---|---|
| Task | `SPIKE-BACKUP-RESTORE-001` |
| Artifact | `BACKUP-RESTORE-SPIKE-v1` |
| Status | Measured draft for owner approval |
| Execution time | 2026-07-27T19:31:08Z (2026-07-28 local) |
| Context manifest | `a467a76c8fa87cf5d9a807dfb5668dc8279ec646739d86291d0fff4757f1690a` |
| Raw result | `tests/spikes/backup-restore/results/windows_x86_64.json` |
| Raw result SHA-256 | `d4eceb03e436eb607b8144fd6cbf8e3250cd98da3f9b196c91a66667ff9c6710` |
| Pull request | Pending draft publication |
| Owner approval | Pending |

This report is measured input to later specification and ADR work. The
experimental directory bundle and versioned activation pointer used by the
harness are not production contracts.

## Outcome

The canonical run passed all **13 cases and 36 required assertions** on Windows
11, Python 3.12.7, and SQLite 3.45.3.

The measurement supports the following bounded conclusions:

1. Python/SQLite online backup produced a structurally and logically valid DB
   snapshot in both quiescent and bounded-concurrent cases.
2. The blob manifest must be derived from the completed DB snapshot. A manifest
   derived from a later live generation was rejected deterministically.
3. Immutable blob bytes may be copied after the DB snapshot only while every
   referenced hash remains available and verifiable. Losing a referenced source
   blob blocked publication.
4. Copying only the live SQLite main file in WAL mode is unsafe as a backup
   mechanism: the copy remained structurally valid but silently exposed
   generation 1 while the live DB had committed generation 2.
5. An incomplete DB backup, partial blob, corrupt DB, missing blob, truncated
   blob, or same-size blob corruption was rejected before activation.
6. Staging restore into a versioned directory preserved the current active
   generation when the worker was terminated before pointer activation; a
   fresh retry from the intact bundle succeeded.
7. A successful restore requires layered verification. SQLite
   `integrity_check` alone cannot establish DB/blob generation closure or detect
   a logically stale main-file-only copy.

The spike does **not** choose a production container, encryption/key-recovery
model, retention policy, purge behavior, GC pin mechanism, migration policy, or
power-loss-safe activation protocol.

## Scope and method

The harness is standard-library-only and lives under
`tests/spikes/backup-restore/`. Every case runs in an isolated temporary
directory and records no absolute temporary path.

The deterministic fixture declares two complete logical generations:

- generation 1: two canonical records, three unique immutable blobs, and four
  blob references;
- generation 2: one additional record, one additional immutable blob, and two
  additional references;
- the DB contains 384 fixed padding rows so stepped backup and process
  termination reach deterministic progress checkpoints;
- blobs include zero-byte, 8 KiB, 256 KiB, and 1 MiB boundaries and are stored
  at `blobs/sha256/<prefix>/<full-hash>`;
- SQLite settings are page size 4096, WAL, `synchronous=FULL`,
  `wal_autocheckpoint=0`, `user_version=1001`, and a 5-second busy timeout.

The experimental bundle contains:

```text
COMPLETE.json
manifest.json
checksums.json
database/snapshot.sqlite3
blobs/sha256/<prefix>/<full-hash>
```

`COMPLETE.json` is written last, after layered validation. A directory without
that marker is explicitly incomplete and is never treated as published.

Restore copies a verified candidate into a new versioned staging directory,
repeats DB and blob verification, renames it to a previously absent generation
directory, and finally replaces a small `ACTIVE` pointer file. This is adequate
for the process-termination experiment. It is not evidence of power-loss
durability on Windows.

## Verification layers

The harness checks, in order:

1. completeness marker, format/version, safe relative paths, and member closure;
2. manifest and checksum-manifest hashes;
3. every declared member size and SHA-256;
4. SQLite read-only open, `PRAGMA integrity_check`,
   `PRAGMA foreign_key_check`, and `user_version`;
5. logical generation and semantic digest of sorted canonical rows;
6. exact DB blob-reference ↔ blob-object ↔ bundle-manifest closure;
7. blob size, content hash, and hash-path identity;
8. staged restore equivalence before activation;
9. preservation of the current active generation on every rejected candidate.

Static snapshot files are opened with SQLite `immutable=1` during verification
so validation does not create empty WAL/SHM sidecars inside a candidate bundle.
Live databases are opened normally so committed WAL state is visible.

## Case matrix

| Case | Required result | Canonical observation |
|---|---|---|
| `QUIESCENT_ONLINE_SNAPSHOT` | DB snapshot and snapshot-derived bundle verify | Generation 1; 826 pages; 3,383,296 DB bytes; 3 blobs / 1,056,768 bytes |
| `CONCURRENT_WAL_ONLINE_SNAPSHOT` | Bounded writer commits; snapshot is one complete generation | Captured generation 2 in this run; generation 1 or 2 is permitted |
| `LIVE_WAL_MAIN_FILE_COPY_NEGATIVE_CONTROL` | Main-file-only copy is shown unsafe | Live generation 2, copy generation 1; copied DB still returned `integrity_check=ok`; WAL was 32,992 bytes |
| `LIVE_MANIFEST_NEGATIVE_CONTROL` | Newer live manifest is rejected against older snapshot | `DB_MANIFEST_GENERATION_MISMATCH` |
| `CLEAN_INSTALL_RESTORE` | Verified generation 2 restores into empty install | 3 records; 4 blobs / 1,318,912 bytes; semantic digest preserved |
| `INTERRUPTED_DATABASE_BACKUP` | Exact progress checkpoint, no publication, source unchanged | Killed after callback 3 with 823/826 pages remaining; residual destination was 0 bytes in this run |
| `INTERRUPTED_BLOB_COPY` | Partial file is not promoted | Killed after two 64 KiB chunks; 131,072-byte `.partial` remained |
| `INTERRUPTED_RESTORE_BEFORE_ACTIVATION` | Active generation unchanged; fresh retry succeeds | `baseline-g1` remained active; `retry-g2` then activated successfully |
| `DATABASE_HEADER_CORRUPTION` | Outer and SQLite layers independently reject | `MEMBER_CHECKSUM_MISMATCH`, then `SQLITE_CORRUPT` after outer checksum refresh |
| `MISSING_BLOB_IN_BUNDLE` | Missing member rejects candidate; other blobs remain valid | `MISSING_MEMBER` |
| `PARTIAL_BLOB_IN_BUNDLE` | Truncation rejects candidate after outer checksum refresh | 1,048,576 → 524,288 bytes; `BLOB_SIZE_MISMATCH` |
| `SAME_SIZE_BLOB_CORRUPTION` | Same-size mutation rejects by content identity | `BLOB_CONTENT_HASH_MISMATCH` |
| `SOURCE_BLOB_DISAPPEARS_AFTER_SNAPSHOT` | Backup cannot publish and staging remains incomplete | `SOURCE_BLOB_MISSING`, then `BUNDLE_INCOMPLETE` |

### Assertions versus observations

The following are required portable assertions:

- a snapshot represents one complete logical generation;
- DB/manifest/blob closure is exact;
- every required file has the declared size and SHA-256;
- a failed backup has no published completeness marker;
- a failed restore does not change the active generation;
- corruption and missing/partial members fail closed;
- retry from an intact bundle can succeed.

The following are environment-specific observations and must not become
portable requirements:

- whether a concurrent online backup captures generation 1 or 2;
- progress callback count, remaining-page sequence, and duration;
- exact worker termination return code;
- exact partial SQLite destination size after hard termination;
- exact SQLite error wording;
- filesystem cleanup and metadata persistence behavior after power loss.

## Consistency-boundary findings

### SQLite boundary

The online backup snapshot is the measured DB boundary. The concurrent case
allowed one finite writer transaction to commit after the first stepped-backup
callback. The destination captured generation 2 in the canonical run and
passed structural, foreign-key, generation, and semantic checks. The assertion
permits generation 1 or 2 because SQLite may restart an incremental backup when
the source changes; only internal completeness is required.

The negative raw-copy control held an active generation-1 read mark, committed
generation 2 into WAL, and copied only the main DB file. The copied file opened
and passed `integrity_check`, but it exposed generation 1. Therefore structural
integrity is not proof that a live-file copy includes the latest committed
state.

### DB/blob boundary

SQLite backup covers the database, not external blob files. The measured safe
sequence is:

1. complete the SQLite snapshot;
2. read the logical generation and blob identities from that snapshot;
3. copy only those immutable hash-path members;
4. verify size/hash and exact DB/manifest closure;
5. write the completeness marker only after all validation succeeds.

Immutability alone is insufficient. When a referenced source blob was removed
between steps 2 and 3, the backup correctly remained unpublished. A later
design must therefore provide a bounded pin/lease/retention relationship
between snapshot manifest capture and blob-copy completion, but this spike does
not choose that mechanism.

### Restore boundary

Every corrupted/incomplete candidate failed in preflight before pointer
activation. A process terminated after full staging verification left the
previous `baseline-g1` pointer and semantic digest unchanged. A separate
`retry-g2` staging attempt from the original intact bundle then succeeded.

This demonstrates the value of staging and late activation. It does not prove
filesystem or directory durability across OS/power failure, nor does it select
the production activation primitive.

## Inputs for later specification and ADR work

The following requirements are supported by measured evidence:

1. A live SQLite backup must use the Online Backup API or another explicitly
   quiescent/transactionally equivalent mechanism. Main-file-only copying in
   WAL mode must not be accepted as a complete backup.
2. Each DB snapshot needs a logical generation marker. The blob manifest must
   be derived from that snapshot, not from the mutable live DB.
3. Referenced blob bytes must remain available from manifest capture through
   checksum-complete publication. Missing bytes make the backup incomplete.
4. Publication needs an explicit final completeness record written only after
   DB, member, and closure verification.
5. Restore must validate format/schema availability, member checksums,
   SQLite integrity, foreign keys, logical invariants, DB/blob closure, and blob
   identity before activation.
6. Restore must use an isolated staging generation. A failed candidate must not
   mutate the current working set.
7. Error categories should distinguish incomplete bundle, member checksum,
   SQLite corruption, logical generation mismatch, missing blob, size mismatch,
   and content-hash mismatch.
8. Periodic restore testing is required; successful backup creation alone is
   insufficient evidence of recoverability.
9. Resource bounds must include DB step size, blob chunk size, timeouts, busy
   timeout, staging capacity, and finite retry/backoff.

The following remain deliberately unresolved:

- physical archive/container and canonical JSON profile;
- full/incremental backup model and backup generation identity;
- encryption, key recovery, maximum sensitivity handling, and destination
  protection;
- retention, purge, tombstones, backup-aware blob GC, and the concrete
  pin/lease mechanism;
- production cross-platform activation and power-loss durability;
- schema/migration compatibility and unknown/inactive module handling;
- scheduling, cancellation, resume, storage quotas, and cleanup;
- backup validation frequency and recovery reporting contract.

## Invariant and selector trace

| Requirement | Measurement |
|---|---|
| `ARCH:11` / acceptance `I11` blob identity and immutability boundary | SHA-256 hash paths, no in-place mutation in the source, size/hash verification, missing/corrupt/partial fault cases |
| `CON:I15` / acceptance `I15` failure localization | DB, blob, backup-job, and restore-staging failures are isolated; active/source semantic digests remain unchanged |
| `CON:I16` / acceptance `I16` backup versus export | Harness labels its artifact backup/restore-only and does not claim portable export semantics |
| `ARCH:19` | Consistent DB snapshot, snapshot-derived blob manifest, staged restore, integrity checks, and restore test |
| `ARCH:20` | Typed diagnostics and bounded failure domains |
| `ARCH:24.3` | Required backup/restore spike executed without production implementation |
| `DATA:10` | Canonical DB state is included; all in-scope canonical blob bytes are required; derived/device-local/secrets are explicitly excluded |
| `MOD:19` | Experimental manifest records versions, canonical DB, blobs, checksums, and exclusions |
| `CAP:24` | Finite step, chunk, busy, and subprocess timeout limits |

## Environment caveat

The canonical Python runtime embeds SQLite 3.45.3. Current SQLite documentation
records a rare WAL-reset corruption race in older versions and identifies later
fix releases. This spike therefore:

- records the exact SQLite runtime;
- disables automatic checkpoints;
- does not combine concurrent checkpoint and write stress;
- does not generalize the successful result to that excluded race;
- treats a runtime upgrade/backport requirement as input to later runtime and
  backup decisions.

## Reproduction and raw evidence

Canonical command:

```text
python tests/spikes/backup-restore/run_experiment.py --output tests/spikes/backup-restore/results/windows_x86_64.json
```

The canonical command was run twice consecutively after the final harness fix;
both runs returned exit code 0 with 13/13 cases and 36/36 assertions passing.
The committed raw result is the second run.

Key files:

- fixture: `tests/spikes/backup-restore/fixtures/generation-v1.json`;
- harness: `tests/spikes/backup-restore/run_experiment.py`;
- shared test helpers: `tests/spikes/backup-restore/_spike_harness.py`;
- crash worker: `tests/spikes/backup-restore/worker.py`;
- raw result: `tests/spikes/backup-restore/results/windows_x86_64.json`.

Primary references:

- [Python `sqlite3.Connection.backup`](https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Connection.backup);
- [SQLite Online Backup API](https://www.sqlite.org/backup.html);
- [SQLite WAL](https://www.sqlite.org/wal.html);
- [SQLite causes of corruption](https://www.sqlite.org/howtocorrupt.html);
- [SQLite `PRAGMA integrity_check`](https://www.sqlite.org/pragma.html#pragma_integrity_check).

## Owner gate

Until explicit owner approval:

- this report remains a measured draft;
- `BACKUP-RESTORE-SPIKE` remains `required`;
- `SPIKE-BACKUP-RESTORE-001` remains `ready`;
- `SPIKE-REVISION-REPLAY-001` remains `blocked`.

Owner approval must explicitly confirm the measurements and conclusions,
authorize publication of `BACKUP-RESTORE-SPIKE`, completion of this task, and
activation of `SPIKE-REVISION-REPLAY-001` as the sole successor.
