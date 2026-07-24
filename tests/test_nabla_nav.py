from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import nabla_nav  # noqa: E402
import spec_slice  # noqa: E402


def repository_state():
    index = spec_slice.load_index(ROOT / "spec-index.json")
    errors, warnings, docs = spec_slice.validate_index(ROOT, index)
    assert errors == []
    assert warnings == []
    tasks, paths = nabla_nav.load_tasks(ROOT)
    return index, docs, tasks, paths


def test_repository_task_cards_validate() -> None:
    errors, warnings, tasks, _ = nabla_nav.validate_repository(ROOT)

    assert errors == []
    assert warnings == []
    assert len(tasks) == 7


def test_ready_tasks_have_completed_dependencies() -> None:
    _, _, tasks, _ = repository_state()

    ready = [task for task in tasks.values() if task["state"] == "ready"]

    assert len(ready) <= 1
    for task in ready:
        assert all(
            tasks[dependency]["state"] == "completed"
            for dependency in task["dependencies"]["tasks"]
        )


def test_context_manifest_is_deterministic() -> None:
    index, docs, tasks, paths = repository_state()
    task = tasks["BOOT-NAV-001"]

    first_context, first_manifest = nabla_nav.build_context_bundle(
        ROOT, task, paths[task["task_id"]], index, docs
    )
    second_context, second_manifest = nabla_nav.build_context_bundle(
        ROOT, task, paths[task["task_id"]], index, docs
    )

    assert first_context.encode("utf-8") == second_context.encode("utf-8")
    assert nabla_nav.canonical_json(first_manifest) == nabla_nav.canonical_json(second_manifest)
    assert first_manifest["context_words"] < 12000


def test_stale_selector_is_rejected() -> None:
    index, docs, tasks, _ = repository_state()
    task = copy.deepcopy(tasks["BOOT-NAV-001"])
    task["context"]["required"] = ["NAV:does-not-exist"]

    errors, _ = nabla_nav.validate_task_semantics(task, tasks, index, docs, {}, {})

    assert any("selector does not resolve" in error for error in errors)


def test_wrong_pack_version_is_rejected() -> None:
    index, _, tasks, _ = repository_state()
    task = copy.deepcopy(tasks["BOOT-NAV-001"])
    task["context"]["packs"][0]["version"] = 999

    errors = nabla_nav.validate_pack_pins(task, index)

    assert errors == [
        "BOOT-NAV-001: context pack spec-authoring is pinned to 999, repository has 1"
    ]


def test_ready_task_cannot_depend_on_incomplete_task() -> None:
    index, docs, tasks, _ = repository_state()
    scenario = copy.deepcopy(tasks)
    scenario["BOOT-NAV-001"]["state"] = "blocked"
    task = copy.deepcopy(scenario["BOOT-SLICE-001"])
    task["state"] = "ready"

    errors, _ = nabla_nav.validate_task_semantics(task, scenario, index, docs, {}, {})

    assert any("depends on non-completed task BOOT-NAV-001" in error for error in errors)


def test_ready_task_cannot_use_missing_artifact() -> None:
    index, docs, tasks, _ = repository_state()
    task = copy.deepcopy(tasks["BOOT-NAV-001"])
    task["state"] = "ready"
    task["dependencies"]["artifacts"] = ["MISSING"]

    errors, _ = nabla_nav.validate_task_semantics(task, tasks, index, docs, {}, {})

    assert any("blocking artifact is not available: MISSING" in error for error in errors)


def test_task_dependency_cycle_is_rejected() -> None:
    _, _, tasks, _ = repository_state()
    cyclic = copy.deepcopy(tasks)
    cyclic["BOOT-NAV-001"]["dependencies"]["tasks"] = ["BOOT-SLICE-001"]

    errors = nabla_nav.task_dependency_cycles(cyclic)

    assert any(
        "BOOT-SLICE-001 -> BOOT-NAV-001 -> BOOT-SLICE-001" in error for error in errors
    )


def test_full_document_read_requires_reason() -> None:
    _, _, tasks, paths = repository_state()
    task = copy.deepcopy(tasks["BOOT-NAV-001"])
    task["context"]["full_document_reads"] = [
        {"selector": "NAV:full", "reason": ""}
    ]

    errors = nabla_nav.validate_task_shape(task, paths["BOOT-NAV-001"])

    assert any("DOC:full selector and reason required" in error for error in errors)


def test_context_over_hard_budget_is_rejected() -> None:
    index, docs, tasks, paths = repository_state()
    task = copy.deepcopy(tasks["BOOT-NAV-001"])
    task["context"]["packs"] = []
    task["context"]["required"] = [
        "CON:full",
        "ARCH:full",
        "DATA:full",
        "CAP:full",
        "MOD:full",
        "LOOP:full",
        "KNOW:full",
        "DOC:full",
    ]
    task["context"]["context_budget_justification"] = "Architecture conformance audit."

    with pytest.raises(nabla_nav.NavError, match="hard limit is 16000"):
        nabla_nav.build_context_bundle(
            ROOT, task, paths["BOOT-NAV-001"], index, docs
        )


def test_ready_implementation_task_rejects_draft_spec_and_missing_roadmap() -> None:
    index, docs, tasks, _ = repository_state()
    task = copy.deepcopy(tasks["BOOT-NAV-001"])
    task["state"] = "ready"
    task["type"] = "implementation"
    task["context"]["packs"] = []
    task["context"]["required"] = ["ARCH:25"]

    errors, _ = nabla_nav.validate_task_semantics(task, tasks, index, docs, {}, {})

    assert any("uses draft document ARCH" in error for error in errors)
    assert any("production ROADMAP.md is required" in error for error in errors)


def test_scope_rejects_outside_and_normative_changes() -> None:
    _, _, tasks, _ = repository_state()
    task = tasks["BOOT-SLICE-001"]

    errors = nabla_nav.validate_changed_paths(
        task, ["tools/spec_slice.py", "ARCHITECTURE.md"]
    )

    assert any("outside scope: ARCHITECTURE.md" in error for error in errors)
    assert any("normative files require spec/adr task" in error for error in errors)


def test_completed_task_requires_evidence() -> None:
    _, _, tasks, _ = repository_state()
    task = copy.deepcopy(tasks["BOOT-NAV-001"])
    task["task_id"] = "NO-SUCH-EVIDENCE"
    task["state"] = "completed"

    errors = nabla_nav.validate_evidence(ROOT, task)

    assert len(errors) == 1
    assert "completed task requires evidence file" in errors[0]


def test_unknown_conditional_trigger_is_rejected() -> None:
    index, _, tasks, _ = repository_state()

    with pytest.raises(nabla_nav.NavError, match="unknown conditional trigger"):
        nabla_nav.expanded_task_context(tasks["BOOT-PILOT-001"], index, ["unknown"])


def test_prepared_manifest_round_trips_as_utf8_json() -> None:
    _, _, tasks, paths = repository_state()
    _, manifest_path, manifest = nabla_nav.write_context_bundle(
        ROOT, tasks["BOOT-NAV-001"], paths["BOOT-NAV-001"], []
    )

    loaded = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert loaded == manifest
