from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import nabla_nav  # noqa: E402
import spec_slice  # noqa: E402


TASK_ID = "BOOT-PILOT-001"


def pilot_bundle() -> tuple[dict, str, dict]:
    index = spec_slice.load_index(ROOT / "spec-index.json")
    errors, warnings, docs = spec_slice.validate_index(ROOT, index)
    assert errors == []
    assert warnings == []
    tasks, paths = nabla_nav.load_tasks(ROOT)
    task = tasks[TASK_ID]
    context, manifest = nabla_nav.build_context_bundle(
        ROOT,
        task,
        paths[TASK_ID],
        index,
        docs,
    )
    return task, context, manifest


def test_pilot_context_is_exact_bounded_and_deterministic() -> None:
    task, first_context, first_manifest = pilot_bundle()
    _, second_context, second_manifest = pilot_bundle()

    assert task["state"] == "blocked"
    assert task["dependencies"]["tasks"] == ["BOOT-CI-001"]
    assert task["dependencies"]["artifacts"] == ["GITHUB-BRANCH-PROTECTION"]
    assert first_manifest["context_words"] < 12000
    assert first_manifest["budget_warning"] is False
    assert all(not selector.endswith(":full") for selector in first_manifest["selectors"])
    assert set(first_manifest["documents"]) == {
        selector.split(":", 1)[0] for selector in first_manifest["selectors"]
    }
    assert first_context.encode("utf-8") == second_context.encode("utf-8")
    assert nabla_nav.canonical_json(first_manifest) == nabla_nav.canonical_json(
        second_manifest
    )


def test_pilot_scope_excludes_production_and_markdown() -> None:
    task, _, _ = pilot_bundle()
    included = task["scope"]["paths"]["include"]
    excluded = task["scope"]["paths"]["exclude"]

    assert included == [
        "tests/pilot/**",
        "roadmap/tasks/BOOT-PILOT-001.yaml",
        "roadmap/evidence/BOOT-PILOT-001.yaml",
    ]
    assert {"*.md", "src/**", "app/**", "core/**"}.issubset(excluded)
    assert nabla_nav.validate_changed_paths(
        task, ["tests/pilot/test_bootstrap_pilot.py"]
    ) == []
