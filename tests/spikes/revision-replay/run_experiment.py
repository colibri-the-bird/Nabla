"""Run the reproducible SPIKE-REVISION-REPLAY-001 experiment."""

from __future__ import annotations

import argparse
import copy
import hashlib
import inspect
import itertools
import json
import os
import platform
import sqlite3
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from _spike_harness import (
    ExperimentStore,
    IdempotencyConflict,
    RevisionConflict,
    canonical_json,
    replay_until_fixed_point,
    sha256_json,
    stable_id,
)


HERE = Path(__file__).resolve().parent
FIXTURE_PATH = HERE / "fixtures" / "scenario-v1.json"
WORKER_PATH = HERE / "worker.py"
TASK_ID = "SPIKE-REVISION-REPLAY-001"
ARTIFACT_ID = "REVISION-SYNC-PREPARATION-SPIKE"
CRASH_TIMEOUT_SECONDS = 10.0
MAX_REPLAY_PASSES = 6


@dataclass
class CaseChecks:
    names: list[str] = field(default_factory=list)

    def require(self, name: str, condition: bool) -> None:
        self.names.append(name)
        if not condition:
            raise AssertionError(name)


def load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def fixture_sha256() -> str:
    return hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest()


def commit(
    store: ExperimentStore,
    fixture: dict[str, Any],
    *,
    device: str,
    entity_id: str,
    payload_name: str,
    expected: Sequence[str],
    key: str,
    command_sequence: int,
    request_id: str,
    actor: str | None = None,
    capability_id: str | None = None,
    major_version: int | None = None,
    exact_version: str | None = None,
    contract_hash: str | None = None,
    merge_intent: bool = False,
    tombstone: bool = False,
    stable_options: dict[str, Any] | None = None,
    command_id: str | None = None,
) -> Any:
    capability = fixture["capability"]
    return store.commit_command(
        verified_actor=actor or fixture["actor"],
        origin_device=device,
        capability_id=capability_id or capability["id"],
        major_version=(
            capability["major_version"] if major_version is None else major_version
        ),
        exact_version=exact_version or capability["exact_version"],
        contract_hash=contract_hash or capability["contract_hash"],
        idempotency_key=key,
        command_id=command_id or stable_id("command", device, command_sequence),
        request_id=request_id,
        entity_id=entity_id,
        payload=fixture["payloads"][payload_name],
        expected_revisions=list(expected),
        merge_intent=merge_intent,
        tombstone=tombstone,
        stable_options=stable_options or {"fixture_mode": "revision-graph"},
    )


def build_graph(root: Path, fixture: dict[str, Any]) -> dict[str, Any]:
    """Build concurrent branches in separate stores, then an explicit merge."""

    root.mkdir(parents=True, exist_ok=True)
    device_a = fixture["devices"]["a"]
    device_b = fixture["devices"]["b"]
    device_c = fixture["devices"]["c"]
    entity_id = stable_id("entity", device_a, 42)

    database_a = root / "graph-device-a.sqlite3"
    with ExperimentStore(database_a) as store_a:
        root_result = commit(
            store_a,
            fixture,
            device=device_a,
            entity_id=entity_id,
            payload_name="root",
            expected=[],
            key="graph-root",
            command_sequence=1001,
            request_id="request-graph-root",
        )
        root_event = store_a.outbox_event(root_result.receipt["event_id"])
        branch_a_result = commit(
            store_a,
            fixture,
            device=device_a,
            entity_id=entity_id,
            payload_name="branch_a",
            expected=[root_result.receipt["revision_id"]],
            key="graph-branch-a",
            command_sequence=1002,
            request_id="request-graph-branch-a",
        )
        branch_a_event = store_a.outbox_event(branch_a_result.receipt["event_id"])

    database_b = root / "graph-device-b.sqlite3"
    with ExperimentStore(database_b) as store_b:
        store_b.seed_source_event(root_event)
        branch_b_result = commit(
            store_b,
            fixture,
            device=device_b,
            entity_id=entity_id,
            payload_name="branch_b",
            expected=[root_result.receipt["revision_id"]],
            key="graph-branch-b",
            command_sequence=2001,
            request_id="request-graph-branch-b",
        )
        branch_b_event = store_b.outbox_event(branch_b_result.receipt["event_id"])

    database_c = root / "graph-merge.sqlite3"
    with ExperimentStore(database_c) as store_c:
        for event in (root_event, branch_a_event, branch_b_event):
            store_c.seed_source_event(event)
        concurrent_heads = store_c.current_heads(entity_id)
        before_partial_merge_counts = store_c.source_counts()
        before_partial_merge_digest = store_c.source_semantic_digest()
        partial_merge_conflict: tuple[str, ...] | None = None
        try:
            commit(
                store_c,
                fixture,
                device=device_c,
                entity_id=entity_id,
                payload_name="merged",
                expected=[branch_a_result.receipt["revision_id"]],
                key="graph-partial-merge",
                command_sequence=3000,
                request_id="request-graph-partial-merge",
                merge_intent=True,
            )
        except RevisionConflict as error:
            partial_merge_conflict = error.current_heads
        after_partial_merge_counts = store_c.source_counts()
        after_partial_merge_digest = store_c.source_semantic_digest()
        merge_result = commit(
            store_c,
            fixture,
            device=device_c,
            entity_id=entity_id,
            payload_name="merged",
            expected=concurrent_heads,
            key="graph-explicit-merge",
            command_sequence=3001,
            request_id="request-graph-explicit-merge",
            merge_intent=True,
        )
        merge_event = store_c.outbox_event(merge_result.receipt["event_id"])
        heads_after_merge = store_c.current_heads(entity_id)
        tombstone_result = commit(
            store_c,
            fixture,
            device=device_c,
            entity_id=entity_id,
            payload_name="tombstone",
            expected=[merge_result.receipt["revision_id"]],
            key="graph-tombstone",
            command_sequence=3002,
            request_id="request-graph-tombstone",
            tombstone=True,
        )
        tombstone_event = store_c.outbox_event(tombstone_result.receipt["event_id"])
        heads_after_tombstone = store_c.current_heads(entity_id)

    return {
        "database_a": database_a,
        "database_b": database_b,
        "database_c": database_c,
        "entity_id": entity_id,
        "events": {
            "root": root_event,
            "branch_a": branch_a_event,
            "branch_b": branch_b_event,
            "merge": merge_event,
            "tombstone": tombstone_event,
        },
        "heads": {
            "concurrent": concurrent_heads,
            "merged": heads_after_merge,
            "tombstone": heads_after_tombstone,
        },
        "partial_merge_conflict": list(partial_merge_conflict or ()),
        "partial_merge_digest_unchanged": (
            before_partial_merge_digest == after_partial_merge_digest
        ),
        "partial_merge_effect_delta": {
            key: after_partial_merge_counts[key] - before_partial_merge_counts[key]
            for key in before_partial_merge_counts
        },
    }


def case_identity(root: Path, fixture: dict[str, Any], checks: CaseChecks) -> dict[str, Any]:
    del root
    devices = [fixture["devices"]["a"], fixture["devices"]["b"]]
    sample = int(fixture["identity"]["sample_per_device"])
    forward = {
        (device, sequence): stable_id("entity", device, sequence)
        for device in devices
        for sequence in range(1, sample + 1)
    }
    reverse = {
        (device, sequence): stable_id("entity", device, sequence)
        for device in reversed(devices)
        for sequence in range(sample, 0, -1)
    }
    values = list(forward.values())
    collisions = len(values) - len(set(values))
    forward_digest = sha256_json(sorted(values))
    reverse_digest = sha256_json(sorted(reverse.values()))
    inputs = list(inspect.signature(stable_id).parameters)

    checks.require("all bounded candidate IDs are unique", collisions == 0)
    checks.require("reordered generation preserves every fixture ID", forward == reverse)
    checks.require("reordered generation preserves the candidate-set digest", forward_digest == reverse_digest)
    checks.require("fixture ID function has no wall-clock input", inputs == ["kind", "origin_device", "local_sequence"])
    checks.require("same local sequence differs across devices", all(forward[(devices[0], n)] != forward[(devices[1], n)] for n in range(1, sample + 1)))

    return {
        "measurements": {
            "candidate_encoding": fixture["identity"]["candidate_encoding"],
            "collisions": collisions,
            "devices": len(devices),
            "generated": len(values),
            "per_device": sample,
            "reordered_set_digest": reverse_digest,
            "set_digest": forward_digest,
            "stable_id_inputs": inputs,
            "unique": len(set(values)),
        },
        "observations": [
            "The bounded fixture had no collision and was independent of generation interleaving.",
            "The deterministic fixture encoding measures device-plus-sequence mechanics; it is not a production ID selection or a proof of global collision freedom.",
        ],
    }


def case_revision_graph(root: Path, fixture: dict[str, Any], checks: CaseChecks) -> dict[str, Any]:
    graph = build_graph(root, fixture)
    events = graph["events"]
    entity_id = graph["entity_id"]
    root_revision = events["root"]["revision_id"]
    branch_a_revision = events["branch_a"]["revision_id"]
    branch_b_revision = events["branch_b"]["revision_id"]
    merge_revision = events["merge"]["revision_id"]
    tombstone_revision = events["tombstone"]["revision_id"]
    logical_sequences = {
        name: int(event["logical_sequence"]) for name, event in events.items()
    }
    device_sequences = {
        name: int(event["device_sequence"]) for name, event in events.items()
    }
    origin_devices = {
        name: str(event["origin_device"]) for name, event in events.items()
    }

    with ExperimentStore(graph["database_a"]) as store_a:
        before_digest = store_a.source_semantic_digest()
        before_counts = store_a.source_counts()
        stale_heads: list[str] = []
        try:
            commit(
                store_a,
                fixture,
                device=fixture["devices"]["a"],
                entity_id=entity_id,
                payload_name="branch_b",
                expected=[root_revision],
                key="stale-command",
                command_sequence=1010,
                request_id="request-stale-command",
            )
        except RevisionConflict as error:
            stale_heads = list(error.current_heads)
        after_digest = store_a.source_semantic_digest()
        after_counts = store_a.source_counts()
        immutable_error = store_a.attempt_revision_update(root_revision)
        root_payload_after = store_a.revision_payload(root_revision)
        before_parent_mutation_digest = store_a.source_semantic_digest()
        parent_immutable_error = store_a.attempt_parent_delete(branch_a_revision)
        after_parent_mutation_digest = store_a.source_semantic_digest()
        before_parent_insert_digest = store_a.source_semantic_digest()
        parent_insert_error = store_a.attempt_parent_insert(branch_a_revision)
        after_parent_insert_digest = store_a.source_semantic_digest()

    consumer_database = root / "revision-consumer.sqlite3"
    consumer_id = fixture["consumer_id"]
    with ExperimentStore(consumer_database) as consumer:
        for name in ("root", "branch_a", "branch_b"):
            result = consumer.apply_event(consumer_id, events[name])
            checks.require(f"{name} event applies", result.code == "APPLIED")
        concurrent_consumer_heads = consumer.consumer_heads(consumer_id, entity_id)
        history_at_conflict = consumer.consumer_counts(consumer_id)
        merge_result = consumer.apply_event(consumer_id, events["merge"])
        merged_consumer_heads = consumer.consumer_heads(consumer_id, entity_id)
        tombstone_result = consumer.apply_event(consumer_id, events["tombstone"])
        tombstone_consumer_heads = consumer.consumer_heads(consumer_id, entity_id)
        final_state = consumer.consumer_semantic_state(consumer_id)
        final_counts = consumer.consumer_counts(consumer_id)
        final_digest = consumer.consumer_semantic_digest(consumer_id)

    parent_pairs = {
        item["revision_id"]: item["parent_revision_id"]
        for item in final_state["parents"]
    }
    merge_parents = sorted(
        item["parent_revision_id"]
        for item in final_state["parents"]
        if item["revision_id"] == merge_revision
    )
    tombstone_rows = [
        row for row in final_state["revisions"] if row["revision_id"] == tombstone_revision
    ]

    checks.require("stale expected revision returns all current heads", stale_heads == [branch_a_revision])
    checks.require("stale conflict adds no source row or outbox effect", before_counts == after_counts)
    checks.require("stale conflict preserves the source semantic digest", before_digest == after_digest)
    checks.require("immutable revision trigger rejects update", "immutable revision" in immutable_error)
    checks.require("rejected update preserves ancestor payload", root_payload_after == fixture["payloads"]["root"])
    checks.require("immutable parentage trigger rejects delete", "immutable revision parentage" in parent_immutable_error)
    checks.require("rejected parentage delete preserves graph digest", before_parent_mutation_digest == after_parent_mutation_digest)
    checks.require("sealed parentage rejects post-commit insert", "immutable revision parentage" in parent_insert_error)
    checks.require("rejected parentage insert preserves graph digest", before_parent_insert_digest == after_parent_insert_digest)
    checks.require("independent offline descendants produce two heads", concurrent_consumer_heads == sorted([branch_a_revision, branch_b_revision]))
    checks.require("both concurrent branches remain in history", history_at_conflict["consumer_revisions"] == 3)
    checks.require("partial merge intent is rejected with the full frontier", graph["partial_merge_conflict"] == sorted([branch_a_revision, branch_b_revision]))
    checks.require("partial merge conflict adds no source row or outbox effect", all(value == 0 for value in graph["partial_merge_effect_delta"].values()))
    checks.require("partial merge conflict preserves the source semantic digest", graph["partial_merge_digest_unchanged"] is True)
    checks.require("explicit merge event applies", merge_result.code == "APPLIED")
    checks.require("explicit merge leaves one head", merged_consumer_heads == [merge_revision])
    checks.require("explicit merge records both branch parents", merge_parents == sorted([branch_a_revision, branch_b_revision]))
    checks.require("tombstone is applied as a revision", tombstone_result.code == "APPLIED")
    checks.require("tombstone becomes the head", tombstone_consumer_heads == [tombstone_revision])
    checks.require("tombstone retains all prior history", final_counts["consumer_revisions"] == 5)
    checks.require("tombstone flag is replayed", len(tombstone_rows) == 1 and tombstone_rows[0]["tombstone"] is True)
    checks.require("root remains an ancestor in the recorded graph", parent_pairs[branch_a_revision] == root_revision and parent_pairs[branch_b_revision] == root_revision)
    checks.require("logical sequence follows parent depth", logical_sequences == {"root": 1, "branch_a": 2, "branch_b": 2, "merge": 3, "tombstone": 4})
    checks.require("concurrent branches do not gain a sequence winner", logical_sequences["branch_a"] == logical_sequences["branch_b"])
    checks.require("device sequence is monotonic only inside each origin", device_sequences == {"root": 1, "branch_a": 2, "branch_b": 1, "merge": 1, "tombstone": 2})

    return {
        "measurements": {
            "concurrent_head_count": len(concurrent_consumer_heads),
            "concurrent_heads": concurrent_consumer_heads,
            "conflict_code": RevisionConflict.code,
            "final_effects": final_counts["consumer_effects"],
            "final_history_revisions": final_counts["consumer_revisions"],
            "final_semantic_digest": final_digest,
            "heads_after_merge": merged_consumer_heads,
            "heads_after_tombstone": tombstone_consumer_heads,
            "logical_sequences": logical_sequences,
            "merge_parent_count": len(merge_parents),
            "origin_devices": origin_devices,
            "partial_merge_conflict_heads": graph["partial_merge_conflict"],
            "partial_merge_effect_delta": graph["partial_merge_effect_delta"],
            "stale_conflict_heads": stale_heads,
            "device_sequences": device_sequences,
            "stale_effect_delta": {
                key: after_counts[key] - before_counts[key] for key in before_counts
            },
        },
        "observations": [
            "A stale ordinary command was rejected without overwrite or outbox append.",
            "Concurrent heads arose only from independently accepted offline descendants of one ancestor.",
            "The merge payload was an explicit fixture choice; no automatic conflict-resolution policy was measured.",
            "A tombstone remained an immutable revision; purge and retention were not exercised.",
        ],
    }


def case_idempotency(root: Path, fixture: dict[str, Any], checks: CaseChecks) -> dict[str, Any]:
    database = root / "idempotency.sqlite3"
    device_a = fixture["devices"]["a"]
    literal_key = "same-literal-key"
    entity_primary = stable_id("entity", device_a, 501)
    base_options = {"fixture_mode": "idempotency", "stable_flag": True}

    with ExperimentStore(database) as store:
        first = commit(
            store,
            fixture,
            device=device_a,
            entity_id=entity_primary,
            payload_name="root",
            expected=[],
            key=literal_key,
            command_sequence=5001,
            request_id="request-idempotency-first",
            stable_options=base_options,
        )
        counts_after_first = store.source_counts()
        retry = commit(
            store,
            fixture,
            device=device_a,
            entity_id=entity_primary,
            payload_name="root",
            expected=[],
            key=literal_key,
            command_sequence=5999,
            command_id=stable_id("command", device_a, 5999),
            request_id="request-idempotency-retry",
            stable_options=base_options,
        )
        counts_after_retry = store.source_counts()

        conflict_variants = [
            (
                "entity_id",
                {"entity_id": stable_id("entity", device_a, 502)},
            ),
            ("payload", {"payload_name": "branch_a"}),
            ("expected_revisions", {"expected": ["revision-not-current"]}),
            ("exact_version", {"exact_version": "1.0.1"}),
            ("contract_hash", {"contract_hash": "sha256:different-contract"}),
            (
                "stable_options",
                {
                    "stable_options": {
                        "fixture_mode": "idempotency",
                        "stable_flag": False,
                    }
                },
            ),
        ]
        conflicts: list[str] = []
        conflicting_variant_names: list[str] = []
        for offset, (variant_name, variant) in enumerate(conflict_variants, start=1):
            arguments = {
                "device": device_a,
                "entity_id": entity_primary,
                "payload_name": "root",
                "expected": [],
                "key": literal_key,
                "command_sequence": 5100 + offset,
                "request_id": f"request-idempotency-conflict-{offset}",
                "stable_options": base_options,
            }
            arguments.update(variant)
            try:
                commit(store, fixture, **arguments)
            except IdempotencyConflict as error:
                conflicts.append(error.code)
                conflicting_variant_names.append(variant_name)

        scoped_commands = [
            {
                "actor": "actor-secondary",
                "device": device_a,
                "capability_id": fixture["capability"]["id"],
                "major_version": 1,
                "exact_version": "1.0.0",
                "contract_hash": fixture["capability"]["contract_hash"],
            },
            {
                "actor": fixture["actor"],
                "device": fixture["devices"]["b"],
                "capability_id": fixture["capability"]["id"],
                "major_version": 1,
                "exact_version": "1.0.0",
                "contract_hash": fixture["capability"]["contract_hash"],
            },
            {
                "actor": fixture["actor"],
                "device": device_a,
                "capability_id": "nabla.entity.annotate",
                "major_version": 1,
                "exact_version": "1.0.0",
                "contract_hash": "sha256:annotate-contract-v1",
            },
            {
                "actor": fixture["actor"],
                "device": device_a,
                "capability_id": fixture["capability"]["id"],
                "major_version": 2,
                "exact_version": "2.0.0",
                "contract_hash": "sha256:update-contract-v2",
            },
        ]
        for offset, scope in enumerate(scoped_commands, start=1):
            commit(
                store,
                fixture,
                device=scope["device"],
                entity_id=stable_id("entity", scope["device"], 600 + offset),
                payload_name="root",
                expected=[],
                key=literal_key,
                command_sequence=6000 + offset,
                request_id=f"request-scope-{offset}",
                actor=scope["actor"],
                capability_id=scope["capability_id"],
                major_version=scope["major_version"],
                exact_version=scope["exact_version"],
                contract_hash=scope["contract_hash"],
                stable_options=base_options,
            )
        final_counts = store.source_counts()
        rows = store.command_rows()

    scopes = {
        (
            row["verified_actor"],
            row["origin_device"],
            row["capability_id"],
            int(row["major_version"]),
            row["idempotency_key"],
        )
        for row in rows
    }
    first_row = next(row for row in rows if row["command_id"] == first.receipt["command_id"])

    checks.require("same scope key and fingerprint returns a replay", retry.replayed is True)
    checks.require("retry returns the original committed receipt", retry.receipt == first.receipt)
    checks.require("retry with a new command ID returns original command ID", retry.receipt["command_id"] == first.receipt["command_id"])
    checks.require("retry adds no command revision or outbox row", counts_after_retry == counts_after_first)
    checks.require("all fingerprint mismatches are typed conflicts", conflicts == [IdempotencyConflict.code] * len(conflict_variants))
    checks.require("every named fingerprint variant was rejected", conflicting_variant_names == [name for name, _ in conflict_variants])
    checks.require("fingerprint conflicts add no effect", final_counts["revisions"] == 1 + len(scoped_commands))
    checks.require("same literal key is independent in every complete scope", len(scopes) == 1 + len(scoped_commands))
    checks.require("initial request ID is distinct and remains pinned", first_row["initial_request_id"] == "request-idempotency-first")
    checks.require("exact version and contract hash are stored with the committed intent", first_row["exact_version"] == fixture["capability"]["exact_version"] and first_row["contract_hash"] == fixture["capability"]["contract_hash"])
    checks.require("one semantic effect has one revision and outbox event", final_counts["revisions"] == final_counts["outbox"] == final_counts["command_receipts"])

    return {
        "measurements": {
            "conflicting_fingerprint_variants": len(conflict_variants),
            "conflicting_variants": conflicting_variant_names,
            "fingerprint_fields": [
                "entity_id",
                "exact_version",
                "contract_hash",
                "canonical_payload",
                "expected_revisions",
                "merge_intent",
                "tombstone_intent",
                "stable_options",
            ],
            "idempotency_conflict_code": IdempotencyConflict.code,
            "independent_scope_count": len(scopes),
            "literal_key": literal_key,
            "request_ids_exercised": 2,
            "retry_effect_delta": {
                key: counts_after_retry[key] - counts_after_first[key]
                for key in counts_after_first
            },
            "stored_command_count": final_counts["command_receipts"],
        },
        "observations": [
            "Command ID, scoped idempotency key, and per-attempt request ID remained distinct.",
            "The first committed exact version and contract hash remained attached to the stored receipt.",
            "Unknown external effects and retention of failed first intents were not exercised.",
        ],
    }


def worker_command_args(fixture: dict[str, Any]) -> dict[str, Any]:
    capability = fixture["capability"]
    device = fixture["devices"]["a"]
    return {
        "verified_actor": fixture["actor"],
        "origin_device": device,
        "capability_id": capability["id"],
        "major_version": capability["major_version"],
        "exact_version": capability["exact_version"],
        "contract_hash": capability["contract_hash"],
        "idempotency_key": "crash-producer-intent-v1",
        "command_id": stable_id("command", device, 9001),
        "request_id": "request-crash-worker-initial",
        "entity_id": stable_id("entity", device, 9001),
        "payload": fixture["payloads"]["root"],
        "expected_revisions": [],
        "stable_options": {"fixture_mode": "producer-crash"},
    }


def run_killed_worker(
    *,
    mode: str,
    phase: str,
    database: Path,
    checkpoint: Path,
) -> dict[str, Any]:
    command_line = [
        sys.executable,
        "-u",
        str(WORKER_PATH),
        mode,
        "--database",
        str(database),
        "--fixture",
        str(FIXTURE_PATH),
        "--checkpoint",
        str(checkpoint),
        "--phase",
        phase,
    ]
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        command_line,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
        creationflags=creation_flags,
    )
    deadline = time.monotonic() + CRASH_TIMEOUT_SECONDS
    try:
        while not checkpoint.exists():
            return_code = process.poll()
            if return_code is not None:
                stdout, stderr = process.communicate(timeout=1)
                raise RuntimeError(
                    f"worker exited before checkpoint ({return_code}): "
                    f"{stderr.strip() or stdout.strip()}"
                )
            if time.monotonic() >= deadline:
                raise TimeoutError(f"worker did not reach checkpoint {phase}")
            time.sleep(0.01)
        marker = json.loads(checkpoint.read_text(encoding="utf-8"))
        if marker != {"phase": phase}:
            raise AssertionError(f"unexpected checkpoint marker: {marker}")
        process.kill()
        stdout, stderr = process.communicate(timeout=5)
        return {
            "checkpoint": phase,
            "killed": process.returncode != 0,
            "stderr_empty": stderr == "",
            "stdout_empty": stdout == "",
        }
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)


def case_atomicity(root: Path, fixture: dict[str, Any], checks: CaseChecks) -> dict[str, Any]:
    before_database = root / "crash-before.sqlite3"
    after_database = root / "crash-after.sqlite3"
    with ExperimentStore(before_database):
        pass
    with ExperimentStore(after_database):
        pass

    before_process = run_killed_worker(
        mode="producer",
        phase="before_commit",
        database=before_database,
        checkpoint=root / "checkpoint-before.json",
    )
    with ExperimentStore(before_database) as store:
        before_counts = store.source_counts()
        before_counter = store.connection.execute(
            "SELECT COUNT(*) FROM device_counters"
        ).fetchone()[0]

    after_process = run_killed_worker(
        mode="producer",
        phase="after_commit",
        database=after_database,
        checkpoint=root / "checkpoint-after.json",
    )
    with ExperimentStore(after_database) as store:
        after_counts = store.source_counts()
        arguments = worker_command_args(fixture)
        arguments["request_id"] = "request-crash-worker-retry"
        arguments["command_id"] = stable_id("command", fixture["devices"]["a"], 9999)
        retry = store.commit_command(**arguments)
        counts_after_retry = store.source_counts()
        next_result = commit(
            store,
            fixture,
            device=fixture["devices"]["a"],
            entity_id=stable_id("entity", fixture["devices"]["a"], 9002),
            payload_name="root",
            expected=[],
            key="post-crash-next-intent",
            command_sequence=9002,
            request_id="request-post-crash-next",
            stable_options={"fixture_mode": "producer-crash"},
        )
        next_event = store.outbox_event(next_result.receipt["event_id"])

    zero_counts = {"command_receipts": 0, "heads": 0, "outbox": 0, "revisions": 0}
    one_counts = {"command_receipts": 1, "heads": 1, "outbox": 1, "revisions": 1}
    checks.require("worker reached before-commit checkpoint and was killed", before_process["checkpoint"] == "before_commit" and before_process["killed"])
    checks.require("kill before commit leaves no command revision head or outbox row", before_counts == zero_counts)
    checks.require("kill before commit leaves no committed device counter", int(before_counter) == 0)
    checks.require("worker reached after-commit checkpoint and was killed", after_process["checkpoint"] == "after_commit" and after_process["killed"])
    checks.require("kill after commit exposes command revision head and outbox atomically", after_counts == one_counts)
    checks.require("same-key retry after commit-before-response returns stored receipt", retry.replayed is True)
    checks.require("same-key retry after commit-before-response adds no effect", counts_after_retry == after_counts)
    checks.require("next committed device sequence is strictly greater", int(next_event["device_sequence"]) == 2)

    return {
        "measurements": {
            "after_commit_counts": after_counts,
            "before_commit_counts": before_counts,
            "before_commit_persisted_counter_rows": int(before_counter),
            "crash_checkpoints": ["before_commit", "after_commit"],
            "next_committed_device_sequence": int(next_event["device_sequence"]),
            "retry_effect_delta": {
                key: counts_after_retry[key] - after_counts[key] for key in after_counts
            },
        },
        "observations": [
            "At the selected process-kill checkpoints, command receipt, revision, head, counter, and outbox had one local transaction boundary.",
            "Commit-before-response was recoverable by retrying the same scoped idempotency key.",
        ],
        "diagnostics": {
            "after_commit_worker": after_process,
            "before_commit_worker": before_process,
        },
    }


def create_single_outbox_event(
    database: Path, fixture: dict[str, Any], sequence: int
) -> dict[str, Any]:
    device = fixture["devices"]["a"]
    with ExperimentStore(database) as store:
        result = commit(
            store,
            fixture,
            device=device,
            entity_id=stable_id("entity", device, sequence),
            payload_name="root",
            expected=[],
            key=f"delivery-intent-{sequence}",
            command_sequence=sequence,
            request_id=f"request-delivery-{sequence}",
            stable_options={"fixture_mode": "delivery"},
        )
        return store.outbox_event(result.receipt["event_id"])


def case_delivery_crash(root: Path, fixture: dict[str, Any], checks: CaseChecks) -> dict[str, Any]:
    consumer_id = fixture["consumer_id"]

    duplicate_database = root / "duplicate-delivery.sqlite3"
    duplicate_event = create_single_outbox_event(duplicate_database, fixture, 7001)
    with ExperimentStore(duplicate_database) as store:
        store.record_outbox_attempt(duplicate_event["event_id"])
        first = store.apply_event(consumer_id, duplicate_event)
        store.record_outbox_attempt(duplicate_event["event_id"])
        duplicate = store.apply_event(consumer_id, duplicate_event)
        store.acknowledge_outbox(duplicate_event["event_id"])
        duplicate_counts = store.consumer_counts(consumer_id)
        duplicate_outbox = store.outbox_row(duplicate_event["event_id"])
        delivery_count = int(
            store.connection.execute(
                """
                SELECT delivery_count
                FROM consumer_receipts
                WHERE consumer_id = ? AND event_id = ?
                """,
                (consumer_id, duplicate_event["event_id"]),
            ).fetchone()[0]
        )

    crash_database = root / "consumer-crash.sqlite3"
    crash_event = create_single_outbox_event(crash_database, fixture, 7101)
    process_result = run_killed_worker(
        mode="consumer",
        phase="after_effect_before_ack",
        database=crash_database,
        checkpoint=root / "checkpoint-consumer.json",
    )
    with ExperimentStore(crash_database) as store:
        state_after_kill = store.outbox_row(crash_event["event_id"])
        counts_after_kill = store.consumer_counts(consumer_id)
        store.record_outbox_attempt(crash_event["event_id"])
        retry = store.apply_event(consumer_id, crash_event)
        store.acknowledge_outbox(crash_event["event_id"])
        final_outbox = store.outbox_row(crash_event["event_id"])
        final_counts = store.consumer_counts(consumer_id)
        final_digest = store.consumer_semantic_digest(consumer_id)

    checks.require("first local consumer delivery applies", first.code == "APPLIED")
    checks.require("second delivery is typed duplicate suppression", duplicate.code == "DUPLICATE_SUPPRESSED")
    checks.require("duplicate deliveries create one consumer effect", duplicate_counts["consumer_effects"] == 1)
    checks.require("delivery receipt counts both transport attempts", delivery_count == 2 and duplicate_outbox["delivery_attempts"] == 2)
    checks.require("worker reached post-effect pre-ack checkpoint and was killed", process_result["checkpoint"] == "after_effect_before_ack" and process_result["killed"])
    checks.require("consumer effect and receipt are durable before producer ack", counts_after_kill["consumer_effects"] == 1 and counts_after_kill["consumer_receipts"] == 1 and state_after_kill["status"] == "pending")
    checks.require("redelivery after consumer crash is duplicate suppression", retry.code == "DUPLICATE_SUPPRESSED")
    checks.require("redelivery after consumer crash does not repeat effect", final_counts["consumer_effects"] == counts_after_kill["consumer_effects"] == 1)
    checks.require("producer outbox is acknowledged after safe retry", final_outbox["status"] == "acknowledged" and final_outbox["delivery_attempts"] == 2)

    return {
        "measurements": {
            "crash_checkpoint": "after_effect_before_ack",
            "delivery_code_first": first.code,
            "delivery_code_retry": retry.code,
            "duplicate_delivery_count": delivery_count,
            "duplicate_effect_count": duplicate_counts["consumer_effects"],
            "final_consumer_effect_count": final_counts["consumer_effects"],
            "final_consumer_semantic_digest": final_digest,
            "final_outbox_attempts": final_outbox["delivery_attempts"],
            "final_outbox_status": final_outbox["status"],
            "outbox_status_after_kill": state_after_kill["status"],
        },
        "observations": [
            "The measured handoff was at-least-once; a transactional local inbox/effect ledger produced one local effect for duplicate deliveries.",
            "The result does not claim exactly-once external effects or a distributed transaction.",
        ],
        "diagnostics": {"consumer_worker": process_result},
    }


def case_missing_parent(root: Path, fixture: dict[str, Any], checks: CaseChecks) -> dict[str, Any]:
    graph = build_graph(root / "graph", fixture)
    root_event = graph["events"]["root"]
    child_event = graph["events"]["branch_a"]
    consumer_id = fixture["consumer_id"]

    database = root / "missing-parent.sqlite3"
    with ExperimentStore(database) as store:
        child_first = store.apply_event(consumer_id, child_event)
        counts_while_blocked = store.consumer_counts(consumer_id)
        pending_while_blocked = store.pending_rows(consumer_id)
        root_result = store.apply_event(consumer_id, root_event)
        child_retry = store.apply_event(consumer_id, child_event)
        final_pending = store.pending_rows(consumer_id)
        final_heads = store.consumer_heads(consumer_id, graph["entity_id"])

    orphan = copy.deepcopy(child_event)
    orphan_device = fixture["devices"]["b"]
    orphan["entity_id"] = stable_id("entity", orphan_device, 8800)
    orphan["revision_id"] = stable_id("revision", orphan_device, 8800)
    orphan["event_id"] = stable_id("event", orphan_device, 8800)
    orphan["device_sequence"] = 8800
    orphan["parents"] = [stable_id("revision", orphan_device, 8799)]
    fixed_database = root / "bounded-fixed-point.sqlite3"
    with ExperimentStore(fixed_database) as store:
        fixed_point = replay_until_fixed_point(
            store,
            consumer_id,
            [orphan, root_event],
            max_passes=4,
        )
        fixed_counts = store.consumer_counts(consumer_id)
        fixed_pending = store.pending_rows(consumer_id)

    checks.require("child before parent returns typed missing-parent result", child_first.code == "MISSING_PARENT" and list(child_first.missing_parents) == [root_event["revision_id"]])
    checks.require("blocked child creates no partial consumer effect", counts_while_blocked["consumer_effects"] == 0 and counts_while_blocked["consumer_revisions"] == 0)
    checks.require("blocked child is durably typed pending", len(pending_while_blocked) == 1 and pending_while_blocked[0]["reason"] == "MISSING_PARENT")
    checks.require("parent then child apply causally", root_result.code == child_retry.code == "APPLIED")
    checks.require("resolved dependency clears pending row", final_pending == [])
    checks.require("resolved child becomes the head", final_heads == [child_event["revision_id"]])
    checks.require("unresolvable dependency reaches a bounded fixed point", fixed_point["passes"] <= 4 and len(fixed_pending) == 1)
    checks.require("unresolvable event remains typed pending", fixed_pending[0]["reason"] == "MISSING_PARENT")
    checks.require("unresolvable event does not block independent root", fixed_counts["consumer_effects"] == 1 and fixed_counts["consumer_pending"] == 1)

    return {
        "measurements": {
            "blocked_effect_count": counts_while_blocked["consumer_effects"],
            "child_first_code": child_first.code,
            "fixed_point_passes": fixed_point["passes"],
            "independent_effect_count": fixed_counts["consumer_effects"],
            "pending_after_parent": len(final_pending),
            "unresolved_code": fixed_pending[0]["reason"],
            "unresolved_count": len(fixed_pending),
            "unresolved_missing_parents": fixed_pending[0]["missing_parents"],
        },
        "observations": [
            "Parent availability, not arrival time, gated revision application.",
            "A bounded fixed point retained an unresolved dependency without blocking an independent event.",
        ],
    }


def case_replay_determinism(root: Path, fixture: dict[str, Any], checks: CaseChecks) -> dict[str, Any]:
    graph = build_graph(root / "graph-primary", fixture)
    repeat_graph = build_graph(root / "graph-repeat", fixture)
    labels = ("root", "branch_a", "branch_b", "merge")
    events = graph["events"]
    event_digest = sha256_json([events[label] for label in labels])
    repeat_event_digest = sha256_json(
        [repeat_graph["events"][label] for label in labels]
    )
    consumer_id = fixture["consumer_id"]
    schedules: list[dict[str, Any]] = []
    final_digests: set[str] = set()
    total_missing = 0
    total_duplicates = 0
    max_passes_observed = 0

    for index, order in enumerate(itertools.permutations(labels), start=1):
        ordered = [events[label] for label in order]
        injected = [ordered[0], *ordered, ordered[-1]]
        database = root / f"schedule-{index:02d}.sqlite3"
        with ExperimentStore(database) as store:
            replay = replay_until_fixed_point(
                store,
                consumer_id,
                injected,
                max_passes=MAX_REPLAY_PASSES,
            )
            digest = store.consumer_semantic_digest(consumer_id)
            heads = store.consumer_heads(consumer_id, graph["entity_id"])
        checks.require(f"schedule {index:02d} drains all causal dependencies", replay["pending"] == [])
        checks.require(f"schedule {index:02d} preserves merge as sole head", heads == [events["merge"]["revision_id"]])
        final_digests.add(digest)
        total_missing += int(replay["codes"]["MISSING_PARENT"])
        total_duplicates += int(replay["codes"]["DUPLICATE_SUPPRESSED"])
        max_passes_observed = max(max_passes_observed, int(replay["passes"]))
        schedules.append(
            {
                "digest": digest,
                "duplicate_suppressions": int(
                    replay["codes"]["DUPLICATE_SUPPRESSED"]
                ),
                "missing_parent_observations": int(
                    replay["codes"]["MISSING_PARENT"]
                ),
                "order": list(order),
                "passes": int(replay["passes"]),
            }
        )

    forbidden_time_fields = {"timestamp", "created_at", "updated_at", "wall_clock"}
    envelope_fields = set().union(*(event.keys() for event in events.values()))
    event_types = sorted({str(event["event_type"]) for event in events.values()})
    event_versions = sorted({int(event["event_version"]) for event in events.values()})
    checks.require("all 24 arrival permutations were exercised", len(schedules) == 24)
    checks.require("all complete schedules converge to one semantic digest", len(final_digests) == 1)
    checks.require("replay terminates inside the explicit pass bound", max_passes_observed <= MAX_REPLAY_PASSES)
    checks.require("repeat graph construction yields the same event digest", event_digest == repeat_event_digest)
    checks.require("event envelopes contain no wall-clock causal field", forbidden_time_fields.isdisjoint(envelope_fields))
    checks.require("fixture events carry one explicit type and version", event_types == ["nabla.entity.revision-committed"] and event_versions == [1])

    return {
        "measurements": {
            "distinct_final_digests": len(final_digests),
            "event_set_digest": event_digest,
            "event_types": event_types,
            "event_versions": event_versions,
            "final_semantic_digest": sorted(final_digests)[0],
            "max_passes_bound": MAX_REPLAY_PASSES,
            "max_passes_observed": max_passes_observed,
            "injected_duplicates_per_schedule": 2,
            "repeat_event_set_digest": repeat_event_digest,
            "schedule_count": len(schedules),
            "schedules": schedules,
            "total_duplicate_suppressions": total_duplicates,
            "total_missing_parent_observations": total_missing,
        },
        "observations": [
            "Causal parent gating plus set-valued heads converged for every measured order and duplicate schedule.",
            "Canonical sorting was used only for comparison and serialization, never to choose a winning concurrent head.",
            "Per-device sequence was not treated as a global order and wall clock was absent from correctness logic.",
        ],
    }


CASE_DEFINITIONS: list[
    tuple[str, str, Callable[[Path, dict[str, Any], CaseChecks], dict[str, Any]]]
] = [
    ("IDENTITY-01", "bounded offline identity generation", case_identity),
    ("REVISION-01", "immutable graph conflict merge and tombstone", case_revision_graph),
    ("IDEMPOTENCY-01", "scoped committed-result replay", case_idempotency),
    ("ATOMICITY-01", "producer crash before and after commit", case_atomicity),
    ("DELIVERY-01", "duplicate delivery and consumer crash gap", case_delivery_crash),
    ("DEPENDENCY-01", "missing-parent causal buffering", case_missing_parent),
    ("REPLAY-01", "permutation and duplicate convergence", case_replay_determinism),
]


def run_case(
    root: Path,
    fixture: dict[str, Any],
    case_id: str,
    title: str,
    function: Callable[[Path, dict[str, Any], CaseChecks], dict[str, Any]],
) -> dict[str, Any]:
    checks = CaseChecks()
    case_root = root / case_id.lower()
    case_root.mkdir(parents=True, exist_ok=True)
    try:
        body = function(case_root, fixture, checks)
        return {
            "checks": checks.names,
            "id": case_id,
            "status": "pass",
            "title": title,
            **body,
        }
    except Exception as error:
        return {
            "checks": checks.names,
            "failure": {"message": str(error), "type": type(error).__name__},
            "id": case_id,
            "measurements": {},
            "observations": [],
            "status": "fail",
            "title": title,
        }


def normalized_machine() -> str:
    machine = platform.machine().lower()
    if machine in {"amd64", "x86_64"}:
        return "x86_64"
    if machine in {"arm64", "aarch64"}:
        return "aarch64"
    return machine or "unknown"


def semantic_projection(result: dict[str, Any]) -> dict[str, Any]:
    projected_cases = []
    for case in result["cases"]:
        projected = {
            key: value
            for key, value in case.items()
            if key not in {"diagnostics", "failure"}
        }
        if "failure" in case:
            projected["failure_type"] = case["failure"]["type"]
        projected_cases.append(projected)
    return {
        "artifact_id": result["artifact_id"],
        "artifact_version": result["artifact_version"],
        "bounds": result["bounds"],
        "cases": projected_cases,
        "fixture": result["fixture"],
        "task_id": result["task_id"],
    }


def run_experiment() -> dict[str, Any]:
    fixture = load_fixture()
    with tempfile.TemporaryDirectory(prefix="nabla-revision-replay-") as temporary:
        temporary_root = Path(temporary)
        cases = [
            run_case(temporary_root, fixture, case_id, title, function)
            for case_id, title, function in CASE_DEFINITIONS
        ]
    result: dict[str, Any] = {
        "artifact_id": ARTIFACT_ID,
        "artifact_version": 1,
        "bounds": {
            "crash_checkpoint_timeout_seconds": int(CRASH_TIMEOUT_SECONDS),
            "identity_candidates_per_device": int(
                fixture["identity"]["sample_per_device"]
            ),
            "replay_max_passes": MAX_REPLAY_PASSES,
            "replay_permutation_schedules": 24,
        },
        "cases": cases,
        "conclusions": {
            "adr_runtime_boundary_inputs": [
                "one local transaction for command acceptance, scoped idempotency receipt, revision, head update, device sequence, and outbox append",
                "atomic monotonic local sequence allocation for an already supplied normative device identity",
                "replay-worker boundary separating outbox attempt, transactional local inbox and effect receipt, and producer acknowledgement",
                "at-least-once outbox handoff with transactional local inbox and effect receipt before producer acknowledgement",
                "causal dependency buffering with finite replay bounds and isolated unresolved events",
                "persistence port requirements for atomicity, uniqueness, durable restart recovery, and deterministic canonicalization",
                "versioned event envelope separated from revision graph and delivery order",
            ],
            "already_normative_not_reopened": [
                "immutable parented revisions and set-valued heads",
                "no silent overwrite or wall-clock last-write-wins",
                "offline baseline and optimistic revision conflict",
                "specified idempotency scope and transactional outbox",
                "device identity and versioned event requirements; their production lifecycle and envelope remain unselected",
            ],
            "deferred": [
                "production entity revision and event ID encoding plus device provisioning",
                "production logical-sequence computation and event-envelope shape and version lifecycle",
                "revision DDL indexes backend and snapshot-patch-hybrid representation",
                "runtime portability and extension decision owned by ADR-RUNTIME-BOUNDARY-001",
                "network transport authentication reconciliation cursors and synchronization",
                "automatic conflict resolution and merge user experience",
                "external-effect exactly-once semantics and distributed transactions",
                "retention compaction tombstone garbage collection and purge",
                "production performance durability capacity and retry thresholds",
                "multi-head command API shape and failed-intent retention lifecycle",
            ],
        },
        "environment": {
            "architecture": normalized_machine(),
            "os": platform.system(),
            "os_release": platform.release(),
            "python": platform.python_version(),
            "sqlite": sqlite3.sqlite_version,
            "sqlite_durability_settings": {
                "journal_mode": "WAL",
                "synchronous": "FULL",
            },
        },
        "fixture": {
            "path": "tests/spikes/revision-replay/fixtures/scenario-v1.json",
            "sha256": fixture_sha256(),
            "version": fixture["fixture_version"],
        },
        "limitations": [
            "The finite identity sample is not a global collision proof and the deterministic hash prefix is only a fixture encoding.",
            "SQLite tables full-snapshot payloads event envelope and retry bounds are experimental mechanics rather than selected production contracts.",
            "Process termination at explicit checkpoints does not cover power loss torn storage corruption or arbitrary instruction boundaries.",
            "Consumer effect-once was measured only when the local effect and inbox receipt shared one transaction; external effects remain unproven.",
            "Permutation convergence proves graph and frontier convergence for one complete fixed event set, not semantic auto-merge of conflicting payloads.",
            "No network synchronization production persistence throughput scale or cross-platform durability claim was exercised.",
        ],
        "task_id": TASK_ID,
    }
    projection = semantic_projection(result)
    passed = all(case["status"] == "pass" for case in cases)
    result["summary"] = {
        "assertion_count": sum(len(case["checks"]) for case in cases),
        "case_count": len(cases),
        "passed_case_count": sum(case["status"] == "pass" for case in cases),
        "semantic_digest": sha256_json(projection),
        "status": "pass" if passed else "fail",
    }
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify", type=Path)
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    result = run_experiment()
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(rendered, encoding="utf-8", newline="\n")

    verification = "not-requested"
    if arguments.verify is not None:
        expected = json.loads(arguments.verify.read_text(encoding="utf-8"))
        if semantic_projection(expected) != semantic_projection(result):
            print("semantic verification: mismatch", file=sys.stderr)
            return 1
        if expected["summary"]["semantic_digest"] != result["summary"]["semantic_digest"]:
            print("semantic verification: digest mismatch", file=sys.stderr)
            return 1
        verification = "match"

    if arguments.output is None and arguments.verify is None:
        print(rendered, end="")
    else:
        print(
            canonical_json(
                {
                    "assertions": result["summary"]["assertion_count"],
                    "cases": result["summary"]["case_count"],
                    "semantic_digest": result["summary"]["semantic_digest"],
                    "status": result["summary"]["status"],
                    "verification": verification,
                }
            )
        )
    return 0 if result["summary"]["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
