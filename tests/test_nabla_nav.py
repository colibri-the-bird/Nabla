from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest
import yaml


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
    assert (
        first_manifest["manifest_sha256"]
        == "eef4a279f45a7fea6b7b5787ab2dbd83ba8b2f4457260a5e942db88922c6fc6e"
    )


def test_task_card_hash_normalizes_line_endings(tmp_path: Path) -> None:
    windows = tmp_path / "windows.yaml"
    unix = tmp_path / "unix.yaml"
    windows.write_bytes(b"task_id: TEST\r\nstate: ready\r\n")
    unix.write_bytes(b"task_id: TEST\nstate: ready\n")

    assert nabla_nav.normalized_text_sha256(windows) == nabla_nav.normalized_text_sha256(
        unix
    )


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


def test_completed_task_cannot_skip_dependency_chain() -> None:
    index, docs, tasks, _ = repository_state()
    scenario = copy.deepcopy(tasks)
    scenario["BOOT-NAV-001"]["state"] = "blocked"
    task = copy.deepcopy(scenario["BOOT-SLICE-001"])
    task["state"] = "completed"

    errors, _ = nabla_nav.validate_task_semantics(task, scenario, index, docs, {}, {})

    assert any(
        "active task depends on non-completed task BOOT-NAV-001" in error
        for error in errors
    )


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


def test_living_spec_lock_is_current_and_deterministic() -> None:
    index, docs, _, _ = repository_state()
    expected = nabla_nav.canonical_json(nabla_nav.build_spec_lock(ROOT, index, docs))
    actual = (ROOT / "governance" / "spec-lock.json").read_text(encoding="utf-8")

    assert actual == expected
    assert nabla_nav.check_spec_lock(ROOT, index, docs) == []


def test_decision_registry_contains_all_required_adrs() -> None:
    decisions = nabla_nav.load_registry(
        ROOT / "governance" / "decisions.yaml", "decisions"
    )

    assert set(decisions) == {f"ADR-{number:03d}" for number in range(1, 13)}
    assert all(entry["status"] == "required" for entry in decisions.values())


def test_missing_external_artifacts_remain_blockers() -> None:
    artifacts = nabla_nav.load_registry(
        ROOT / "governance" / "artifacts.yaml", "artifacts"
    )

    assert artifacts["BACKUP-RECOVERY-SPEC"]["status"] == "missing"
    assert artifacts["CORE-PORTABILITY-SPIKE"]["status"] == "missing"
    assert artifacts["GITHUB-BRANCH-PROTECTION"]["status"] == "missing"


def test_traceability_covers_exactly_i1_through_i16() -> None:
    index, docs, _, _ = repository_state()
    errors, _, _ = nabla_nav.validate_governance(ROOT, index, docs)
    trace = nabla_nav.read_yaml(ROOT / "governance" / "traceability.yaml")

    assert errors == []
    assert {entry["id"] for entry in trace["invariants"]} == {
        f"I{number}" for number in range(1, 17)
    }


@pytest.mark.parametrize(
    ("title", "task_id"),
    [
        ("[BOOT-CI-001] Add GitHub gates", "BOOT-CI-001"),
        ("  [BOOT-NAV-001] Define navigation  ", "BOOT-NAV-001"),
    ],
)
def test_pr_title_yields_exact_task_id(title: str, task_id: str) -> None:
    assert nabla_nav.task_id_from_pr_title(title) == task_id


@pytest.mark.parametrize(
    "title",
    [
        "BOOT-CI-001 Add GitHub gates",
        "[BOOT-CI-001]",
        "[boot-ci-001] Add GitHub gates",
        "[BOOT_CI_001] Add GitHub gates",
    ],
)
def test_pr_title_rejects_missing_or_malformed_task_id(title: str) -> None:
    with pytest.raises(nabla_nav.NavError, match="PR title must start"):
        nabla_nav.task_id_from_pr_title(title)


def test_pr_evidence_must_match_manifest_diff_and_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = copy.deepcopy(repository_state()[2]["BOOT-CI-001"])
    task["state"] = "completed"
    evidence_path = tmp_path / "roadmap" / "evidence" / "BOOT-CI-001.yaml"
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "task_id": "BOOT-CI-001",
                "context_manifest_sha256": "stale",
                "selectors": [],
                "document_hashes": {},
                "impact_tags": [],
                "changed_paths": ["wrong.txt"],
                "changed_contracts": [],
                "tests": [{"command": "pytest", "exit_code": 1}],
                "unresolved_decisions": [],
                "pr_url": "https://github.com/colibri-the-bird/Nabla/pull/1",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(nabla_nav, "validate_evidence", lambda *_: [])
    monkeypatch.setattr(spec_slice, "load_index", lambda *_: {})
    monkeypatch.setattr(spec_slice, "validate_index", lambda *_: ([], [], {}))
    monkeypatch.setattr(
        nabla_nav,
        "build_context_bundle",
        lambda *_: ("context", {"manifest_sha256": "current"}),
    )

    errors = nabla_nav.validate_pr_evidence(
        tmp_path,
        task,
        tmp_path / "roadmap" / "tasks" / "BOOT-CI-001.yaml",
        [".github/workflows/bootstrap-gates.yml"],
        "https://github.com/colibri-the-bird/Nabla/pull/2",
    )

    assert any("context manifest is stale" in error for error in errors)
    assert any("changed_paths does not match" in error for error in errors)
    assert any("pr_url does not match" in error for error in errors)
    assert any("did not exit with 0" in error for error in errors)


def test_workflow_has_exact_required_checks_and_no_path_filters() -> None:
    workflow_path = ROOT / ".github" / "workflows" / "bootstrap-gates.yml"
    workflow = yaml.load(workflow_path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    assert set(workflow["jobs"]) == {
        "navigation-linux",
        "navigation-windows",
        "task-card-gate",
        "scope-and-evidence-gate",
        "spec-lock-and-traceability-gate",
    }
    assert workflow["on"]["pull_request"] == ""
    assert workflow["on"]["push"]["branches"] == ["main"]
    assert "paths" not in workflow["on"]["push"]
