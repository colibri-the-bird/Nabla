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
    assert {
        "BOOT-NAV-001",
        "BOOT-SLICE-001",
        "BOOT-CARDS-001",
        "BOOT-TRACE-001",
        "BOOT-AGENTS-001",
        "BOOT-CI-001",
        "BOOT-PILOT-001",
        "BOOT-REPAIR-001",
    } <= set(tasks)


def test_ready_tasks_have_completed_dependencies() -> None:
    _, _, tasks, _ = repository_state()

    ready = [task for task in tasks.values() if task["state"] == "ready"]

    assert len(ready) <= 1
    for task in ready:
        assert all(
            tasks[dependency]["state"] == "completed"
            for dependency in task["dependencies"]["tasks"]
        )


def test_validator_rejects_more_than_one_ready_task() -> None:
    _, _, tasks, _ = repository_state()
    scenario = copy.deepcopy(tasks)
    ready_id = next(
        task_id for task_id, task in scenario.items() if task["state"] == "ready"
    )
    blocked_id = next(
        task_id for task_id, task in scenario.items() if task["state"] == "blocked"
    )
    scenario[blocked_id]["state"] = "ready"
    active = ", ".join(sorted((ready_id, blocked_id)))

    assert nabla_nav.ready_cardinality_errors(scenario) == [
        f"more than one task is ready: {active}"
    ]


def test_predevelopment_dag_is_one_mutable_successor_chain() -> None:
    _, _, tasks, _ = repository_state()

    assert nabla_nav.bootstrap_chain_errors(tasks) == []


def test_predevelopment_dag_rejects_branching() -> None:
    _, _, tasks, _ = repository_state()
    scenario = copy.deepcopy(tasks)
    scenario["BOOT-PROTECT-001"]["dependencies"]["tasks"] = [
        "BOOT-REPAIR-001"
    ]

    errors = nabla_nav.bootstrap_chain_errors(scenario)

    assert any("BOOT-REPAIR-001: bootstrap chain branches to" in error for error in errors)


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
    payload = {
        key: value
        for key, value in first_manifest.items()
        if key != "manifest_sha256"
    }
    assert first_manifest["manifest_sha256"] == nabla_nav.sha256_bytes(
        nabla_nav.canonical_json(payload).encode("utf-8")
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

    errors, _ = nabla_nav.validate_task_semantics(
        task,
        tasks,
        index,
        docs,
        {},
        {"MISSING": {"status": "missing"}},
    )

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

    errors, _ = nabla_nav.validate_task_semantics(
        task,
        tasks,
        index,
        docs,
        {},
        {"MISSING": {"status": "missing"}},
    )

    assert any("blocking artifact is not available: MISSING" in error for error in errors)


def test_task_dependency_cycle_is_rejected() -> None:
    _, _, tasks, _ = repository_state()
    cyclic = copy.deepcopy(tasks)
    cyclic["BOOT-NAV-001"]["dependencies"]["tasks"] = ["BOOT-SLICE-001"]

    errors = nabla_nav.task_dependency_cycles(cyclic)

    assert any(
        "BOOT-SLICE-001 -> BOOT-NAV-001 -> BOOT-SLICE-001" in error for error in errors
    )


def test_artifact_provider_dependency_cycle_is_rejected() -> None:
    _, _, tasks, _ = repository_state()
    cyclic = copy.deepcopy(tasks)
    cyclic["BOOT-NAV-001"]["dependencies"]["artifacts"] = ["TEST-ARTIFACT"]

    errors = nabla_nav.task_dependency_cycles(
        cyclic,
        {"TEST-ARTIFACT": {"provided_by": "BOOT-SLICE-001"}},
    )

    assert any(
        "BOOT-SLICE-001 -> BOOT-NAV-001 -> BOOT-SLICE-001" in error
        for error in errors
    )


def test_artifact_provider_must_reference_known_task() -> None:
    _, _, tasks, _ = repository_state()
    scenario = copy.deepcopy(tasks)
    scenario["BOOT-NAV-001"]["dependencies"]["artifacts"] = ["TEST-ARTIFACT"]

    errors = nabla_nav.task_dependency_cycles(
        scenario,
        {"TEST-ARTIFACT": {"provided_by": "NO-SUCH-TASK"}},
    )

    assert "TEST-ARTIFACT: unknown provider task NO-SUCH-TASK" in errors


def test_artifact_provider_must_declare_artifact_change() -> None:
    _, _, tasks, _ = repository_state()

    errors = nabla_nav.artifact_provider_errors(
        tasks,
        {"TEST-ARTIFACT": {"provided_by": "BOOT-NAV-001"}},
    )

    assert errors == [
        "TEST-ARTIFACT: provider task BOOT-NAV-001 must declare the artifact "
        "in contracts.changes"
    ]


def test_available_artifact_requires_completed_provider() -> None:
    _, _, tasks, _ = repository_state()
    scenario = copy.deepcopy(tasks)
    scenario["BOOT-PROTECT-001"]["state"] = "blocked"

    errors = nabla_nav.artifact_provider_errors(
        scenario,
        {
            "GITHUB-BRANCH-PROTECTION": {
                "status": "available",
                "provided_by": "BOOT-PROTECT-001",
            }
        },
    )

    assert errors == [
        "GITHUB-BRANCH-PROTECTION: available artifact provider task is not "
        "completed: BOOT-PROTECT-001"
    ]


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
    assert any("AUDIT-SCAFFOLD-READINESS-001 must be completed" in error for error in errors)
    assert any("must directly depend on AUDIT-SCAFFOLD-READINESS-001" in error for error in errors)


def test_ready_implementation_requires_completed_scaffold_gate_dependency() -> None:
    index, docs, tasks, _ = repository_state()
    scenario = copy.deepcopy(tasks)
    gate_id = nabla_nav.SCAFFOLD_READINESS_TASK_ID
    scenario[gate_id]["state"] = "blocked"
    task = copy.deepcopy(tasks["BOOT-NAV-001"])
    task["state"] = "ready"
    task["type"] = "implementation"
    task["context"]["packs"] = []
    task["context"]["required"] = ["ARCH:25"]
    task["dependencies"]["tasks"] = [gate_id]

    errors, _ = nabla_nav.validate_task_semantics(
        task, scenario, index, docs, {}, {}
    )

    assert any(f"{gate_id} must be completed" in error for error in errors)
    assert not any(f"must directly depend on {gate_id}" in error for error in errors)


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

    assert {f"ADR-{number:03d}" for number in range(1, 13)} <= set(decisions)
    assert {
        entry["status"] for entry in decisions.values()
    } <= {"required", "proposed", "accepted", "superseded"}


def test_required_artifacts_are_registered_with_lifecycle_status() -> None:
    artifacts = nabla_nav.load_registry(
        ROOT / "governance" / "artifacts.yaml", "artifacts"
    )

    assert {
        "BACKUP-RECOVERY-SPEC",
        "CORE-PORTABILITY-SPIKE",
        "GITHUB-BRANCH-PROTECTION",
    } <= set(artifacts)
    assert {
        entry["status"] for entry in artifacts.values()
    } <= {"missing", "required", "available", "superseded"}


def test_completed_task_accepts_superseded_dependencies() -> None:
    index, docs, tasks, _ = repository_state()
    task = copy.deepcopy(tasks["BOOT-NAV-001"])
    task["state"] = "completed"
    task["dependencies"]["decisions"] = ["ADR-TEST"]
    task["dependencies"]["artifacts"] = ["ARTIFACT-TEST"]

    errors, _ = nabla_nav.validate_task_semantics(
        task,
        tasks,
        index,
        docs,
        {"ADR-TEST": {"status": "superseded"}},
        {"ARTIFACT-TEST": {"status": "superseded"}},
    )

    assert errors == []


def test_ready_task_rejects_superseded_dependencies() -> None:
    index, docs, tasks, _ = repository_state()
    task = copy.deepcopy(tasks["BOOT-NAV-001"])
    task["state"] = "ready"
    task["dependencies"]["decisions"] = ["ADR-TEST"]
    task["dependencies"]["artifacts"] = ["ARTIFACT-TEST"]

    errors, _ = nabla_nav.validate_task_semantics(
        task,
        tasks,
        index,
        docs,
        {"ADR-TEST": {"status": "superseded"}},
        {"ARTIFACT-TEST": {"status": "superseded"}},
    )

    assert any("blocking decision is not accepted" in error for error in errors)
    assert any("blocking artifact is not available" in error for error in errors)


def write_evidence(
    root: Path,
    task: dict,
    *,
    tests: list[dict] | None = None,
    proofs: list[dict] | None = None,
    owner_approval: dict | None = None,
    overrides: dict | None = None,
) -> None:
    path = root / "roadmap" / "evidence" / f"{task['task_id']}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    evidence = {
        "schema_version": 2,
        "task_id": task["task_id"],
        "context_manifest_sha256": "manifest",
        "selectors": [],
        "document_hashes": {},
        "impact_tags": [],
        "triggers": [],
        "changed_paths": [],
        "changed_contracts": [],
        "tests": tests or [],
        "acceptance_evidence": proofs or [],
        "owner_approval": owner_approval
        or {"approved": False, "reference": ""},
        "unresolved_decisions": [],
        "pr_url": "https://github.com/colibri-the-bird/Nabla/pull/99",
    }
    evidence.update(overrides or {})
    path.write_text(
        yaml.safe_dump(
            evidence,
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_completed_evidence_covers_declared_acceptance_and_owner(
    tmp_path: Path,
) -> None:
    task = copy.deepcopy(repository_state()[2]["BOOT-NAV-001"])
    task["task_id"] = "TEST-EVIDENCE-001"
    task["state"] = "completed"
    task["acceptance"]["tests"] = ["declared test"]
    task["acceptance"]["evidence"] = ["declared proof"]
    write_evidence(
        tmp_path,
        task,
        tests=[
            {
                "requirement": "declared test",
                "command": "python -m pytest -q",
                "exit_code": 0,
            }
        ],
        proofs=[{"requirement": "declared proof", "proof": "artifact://proof"}],
        owner_approval={"approved": True, "reference": "owner prompt"},
    )

    assert nabla_nav.validate_evidence(tmp_path, task) == []


def test_completed_evidence_rejects_missing_or_failed_requirements(
    tmp_path: Path,
) -> None:
    task = copy.deepcopy(repository_state()[2]["BOOT-NAV-001"])
    task["task_id"] = "TEST-EVIDENCE-002"
    task["state"] = "completed"
    task["acceptance"]["tests"] = ["declared test", "missing test"]
    task["acceptance"]["evidence"] = ["declared proof"]
    write_evidence(
        tmp_path,
        task,
        tests=[
            {
                "requirement": "declared test",
                "command": "python -m pytest -q",
                "exit_code": 1,
            },
            {
                "requirement": "unrelated test",
                "command": "true",
                "exit_code": 0,
            },
        ],
        proofs=[{"requirement": "declared proof", "proof": ""}],
    )

    errors = nabla_nav.validate_evidence(tmp_path, task)

    assert any("undeclared requirement 'unrelated test'" in error for error in errors)
    assert any("missing acceptance test 'missing test'" in error for error in errors)
    assert any("acceptance test did not exit with 0" in error for error in errors)
    assert any("requires non-empty proof" in error for error in errors)
    assert any("requires explicit owner approval" in error for error in errors)


def test_non_owner_task_does_not_require_owner_approval(tmp_path: Path) -> None:
    task = copy.deepcopy(repository_state()[2]["BOOT-SLICE-001"])
    task["task_id"] = "TEST-EVIDENCE-003"
    task["state"] = "completed"
    task["acceptance"]["tests"] = []
    task["acceptance"]["evidence"] = []
    task["approval"]["owner_required"] = False
    write_evidence(tmp_path, task)

    assert nabla_nav.validate_evidence(tmp_path, task) == []


def test_evidence_rejects_malformed_provenance_without_crashing(
    tmp_path: Path,
) -> None:
    task = copy.deepcopy(repository_state()[2]["BOOT-NAV-001"])
    task["task_id"] = "TEST-EVIDENCE-004"
    task["state"] = "completed"
    task["acceptance"]["tests"] = []
    task["acceptance"]["evidence"] = []
    write_evidence(
        tmp_path,
        task,
        owner_approval={"approved": True, "reference": 7},
        overrides={
            "selectors": ["NAV:1", 3],
            "triggers": [5],
            "changed_paths": [9],
            "document_hashes": {"NAV": 7, 4: "hash"},
        },
    )

    errors = nabla_nav.validate_evidence(tmp_path, task)

    assert any("selectors[1]: non-empty string required" in error for error in errors)
    assert any("triggers[0]: non-empty string required" in error for error in errors)
    assert any("changed_paths[0]: non-empty string required" in error for error in errors)
    assert any("non-empty string keys required" in error for error in errors)
    assert any("non-empty string hash required" in error for error in errors)
    assert any("owner_approval.reference: string required" in error for error in errors)
    assert any("requires explicit owner approval" in error for error in errors)


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
                "schema_version": 2,
                "task_id": "BOOT-CI-001",
                "context_manifest_sha256": "stale",
                "selectors": [],
                "document_hashes": {},
                "impact_tags": [],
                "triggers": ["scope-expanded"],
                "changed_paths": ["wrong.txt"],
                "changed_contracts": [],
                "tests": [
                    {
                        "requirement": "pytest",
                        "command": "pytest",
                        "exit_code": 1,
                    }
                ],
                "acceptance_evidence": [],
                "owner_approval": {"approved": True, "reference": "owner prompt"},
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
        lambda *_: (
            "context",
            {
                "manifest_sha256": "current",
                "selectors": ["NAV:6"],
                "documents": {"NAV": {"sha256": "current-doc"}},
                "impact_tags": ["failure-domain"],
                "triggers": [],
            },
        ),
    )

    errors = nabla_nav.validate_pr_evidence(
        tmp_path,
        task,
        tmp_path / "roadmap" / "tasks" / "BOOT-CI-001.yaml",
        [".github/workflows/bootstrap-gates.yml"],
        "https://github.com/colibri-the-bird/Nabla/pull/2",
    )

    assert any("context manifest is stale" in error for error in errors)
    assert any("selectors does not match" in error for error in errors)
    assert any("document_hashes does not match" in error for error in errors)
    assert any("impact_tags does not match" in error for error in errors)
    assert any("triggers does not match" in error for error in errors)
    assert any("changed_paths does not match" in error for error in errors)
    assert any("pr_url does not match" in error for error in errors)


def test_pr_evidence_rebuilds_triggered_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = copy.deepcopy(repository_state()[2]["BOOT-PILOT-001"])
    task["state"] = "completed"
    pr_url = "https://github.com/colibri-the-bird/Nabla/pull/2"
    changed_paths = ["tests/pilot/smoke.txt"]
    write_evidence(
        tmp_path,
        task,
        overrides={
            "context_manifest_sha256": "triggered",
            "selectors": ["NAV:3"],
            "document_hashes": {"NAV": "nav-hash"},
            "impact_tags": ["failure-domain"],
            "triggers": ["scope-expanded"],
            "changed_paths": changed_paths,
            "pr_url": pr_url,
        },
    )
    captured: dict[str, list[str]] = {}

    def fake_build_context_bundle(*args):
        captured["triggers"] = list(args[5])
        return (
            "context",
            {
                "manifest_sha256": "triggered",
                "selectors": ["NAV:3"],
                "documents": {"NAV": {"sha256": "nav-hash"}},
                "impact_tags": ["failure-domain"],
                "triggers": ["scope-expanded"],
            },
        )

    monkeypatch.setattr(nabla_nav, "validate_evidence", lambda *_: [])
    monkeypatch.setattr(spec_slice, "load_index", lambda *_: {})
    monkeypatch.setattr(spec_slice, "validate_index", lambda *_: ([], [], {}))
    monkeypatch.setattr(nabla_nav, "build_context_bundle", fake_build_context_bundle)

    errors = nabla_nav.validate_pr_evidence(
        tmp_path,
        task,
        tmp_path / "roadmap" / "tasks" / "BOOT-PILOT-001.yaml",
        changed_paths,
        pr_url,
    )

    assert errors == []
    assert captured["triggers"] == ["scope-expanded"]


def test_workflow_has_exact_required_checks_and_no_path_filters() -> None:
    workflow_path = ROOT / ".github" / "workflows" / "bootstrap-gates.yml"
    workflow = yaml.load(workflow_path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    assert {
        "navigation-linux",
        "navigation-windows",
        "task-card-gate",
        "scope-and-evidence-gate",
        "spec-lock-and-traceability-gate",
    } <= set(workflow["jobs"])
    assert workflow["on"]["pull_request"] == ""
    assert workflow["on"]["push"]["branches"] == ["main"]
    assert "paths" not in workflow["on"]["push"]
    windows_runs = [
        step["run"]
        for step in workflow["jobs"]["navigation-windows"]["steps"]
        if "run" in step
    ]
    assert "python -m pytest -q tests/test_nabla_nav.py" in windows_runs
    assert "python tools/nabla_nav.py validate" in windows_runs
