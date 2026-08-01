"""Checkpointed subprocess used by the revision/replay spike.

The parent process kills this worker only after a durable marker appears. That
makes the selected crash boundary explicit instead of timing-dependent.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
from pathlib import Path
from typing import Any

from _spike_harness import ExperimentStore, canonical_json, stable_id


def load_fixture(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_checkpoint(path: Path, phase: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(canonical_json({"phase": phase}), encoding="utf-8")
    os.replace(temporary, path)


def wait_for_kill() -> None:
    threading.Event().wait()


def producer_command(
    store: ExperimentStore,
    fixture: dict[str, Any],
    checkpoint: Path,
    phase: str,
) -> None:
    capability = fixture["capability"]
    device = fixture["devices"]["a"]
    entity_id = stable_id("entity", device, 9001)
    arguments = {
        "verified_actor": fixture["actor"],
        "origin_device": device,
        "capability_id": capability["id"],
        "major_version": capability["major_version"],
        "exact_version": capability["exact_version"],
        "contract_hash": capability["contract_hash"],
        "idempotency_key": "crash-producer-intent-v1",
        "command_id": stable_id("command", device, 9001),
        "request_id": "request-crash-worker-initial",
        "entity_id": entity_id,
        "payload": fixture["payloads"]["root"],
        "expected_revisions": [],
        "stable_options": {"fixture_mode": "producer-crash"},
    }
    if phase == "before_commit":
        arguments["before_commit"] = lambda: (
            write_checkpoint(checkpoint, phase),
            wait_for_kill(),
        )
        store.commit_command(**arguments)
        raise AssertionError("before_commit worker was not killed")
    if phase == "after_commit":
        store.commit_command(**arguments)
        write_checkpoint(checkpoint, phase)
        wait_for_kill()
        raise AssertionError("after_commit worker was not killed")
    raise ValueError(phase)


def consumer_delivery(
    store: ExperimentStore,
    fixture: dict[str, Any],
    checkpoint: Path,
) -> None:
    event = store.first_pending_outbox_event()
    store.record_outbox_attempt(event["event_id"])
    result = store.apply_event(fixture["consumer_id"], event)
    if result.code != "APPLIED":
        raise AssertionError(f"unexpected first delivery result: {result.code}")
    write_checkpoint(checkpoint, "after_effect_before_ack")
    wait_for_kill()
    raise AssertionError("consumer worker was not killed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("producer", "consumer"))
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument(
        "--phase",
        choices=("before_commit", "after_commit", "after_effect_before_ack"),
        required=True,
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    fixture = load_fixture(arguments.fixture)
    with ExperimentStore(arguments.database) as store:
        if arguments.mode == "producer":
            producer_command(store, fixture, arguments.checkpoint, arguments.phase)
        elif arguments.phase == "after_effect_before_ack":
            consumer_delivery(store, fixture, arguments.checkpoint)
        else:
            raise ValueError("consumer mode requires after_effect_before_ack")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
