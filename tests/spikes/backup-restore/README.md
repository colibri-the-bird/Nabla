# Backup/restore measurement harness

This directory contains the bounded experiment for
`SPIKE-BACKUP-RESTORE-001`. It is test-only code. It is not a production
backup format, recovery implementation, retention policy, purge workflow, or
encryption design.

## Canonical run

From the repository root:

```text
python tests/spikes/backup-restore/run_experiment.py --output tests/spikes/backup-restore/results/windows_x86_64.json
```

The command uses only the Python standard library, creates isolated temporary
working directories, and returns exit code `0` only when every required
assertion passes. Absolute temporary paths are not written to the result.

## Measured boundaries

The harness records:

1. a quiescent SQLite online backup and snapshot-derived blob manifest;
2. an online backup while a bounded WAL writer commits;
3. the stale-data hazard of copying only the live SQLite main file;
4. rejection of a manifest derived from a different DB generation;
5. restore into an empty versioned installation;
6. process termination during DB backup, blob copy, and restore staging;
7. database-header corruption with both outer-checksum and SQLite detection;
8. missing, truncated, and same-size-corrupt blobs;
9. disappearance of a source blob after the DB snapshot but before publication.

Each expected-failure case passes only when preflight rejects the candidate and
the current source or active installation remains unchanged. Exact SQLite error
text, online-backup progress counts, and the generation captured during a
concurrent commit are observations rather than portable assertions.

## Fixture

`fixtures/generation-v1.json` defines fixed IDs, timestamps, sizes, limits, and
two complete logical generations. Blob bytes are generated deterministically
from the declared seeds and stored by SHA-256 identity inside the temporary
fixture. The SQLite database stores only computed identities, sizes, and
relative hash paths.

The experiment derives the blob manifest from the completed SQLite snapshot,
never from the subsequently changing live database. A bundle is considered
published only after layered verification and a final completeness marker.

## Crash injection

`worker.py` writes and flushes a checkpoint marker at the selected failpoint,
then blocks. The parent waits for that exact checkpoint and terminates the
worker with `Popen.kill()` under a finite timeout. This avoids timing-based
fault injection on Windows. Residual staging files are diagnostic observations;
they are never treated as a published bundle.

## Important limitations

- The harness does not claim power-loss durability for directory or pointer
  operations on Windows.
- It does not choose a production container, encryption, key-recovery, GC
  pinning, retention, or migration policy.
- Python 3.12.7 in the canonical environment embeds SQLite 3.45.3. The run
  disables automatic checkpoints and does not combine concurrent checkpoint
  and write stress because that runtime predates later WAL-reset fixes.
- SQLite structural checks are combined with foreign-key, logical-generation,
  DB/manifest closure, size, and content-hash checks; `integrity_check` alone is
  not treated as sufficient.
