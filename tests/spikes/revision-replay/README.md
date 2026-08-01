# Revision, outbox and replay spike harness

This directory contains the bounded, standard-library-only experiment for
`SPIKE-REVISION-REPLAY-001`. It is test code, not a production persistence or
synchronization implementation.

Run the experiment and write a raw result:

```text
python tests/spikes/revision-replay/run_experiment.py --output tests/spikes/revision-replay/results/windows_x86_64.json
```

Re-run it and compare the semantic result with the checked-in result:

```text
python tests/spikes/revision-replay/run_experiment.py --verify tests/spikes/revision-replay/results/windows_x86_64.json
```

The experiment uses deterministic fixture IDs, local SQLite databases in a
temporary directory, explicit subprocess checkpoints, and process termination
to exercise selected crash boundaries. Correctness never depends on a wall
clock, an unordered SQL result, a temporary path, a process ID, or measured
latency.

Measured cases cover:

- bounded offline identity generation on two devices;
- immutable parented revisions, optimistic conflict, concurrent heads, an
  explicit merge, and a tombstone revision;
- the specified idempotency scope and fingerprint behavior;
- atomic command/revision/outbox commit before and after a killed process;
- duplicate delivery and a killed consumer after its local effect transaction
  but before producer acknowledgement;
- typed missing-parent buffering with a bounded fixed point; and
- all 24 arrival permutations of ancestor, two concurrent descendants, and
  merge, with duplicate injection.

The SHA-256-derived fixture encoding, schema, full-snapshot payloads, SQLite
backend, retry bounds, and event envelope are experimental choices. They do not
select a production ID format, revision DDL, snapshot/patch strategy, runtime
boundary, transport, or synchronization protocol.
