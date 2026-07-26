#!/usr/bin/env python3
"""Validate Nabla task cards and prepare exact, hash-pinned Codex context."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

try:
    import yaml
except ImportError as exc:  # pragma: no cover - exercised by installation failure
    raise SystemExit(
        "PyYAML is required; run: python -m pip install -r tools/requirements.txt"
    ) from exc

import spec_slice


TASK_TYPES = {"spec", "adr", "spike", "tooling", "audit", "implementation"}
TASK_STATES = {"draft", "ready", "blocked", "completed"}
TASK_SCHEMA_VERSION = 2
EVIDENCE_SCHEMA_VERSION = 2
SCAFFOLD_READINESS_TASK_ID = "AUDIT-SCAFFOLD-READINESS-001"
TASK_REQUIRED_KEYS = {
    "schema_version",
    "task_id",
    "type",
    "state",
    "outcome",
    "router",
    "scope",
    "context",
    "contracts",
    "dependencies",
    "acceptance",
    "approval",
}
EVIDENCE_REQUIRED_KEYS = {
    "schema_version",
    "task_id",
    "context_manifest_sha256",
    "selectors",
    "document_hashes",
    "impact_tags",
    "triggers",
    "changed_paths",
    "changed_contracts",
    "tests",
    "acceptance_evidence",
    "owner_approval",
    "unresolved_decisions",
    "pr_url",
}
PR_TITLE_RE = re.compile(r"^\[([A-Z0-9]+(?:-[A-Z0-9]+)+)\]\s+\S")


class NavError(RuntimeError):
    pass


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def normalized_text_sha256(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return sha256_bytes(normalized.encode("utf-8"))


def canonical_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def read_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise NavError(f"cannot read YAML {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise NavError(f"{path}: YAML root must be a mapping")
    return data


def expect_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise NavError(f"{label}: mapping required")
    return value


def expect_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise NavError(f"{label}: list required")
    return value


def expect_string_list(value: Any, label: str) -> list[str]:
    result = expect_list(value, label)
    if any(not isinstance(item, str) or not item.strip() for item in result):
        raise NavError(f"{label}: non-empty strings required")
    return result


def require_keys(mapping: dict[str, Any], required: set[str], label: str) -> None:
    missing = sorted(required - set(mapping))
    if missing:
        raise NavError(f"{label}: missing keys: {', '.join(missing)}")


def load_tasks(root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Path]]:
    tasks: dict[str, dict[str, Any]] = {}
    paths: dict[str, Path] = {}
    task_dir = root / "roadmap" / "tasks"
    if not task_dir.is_dir():
        raise NavError(f"task directory is missing: {task_dir}")
    for path in sorted(task_dir.glob("*.yaml")):
        task = read_yaml(path)
        task_id = task.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise NavError(f"{path}: task_id must be a non-empty string")
        if task_id in tasks:
            raise NavError(f"duplicate task_id {task_id}: {paths[task_id]} and {path}")
        if path.stem != task_id:
            raise NavError(f"{path}: filename must match task_id {task_id}")
        tasks[task_id] = task
        paths[task_id] = path
    if not tasks:
        raise NavError(f"no task cards found in {task_dir}")
    return tasks, paths


def task_dependency_cycles(
    tasks: dict[str, dict[str, Any]],
    artifacts: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []
    errors: list[str] = []

    def visit(task_id: str) -> None:
        if task_id in visited:
            return
        if task_id in visiting:
            start = stack.index(task_id)
            errors.append("task dependency cycle: " + " -> ".join(stack[start:] + [task_id]))
            return
        visiting.add(task_id)
        stack.append(task_id)
        dependencies = tasks[task_id].get("dependencies", {})
        dependency_ids = list(
            dependencies.get("tasks", []) if isinstance(dependencies, dict) else []
        )
        if artifacts is not None and isinstance(dependencies, dict):
            for artifact_id in dependencies.get("artifacts", []):
                artifact = artifacts.get(artifact_id)
                if artifact is None:
                    continue
                provider = artifact.get("provided_by")
                if provider is None:
                    continue
                if not isinstance(provider, str) or not provider.strip():
                    errors.append(
                        f"{artifact_id}: provided_by must be a non-empty task ID"
                    )
                    continue
                if provider not in tasks:
                    errors.append(
                        f"{artifact_id}: unknown provider task {provider}"
                    )
                    continue
                dependency_ids.append(provider)
        for dependency in dependency_ids:
            if dependency not in tasks:
                errors.append(f"{task_id}: unknown task dependency {dependency}")
            else:
                visit(dependency)
        stack.pop()
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in tasks:
        visit(task_id)
    return errors


def ready_cardinality_errors(tasks: dict[str, dict[str, Any]]) -> list[str]:
    ready = sorted(
        task_id for task_id, task in tasks.items() if task.get("state") == "ready"
    )
    if len(ready) <= 1:
        return []
    return ["more than one task is ready: " + ", ".join(ready)]


def artifact_provider_errors(
    tasks: dict[str, dict[str, Any]],
    artifacts: dict[str, dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    for artifact_id, artifact in artifacts.items():
        provider = artifact.get("provided_by")
        if provider is None:
            continue
        if not isinstance(provider, str) or not provider.strip():
            errors.append(f"{artifact_id}: provided_by must be a non-empty task ID")
            continue
        task = tasks.get(provider)
        if task is None:
            errors.append(f"{artifact_id}: unknown provider task {provider}")
            continue
        changes = task.get("contracts", {}).get("changes", [])
        if artifact_id not in changes:
            errors.append(
                f"{artifact_id}: provider task {provider} must declare the artifact "
                "in contracts.changes"
            )
        if artifact.get("status") == "available" and task.get("state") != "completed":
            errors.append(
                f"{artifact_id}: available artifact provider task is not completed: "
                f"{provider}"
            )
    return errors


def bootstrap_chain_errors(tasks: dict[str, dict[str, Any]]) -> list[str]:
    bootstrap = {
        task_id: task
        for task_id, task in tasks.items()
        if isinstance(task.get("router"), str)
        and task["router"].startswith("BOOT:")
    }
    if not bootstrap:
        return ["bootstrap task chain is missing"]

    errors: list[str] = []
    predecessors: dict[str, list[str]] = {}
    successors: dict[str, list[str]] = {task_id: [] for task_id in bootstrap}
    for task_id, task in bootstrap.items():
        declared = task.get("dependencies", {}).get("tasks", [])
        foreign = [dependency for dependency in declared if dependency not in bootstrap]
        if foreign:
            errors.append(
                f"{task_id}: bootstrap task depends outside bootstrap chain: "
                + ", ".join(foreign)
            )
        direct = [dependency for dependency in declared if dependency in bootstrap]
        predecessors[task_id] = direct
        if len(direct) > 1:
            errors.append(
                f"{task_id}: bootstrap chain requires exactly one predecessor, "
                f"found {len(direct)}"
            )
        for dependency in direct:
            successors[dependency].append(task_id)

    roots = sorted(task_id for task_id, deps in predecessors.items() if not deps)
    tails = sorted(task_id for task_id, next_ids in successors.items() if not next_ids)
    if len(roots) != 1:
        errors.append(
            "bootstrap chain requires exactly one root, found: "
            + (", ".join(roots) if roots else "none")
        )
    if len(tails) != 1:
        errors.append(
            "bootstrap chain requires exactly one tail, found: "
            + (", ".join(tails) if tails else "none")
        )
    for task_id, next_ids in successors.items():
        if len(next_ids) > 1:
            errors.append(
                f"{task_id}: bootstrap chain branches to: "
                + ", ".join(sorted(next_ids))
            )
    if errors or not roots:
        return errors

    ordered: list[str] = []
    current = roots[0]
    while current not in ordered:
        ordered.append(current)
        next_ids = successors[current]
        if not next_ids:
            break
        if len(next_ids) != 1:
            break
        current = next_ids[0]
    if len(ordered) != len(bootstrap):
        missing = sorted(set(bootstrap) - set(ordered))
        errors.append(
            "bootstrap chain is disconnected or cyclic; unreachable: "
            + ", ".join(missing)
        )
        return errors

    ready_positions = [
        position
        for position, task_id in enumerate(ordered)
        if bootstrap[task_id].get("state") == "ready"
    ]
    if ready_positions:
        ready_position = ready_positions[0]
        for task_id in ordered[:ready_position]:
            if bootstrap[task_id].get("state") != "completed":
                errors.append(
                    f"{task_id}: task before the ready frontier must be completed"
                )
        for task_id in ordered[ready_position + 1 :]:
            if bootstrap[task_id].get("state") not in {"blocked", "draft"}:
                errors.append(
                    f"{task_id}: task after the ready frontier must be blocked or draft"
                )
    elif any(task.get("state") != "completed" for task in bootstrap.values()):
        errors.append("non-completed bootstrap chain requires exactly one ready task")

    for predecessor, successor in zip(ordered, ordered[1:]):
        if bootstrap[successor].get("state") == "completed":
            continue
        successor_path = f"roadmap/tasks/{successor}.yaml"
        include = bootstrap[predecessor].get("scope", {}).get("paths", {}).get(
            "include", []
        )
        if not match_any(successor_path, include):
            errors.append(
                f"{predecessor}: scope does not authorize successor card "
                f"{successor_path}"
            )

    implementation = sorted(
        task_id
        for task_id, task in bootstrap.items()
        if task.get("type") == "implementation"
    )
    if implementation:
        errors.append(
            "bootstrap chain cannot contain implementation tasks: "
            + ", ".join(implementation)
        )
    if len(tails) == 1:
        tail = bootstrap[tails[0]]
        if tail.get("type") != "audit" or not tail.get("approval", {}).get(
            "owner_required"
        ):
            errors.append(
                f"{tails[0]}: bootstrap tail must be an owner-required audit"
            )
    return errors


def is_approved_document(doc: spec_slice.ParsedDocument) -> bool:
    status = (doc.status or "").lower()
    return (
        ("утвержден" in status or "утверждён" in status or "approved" in status)
        and "к утвержд" not in status
        and "draft" not in status
        and not status.startswith("проект")
    )


def validate_task_shape(task: dict[str, Any], path: Path) -> list[str]:
    errors: list[str] = []
    label = str(path)
    try:
        require_keys(task, TASK_REQUIRED_KEYS, label)
        if task["schema_version"] != TASK_SCHEMA_VERSION:
            raise NavError(
                f"{label}: schema_version must be {TASK_SCHEMA_VERSION}"
            )
        if task["type"] not in TASK_TYPES:
            raise NavError(f"{label}: unsupported task type {task['type']!r}")
        if task["state"] not in TASK_STATES:
            raise NavError(f"{label}: unsupported task state {task['state']!r}")
        for key in ("task_id", "outcome", "router"):
            if not isinstance(task[key], str) or not task[key].strip():
                raise NavError(f"{label}.{key}: non-empty string required")

        scope = expect_mapping(task["scope"], f"{label}.scope")
        require_keys(scope, {"include", "exclude", "paths"}, f"{label}.scope")
        expect_string_list(scope["include"], f"{label}.scope.include")
        expect_string_list(scope["exclude"], f"{label}.scope.exclude")
        paths = expect_mapping(scope["paths"], f"{label}.scope.paths")
        require_keys(paths, {"include", "exclude"}, f"{label}.scope.paths")
        if not expect_string_list(paths["include"], f"{label}.scope.paths.include"):
            raise NavError(f"{label}.scope.paths.include: at least one pattern required")
        expect_string_list(paths["exclude"], f"{label}.scope.paths.exclude")

        context = expect_mapping(task["context"], f"{label}.context")
        require_keys(
            context,
            {
                "packs",
                "required",
                "conditional",
                "impact_tags",
                "full_document_reads",
                "context_budget_justification",
            },
            f"{label}.context",
        )
        for position, pack in enumerate(expect_list(context["packs"], f"{label}.context.packs")):
            pack = expect_mapping(pack, f"{label}.context.packs[{position}]")
            require_keys(pack, {"id", "version"}, f"{label}.context.packs[{position}]")
            if not isinstance(pack["id"], str) or not isinstance(pack["version"], int):
                raise NavError(f"{label}.context.packs[{position}]: id/string and version/int required")
        expect_string_list(context["required"], f"{label}.context.required")
        expect_string_list(context["impact_tags"], f"{label}.context.impact_tags")
        for position, condition in enumerate(
            expect_list(context["conditional"], f"{label}.context.conditional")
        ):
            condition = expect_mapping(condition, f"{label}.context.conditional[{position}]")
            require_keys(
                condition,
                {"when", "selectors", "packs", "impact_tags"},
                f"{label}.context.conditional[{position}]",
            )
            if not isinstance(condition["when"], str) or not condition["when"]:
                raise NavError(f"{label}.context.conditional[{position}].when: string required")
            expect_string_list(
                condition["selectors"], f"{label}.context.conditional[{position}].selectors"
            )
            expect_string_list(condition["packs"], f"{label}.context.conditional[{position}].packs")
            expect_string_list(
                condition["impact_tags"], f"{label}.context.conditional[{position}].impact_tags"
            )
        for position, full_read in enumerate(
            expect_list(context["full_document_reads"], f"{label}.context.full_document_reads")
        ):
            full_read = expect_mapping(
                full_read, f"{label}.context.full_document_reads[{position}]"
            )
            require_keys(
                full_read,
                {"selector", "reason"},
                f"{label}.context.full_document_reads[{position}]",
            )
            if not str(full_read["selector"]).endswith(":full") or not str(
                full_read["reason"]
            ).strip():
                raise NavError(
                    f"{label}.context.full_document_reads[{position}]: "
                    "DOC:full selector and reason required"
                )
        justification = context["context_budget_justification"]
        if justification is not None and (
            not isinstance(justification, str) or not justification.strip()
        ):
            raise NavError(
                f"{label}.context.context_budget_justification: null or non-empty string required"
            )

        for section in ("contracts", "dependencies", "acceptance", "approval"):
            expect_mapping(task[section], f"{label}.{section}")
        require_keys(
            task["contracts"], {"reads", "writes", "changes"}, f"{label}.contracts"
        )
        for key in ("reads", "writes", "changes"):
            expect_string_list(task["contracts"][key], f"{label}.contracts.{key}")
        require_keys(
            task["dependencies"],
            {"tasks", "decisions", "artifacts"},
            f"{label}.dependencies",
        )
        for key in ("tasks", "decisions", "artifacts"):
            expect_string_list(task["dependencies"][key], f"{label}.dependencies.{key}")
        require_keys(
            task["acceptance"],
            {"tests", "invariants", "evidence"},
            f"{label}.acceptance",
        )
        for key in ("tests", "invariants", "evidence"):
            expect_string_list(task["acceptance"][key], f"{label}.acceptance.{key}")
        require_keys(
            task["approval"],
            {"owner_required", "required_spec_status"},
            f"{label}.approval",
        )
        if not isinstance(task["approval"]["owner_required"], bool):
            raise NavError(f"{label}.approval.owner_required: boolean required")
        if task["approval"]["required_spec_status"] not in {"approved", "draft-allowed"}:
            raise NavError(
                f"{label}.approval.required_spec_status: approved or draft-allowed required"
            )
    except NavError as exc:
        errors.append(str(exc))
    return errors


def active_condition(
    task: dict[str, Any], trigger: str
) -> dict[str, Any] | None:
    for condition in task["context"]["conditional"]:
        if condition["when"] == trigger:
            return condition
    return None


def expanded_task_context(
    task: dict[str, Any],
    index: dict[str, Any],
    triggers: Sequence[str] = (),
) -> tuple[list[str], list[str], list[str]]:
    pack_ids = [pack["id"] for pack in task["context"]["packs"]]
    tags = list(task["context"]["impact_tags"])
    selectors = list(task["context"]["required"])
    selectors.extend(item["selector"] for item in task["context"]["full_document_reads"])
    for trigger in triggers:
        condition = active_condition(task, trigger)
        if condition is None:
            raise NavError(f"{task['task_id']}: unknown conditional trigger {trigger!r}")
        selectors.extend(condition["selectors"])
        pack_ids.extend(condition["packs"])
        tags.extend(condition["impact_tags"])
    expanded = spec_slice.expand_context(index, pack_ids, tags, selectors)
    return expanded, pack_ids, tags


def validate_pack_pins(task: dict[str, Any], index: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    packs = index.get("context_packs", {})
    for pin in task["context"]["packs"]:
        pack_id = pin["id"]
        if pack_id not in packs:
            errors.append(f"{task['task_id']}: unknown context pack {pack_id}")
        elif packs[pack_id].get("version") != pin["version"]:
            errors.append(
                f"{task['task_id']}: context pack {pack_id} is pinned to "
                f"{pin['version']}, repository has {packs[pack_id].get('version')}"
            )
    return errors


def task_context_body(
    task: dict[str, Any],
    docs: dict[str, spec_slice.ParsedDocument],
    index: dict[str, Any],
    selectors: list[str],
    pack_ids: list[str],
    tags: list[str],
) -> str:
    scope = task["scope"]
    acceptance = task["acceptance"]

    def bullets(items: Iterable[str]) -> str:
        items = list(items)
        return "\n".join(f"- {item}" for item in items) if items else "- none"

    task_header = f"""# Task {task['task_id']}

## Outcome

{task['outcome']}

## Scope include

{bullets(scope['include'])}

## Scope exclude

{bullets(scope['exclude'])}

## Allowed paths

{bullets(scope['paths']['include'])}

## Acceptance tests

{bullets(acceptance['tests'])}

## Required evidence

{bullets(acceptance['evidence'])}

## Invariants

{bullets(acceptance['invariants'])}

---
"""
    normative = spec_slice.build_slice(
        docs,
        spec_slice.document_entries(index),
        selectors,
        requested_selectors=task["context"]["required"],
        packs=pack_ids,
        tags=tags,
    )
    return task_header + normative


def build_context_bundle(
    root: Path,
    task: dict[str, Any],
    task_path: Path,
    index: dict[str, Any],
    docs: dict[str, spec_slice.ParsedDocument],
    triggers: Sequence[str] = (),
) -> tuple[str, dict[str, Any]]:
    selectors, pack_ids, tags = expanded_task_context(task, index, triggers)
    body = task_context_body(task, docs, index, selectors, pack_ids, tags)
    words = spec_slice.word_count(body)
    justification = task["context"]["context_budget_justification"]
    if words > 16000:
        raise NavError(f"{task['task_id']}: context has {words} words; hard limit is 16000")
    if words > 12000 and not justification:
        raise NavError(
            f"{task['task_id']}: context has {words} words; "
            "context_budget_justification is required above 12000"
        )

    selected_doc_ids = sorted({spec_slice.parse_selector(item)[0] for item in selectors})
    documents = {
        doc_id: {
            "canonical_path": spec_slice.document_entries(index)[doc_id]["canonical_path"],
            "version": docs[doc_id].version
            or spec_slice.document_entries(index)[doc_id].get("version")
            or "unknown",
            "status": docs[doc_id].status or "unknown",
            "sha256": docs[doc_id].sha256,
        }
        for doc_id in selected_doc_ids
    }
    pack_versions = {
        pack_id: index["context_packs"][pack_id]["version"] for pack_id in sorted(set(pack_ids))
    }
    manifest_payload = {
        "schema_version": 1,
        "task_id": task["task_id"],
        "task_card_sha256": normalized_text_sha256(task_path),
        "router": task["router"],
        "triggers": sorted(set(triggers)),
        "packs": pack_versions,
        "impact_tags": sorted(set(tags)),
        "selectors": selectors,
        "documents": documents,
        "context_content_sha256": sha256_bytes(body.encode("utf-8")),
        "context_words": words,
        "budget_warning": words > 12000,
    }
    manifest_sha = sha256_bytes(canonical_json(manifest_payload).encode("utf-8"))
    manifest = {**manifest_payload, "manifest_sha256": manifest_sha}
    context = (
        "<!-- Generated by tools/nabla_nav.py; do not commit. -->\n"
        f"<!-- manifest_sha256: {manifest_sha} -->\n\n"
        + body
    )
    return context, manifest


def load_registry(path: Path, top_level_key: str) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    data = read_yaml(path)
    entries = data.get(top_level_key, [])
    if not isinstance(entries, list):
        raise NavError(f"{path}: {top_level_key} must be a list")
    result: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise NavError(f"{path}: each {top_level_key} entry requires string id")
        if entry["id"] in result:
            raise NavError(f"{path}: duplicate id {entry['id']}")
        result[entry["id"]] = entry
    return result


def build_spec_lock(
    root: Path,
    index: dict[str, Any],
    docs: dict[str, spec_slice.ParsedDocument],
) -> dict[str, Any]:
    entries = spec_slice.document_entries(index)
    documents: dict[str, Any] = {}
    for doc_id, entry in entries.items():
        doc = docs.get(doc_id)
        if doc is None:
            documents[doc_id] = {
                "canonical_path": entry["canonical_path"],
                "normative": entry.get("normative", True),
                "planned": entry.get("planned", False),
                "exists": False,
                "version": entry.get("version"),
                "status": "planned" if entry.get("planned") else "missing",
                "sha256": None,
                "selectors": [],
            }
            continue
        selectors = [f"{doc_id}:meta", *(f"{doc_id}:{item.key}" for item in doc.heading_order)]
        documents[doc_id] = {
            "canonical_path": entry["canonical_path"],
            "normative": entry.get("normative", True),
            "planned": entry.get("planned", False),
            "exists": True,
            "version": doc.version or entry.get("version"),
            "status": doc.status or "unknown",
            "sha256": doc.sha256,
            "selectors": selectors,
        }

    packs: dict[str, Any] = {}
    for pack_id, pack in sorted(index.get("context_packs", {}).items()):
        payload = {
            "version": pack["version"],
            "tags": pack.get("tags", []),
            "selectors": pack.get("selectors", []),
        }
        packs[pack_id] = {
            **payload,
            "sha256": sha256_bytes(canonical_json(payload).encode("utf-8")),
        }
    impact_tags = index.get("impact_tags", {})
    return {
        "schema_version": 1,
        "generated_policy": (
            "Generated by tools/nabla_nav.py generate-lock; "
            "do not edit independently."
        ),
        "spec_index_sha256": sha256_bytes((root / "spec-index.json").read_bytes()),
        "impact_tags_sha256": sha256_bytes(
            canonical_json(impact_tags).encode("utf-8")
        ),
        "documents": documents,
        "context_packs": packs,
    }


def check_spec_lock(
    root: Path,
    index: dict[str, Any],
    docs: dict[str, spec_slice.ParsedDocument],
) -> list[str]:
    path = root / "governance" / "spec-lock.json"
    if not path.exists():
        return [f"living spec lock is missing: {path}"]
    try:
        actual = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"cannot read living spec lock {path}: {exc}"]
    expected = canonical_json(build_spec_lock(root, index, docs))
    return [] if actual == expected else [
        "governance/spec-lock.json is stale; run "
        "python tools/nabla_nav.py generate-lock"
    ]


def validate_governance(
    root: Path,
    index: dict[str, Any],
    docs: dict[str, spec_slice.ParsedDocument],
) -> tuple[
    list[str],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
]:
    errors: list[str] = []
    try:
        decisions = load_registry(root / "governance" / "decisions.yaml", "decisions")
        artifacts = load_registry(root / "governance" / "artifacts.yaml", "artifacts")
    except NavError as exc:
        return [str(exc)], {}, {}
    required_decisions = {f"ADR-{number:03d}" for number in range(1, 13)}
    missing_decisions = sorted(required_decisions - set(decisions))
    if missing_decisions:
        errors.append("decision registry is missing: " + ", ".join(missing_decisions))
    for decision_id, entry in decisions.items():
        if entry.get("status") not in {"required", "proposed", "accepted", "superseded"}:
            errors.append(f"{decision_id}: invalid decision status {entry.get('status')!r}")
        selectors = entry.get("selectors", [])
        if not isinstance(selectors, list):
            errors.append(f"{decision_id}: selectors must be a list")
            continue
        for selector in selectors:
            try:
                spec_slice.validate_selector(
                    selector, docs, spec_slice.document_entries(index)
                )
            except spec_slice.SpecError as exc:
                errors.append(f"{decision_id}: {exc}")

    required_artifacts = {
        "BACKUP-RECOVERY-SPEC",
        "CORE-PORTABILITY-SPIKE",
        "GITHUB-BRANCH-PROTECTION",
    }
    missing_artifacts = sorted(required_artifacts - set(artifacts))
    if missing_artifacts:
        errors.append("artifact registry is missing: " + ", ".join(missing_artifacts))
    for artifact_id, entry in artifacts.items():
        if entry.get("status") not in {"missing", "required", "available", "superseded"}:
            errors.append(f"{artifact_id}: invalid artifact status {entry.get('status')!r}")

    trace_path = root / "governance" / "traceability.yaml"
    try:
        trace = read_yaml(trace_path)
        invariants = trace.get("invariants", [])
        if not isinstance(invariants, list):
            raise NavError(f"{trace_path}: invariants must be a list")
        by_id: dict[str, dict[str, Any]] = {}
        for entry in invariants:
            if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                raise NavError(f"{trace_path}: every invariant requires string id")
            invariant_id = entry["id"]
            if invariant_id in by_id:
                raise NavError(f"{trace_path}: duplicate invariant {invariant_id}")
            by_id[invariant_id] = entry
            if not isinstance(entry.get("owner"), str) or not entry["owner"]:
                errors.append(f"{invariant_id}: traceability owner is required")
            selectors = entry.get("selectors")
            future_tests = entry.get("future_tests")
            if not isinstance(selectors, list) or not selectors:
                errors.append(f"{invariant_id}: non-empty selectors required")
            else:
                for selector in selectors:
                    try:
                        spec_slice.validate_selector(
                            selector, docs, spec_slice.document_entries(index)
                        )
                    except spec_slice.SpecError as exc:
                        errors.append(f"{invariant_id}: {exc}")
            if not isinstance(future_tests, list) or not future_tests:
                errors.append(f"{invariant_id}: non-empty future_tests required")
        expected_invariants = {f"I{number}" for number in range(1, 17)}
        missing_invariants = sorted(expected_invariants - set(by_id))
        extra_invariants = sorted(set(by_id) - expected_invariants)
        if missing_invariants:
            errors.append("traceability is missing: " + ", ".join(missing_invariants))
        if extra_invariants:
            errors.append("traceability has unknown invariants: " + ", ".join(extra_invariants))
    except NavError as exc:
        errors.append(str(exc))

    errors.extend(check_spec_lock(root, index, docs))
    return errors, decisions, artifacts


def validate_task_semantics(
    task: dict[str, Any],
    tasks: dict[str, dict[str, Any]],
    index: dict[str, Any],
    docs: dict[str, spec_slice.ParsedDocument],
    decisions: dict[str, dict[str, Any]],
    artifacts: dict[str, dict[str, Any]],
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    task_id = task["task_id"]
    errors.extend(validate_pack_pins(task, index))
    try:
        selectors, _, _ = expanded_task_context(task, index)
        entries = spec_slice.document_entries(index)
        for selector in selectors:
            spec_slice.validate_selector(selector, docs, entries)
    except (NavError, spec_slice.SpecError) as exc:
        errors.append(str(exc))
        selectors = []

    dependencies = task["dependencies"]
    for dependency in dependencies["tasks"]:
        if dependency not in tasks:
            errors.append(f"{task_id}: unknown task dependency {dependency}")
    if task["state"] in {"ready", "completed"}:
        for dependency in dependencies["tasks"]:
            if dependency in tasks and tasks[dependency]["state"] != "completed":
                errors.append(
                    f"{task_id}: active task depends on non-completed task {dependency}"
                )
    for decision_id in dependencies["decisions"]:
        entry = decisions.get(decision_id)
        if entry is None:
            errors.append(f"{task_id}: unknown decision dependency {decision_id}")
        elif task["state"] == "ready" and entry.get("status") != "accepted":
            errors.append(f"{task_id}: blocking decision is not accepted: {decision_id}")
        elif task["state"] == "completed" and entry.get("status") not in {
            "accepted",
            "superseded",
        }:
            errors.append(
                f"{task_id}: completed task decision was never accepted: {decision_id}"
            )
    for artifact_id in dependencies["artifacts"]:
        entry = artifacts.get(artifact_id)
        if entry is None:
            errors.append(f"{task_id}: unknown artifact dependency {artifact_id}")
        elif task["state"] == "ready" and entry.get("status") != "available":
            errors.append(f"{task_id}: blocking artifact is not available: {artifact_id}")
        elif task["state"] == "completed" and entry.get("status") not in {
            "available",
            "superseded",
        }:
            errors.append(
                f"{task_id}: completed task artifact was never available: {artifact_id}"
            )

    if task["type"] == "implementation" and task["state"] == "ready":
        for selector in selectors:
            doc_id, _ = spec_slice.parse_selector(selector)
            if not is_approved_document(docs[doc_id]):
                errors.append(
                    f"{task_id}: implementation context uses draft document {doc_id}"
                )
        if "ROADMAP" not in docs:
            errors.append(f"{task_id}: production ROADMAP.md is required")
        scaffold_gate = tasks.get(SCAFFOLD_READINESS_TASK_ID)
        if scaffold_gate is None:
            errors.append(
                f"{task_id}: {SCAFFOLD_READINESS_TASK_ID} task is required"
            )
        elif scaffold_gate["state"] != "completed":
            errors.append(
                f"{task_id}: {SCAFFOLD_READINESS_TASK_ID} must be completed "
                "before implementation becomes ready"
            )
        if SCAFFOLD_READINESS_TASK_ID not in dependencies["tasks"]:
            errors.append(
                f"{task_id}: ready implementation must directly depend on "
                f"{SCAFFOLD_READINESS_TASK_ID}"
            )

    try:
        if selectors:
            context, _ = build_context_bundle(
                repository_root(),
                task,
                repository_root() / "roadmap" / "tasks" / f"{task_id}.yaml",
                index,
                docs,
            )
            words = spec_slice.word_count(context)
            if words > 12000:
                warnings.append(f"{task_id}: context budget warning: {words}/16000 words")
    except (NavError, OSError, spec_slice.SpecError) as exc:
        errors.append(str(exc))
    return errors, warnings


def validate_evidence(root: Path, task: dict[str, Any]) -> list[str]:
    path = root / "roadmap" / "evidence" / f"{task['task_id']}.yaml"
    if not path.exists():
        return (
            [f"{task['task_id']}: completed task requires evidence file {path}"]
            if task["state"] == "completed"
            else []
        )
    errors: list[str] = []
    try:
        evidence = read_yaml(path)
        require_keys(evidence, EVIDENCE_REQUIRED_KEYS, str(path))
        if evidence["schema_version"] != EVIDENCE_SCHEMA_VERSION:
            errors.append(
                f"{path}: schema_version must be {EVIDENCE_SCHEMA_VERSION}"
            )
        if evidence["task_id"] != task["task_id"]:
            errors.append(f"{path}: task_id does not match card")
        for key in (
            "selectors",
            "triggers",
            "impact_tags",
            "changed_paths",
            "changed_contracts",
            "unresolved_decisions",
        ):
            value = evidence[key]
            if not isinstance(value, list):
                errors.append(f"{path}.{key}: list required")
            else:
                for position, item in enumerate(value):
                    if not isinstance(item, str) or not item.strip():
                        errors.append(
                            f"{path}.{key}[{position}]: non-empty string required"
                        )
        for key in ("tests", "acceptance_evidence"):
            if not isinstance(evidence[key], list):
                errors.append(f"{path}.{key}: list required")
        document_hashes = evidence["document_hashes"]
        if not isinstance(document_hashes, dict):
            errors.append(f"{path}.document_hashes: mapping required")
        else:
            for doc_id, digest in document_hashes.items():
                if not isinstance(doc_id, str) or not doc_id.strip():
                    errors.append(
                        f"{path}.document_hashes: non-empty string keys required"
                    )
                if not isinstance(digest, str) or not digest.strip():
                    errors.append(
                        f"{path}.document_hashes[{doc_id!r}]: "
                        "non-empty string hash required"
                    )
        if (
            not isinstance(evidence["context_manifest_sha256"], str)
            or not evidence["context_manifest_sha256"].strip()
        ):
            errors.append(f"{path}.context_manifest_sha256: non-empty string required")
        if not isinstance(evidence["pr_url"], str):
            errors.append(f"{path}.pr_url: string required")
        owner_approval = evidence["owner_approval"]
        if not isinstance(owner_approval, dict):
            errors.append(f"{path}.owner_approval: mapping required")
            owner_approval = {}
        else:
            try:
                require_keys(
                    owner_approval,
                    {"approved", "reference"},
                    f"{path}.owner_approval",
                )
            except NavError as exc:
                errors.append(str(exc))
            if not isinstance(owner_approval.get("approved"), bool):
                errors.append(f"{path}.owner_approval.approved: boolean required")
            if not isinstance(owner_approval.get("reference"), str):
                errors.append(f"{path}.owner_approval.reference: string required")

        declared_tests = task["acceptance"]["tests"]
        test_entries = evidence["tests"] if isinstance(evidence["tests"], list) else []
        seen_tests: set[str] = set()
        for position, test in enumerate(test_entries):
            label = f"{path}.tests[{position}]"
            if not isinstance(test, dict):
                errors.append(f"{label}: mapping required")
                continue
            try:
                require_keys(test, {"requirement", "command", "exit_code"}, label)
            except NavError as exc:
                errors.append(str(exc))
                continue
            requirement = test["requirement"]
            if not isinstance(requirement, str) or not requirement:
                errors.append(f"{label}.requirement: non-empty string required")
                continue
            if requirement in seen_tests:
                errors.append(f"{label}: duplicate requirement {requirement!r}")
            seen_tests.add(requirement)
            if requirement not in declared_tests:
                errors.append(f"{label}: undeclared requirement {requirement!r}")
            if not isinstance(test["command"], str):
                errors.append(f"{label}.command: string required")
            exit_code = test["exit_code"]
            if exit_code is not None and (
                isinstance(exit_code, bool) or not isinstance(exit_code, int)
            ):
                errors.append(f"{label}.exit_code: integer or null required")

        declared_evidence = task["acceptance"]["evidence"]
        proof_entries = (
            evidence["acceptance_evidence"]
            if isinstance(evidence["acceptance_evidence"], list)
            else []
        )
        seen_proofs: set[str] = set()
        for position, proof in enumerate(proof_entries):
            label = f"{path}.acceptance_evidence[{position}]"
            if not isinstance(proof, dict):
                errors.append(f"{label}: mapping required")
                continue
            try:
                require_keys(proof, {"requirement", "proof"}, label)
            except NavError as exc:
                errors.append(str(exc))
                continue
            requirement = proof["requirement"]
            if not isinstance(requirement, str) or not requirement:
                errors.append(f"{label}.requirement: non-empty string required")
                continue
            if requirement in seen_proofs:
                errors.append(f"{label}: duplicate requirement {requirement!r}")
            seen_proofs.add(requirement)
            if requirement not in declared_evidence:
                errors.append(f"{label}: undeclared requirement {requirement!r}")
            if not isinstance(proof["proof"], str):
                errors.append(f"{label}.proof: string required")

        if task["state"] == "completed":
            if not isinstance(evidence["pr_url"], str) or not evidence["pr_url"].startswith(
                "https://github.com/"
            ):
                errors.append(f"{path}: completed evidence requires GitHub PR URL")
            if evidence["unresolved_decisions"]:
                errors.append(f"{path}: completed evidence has unresolved decisions")
            missing_tests = [
                requirement for requirement in declared_tests if requirement not in seen_tests
            ]
            for requirement in missing_tests:
                errors.append(
                    f"{path}: completed evidence is missing acceptance test {requirement!r}"
                )
            for position, test in enumerate(test_entries):
                if not isinstance(test, dict):
                    continue
                requirement = test.get("requirement")
                if requirement not in declared_tests:
                    continue
                if not isinstance(test.get("command"), str) or not test["command"]:
                    errors.append(
                        f"{path}.tests[{position}].command: completed evidence "
                        "requires a non-empty command"
                    )
                exit_code = test.get("exit_code")
                if isinstance(exit_code, bool) or exit_code != 0:
                    errors.append(
                        f"{path}.tests[{position}]: acceptance test did not exit with 0"
                    )
            missing_proofs = [
                requirement
                for requirement in declared_evidence
                if requirement not in seen_proofs
            ]
            for requirement in missing_proofs:
                errors.append(
                    f"{path}: completed evidence is missing proof for {requirement!r}"
                )
            for position, proof in enumerate(proof_entries):
                if not isinstance(proof, dict):
                    continue
                requirement = proof.get("requirement")
                if requirement not in declared_evidence:
                    continue
                if not isinstance(proof.get("proof"), str) or not proof["proof"]:
                    errors.append(
                        f"{path}.acceptance_evidence[{position}].proof: "
                        "completed evidence requires non-empty proof"
                    )
            owner_reference = owner_approval.get("reference")
            if task["approval"]["owner_required"] and (
                owner_approval.get("approved") is not True
                or not isinstance(owner_reference, str)
                or not owner_reference.strip()
            ):
                errors.append(
                    f"{path}: completed evidence requires explicit owner approval"
                )
    except NavError as exc:
        errors.append(str(exc))
    return errors


def validate_repository(
    root: Path,
) -> tuple[list[str], list[str], dict[str, dict[str, Any]], dict[str, Path]]:
    errors: list[str] = []
    warnings: list[str] = []
    index = spec_slice.load_index(root / "spec-index.json")
    spec_errors, spec_warnings, docs = spec_slice.validate_index(root, index)
    errors.extend(spec_errors)
    warnings.extend(spec_warnings)
    try:
        tasks, task_paths = load_tasks(root)
    except NavError as exc:
        return errors + [str(exc)], warnings, {}, {}
    for task_id, task in tasks.items():
        errors.extend(validate_task_shape(task, task_paths[task_id]))
    if errors:
        return errors, sorted(set(warnings)), tasks, task_paths

    governance_errors, decisions, artifacts = validate_governance(root, index, docs)
    errors.extend(governance_errors)
    errors.extend(ready_cardinality_errors(tasks))
    errors.extend(artifact_provider_errors(tasks, artifacts))
    errors.extend(task_dependency_cycles(tasks, artifacts))
    errors.extend(bootstrap_chain_errors(tasks))
    for task in tasks.values():
        task_errors, task_warnings = validate_task_semantics(
            task, tasks, index, docs, decisions, artifacts
        )
        errors.extend(task_errors)
        warnings.extend(task_warnings)
        errors.extend(validate_evidence(root, task))
    return sorted(set(errors)), sorted(set(warnings)), tasks, task_paths


def command_generate_lock(args: argparse.Namespace, root: Path) -> int:
    index = spec_slice.load_index(root / "spec-index.json")
    errors, warnings, docs = spec_slice.validate_index(root, index)
    if errors:
        raise NavError("spec validation failed:\n- " + "\n- ".join(errors))
    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    target = root / "governance" / "spec-lock.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        canonical_json(build_spec_lock(root, index, docs)),
        encoding="utf-8",
        newline="\n",
    )
    print(f"generated spec lock: {target}")
    return 0


def command_check_lock(args: argparse.Namespace, root: Path) -> int:
    index = spec_slice.load_index(root / "spec-index.json")
    errors, warnings, docs = spec_slice.validate_index(root, index)
    if errors:
        raise NavError("spec validation failed:\n- " + "\n- ".join(errors))
    lock_errors = check_spec_lock(root, index, docs)
    if lock_errors:
        raise NavError("\n- ".join(lock_errors))
    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    print("spec lock is current")
    return 0


def write_context_bundle(
    root: Path,
    task: dict[str, Any],
    task_path: Path,
    triggers: Sequence[str],
) -> tuple[Path, Path, dict[str, Any]]:
    index = spec_slice.load_index(root / "spec-index.json")
    errors, _, docs = spec_slice.validate_index(root, index)
    if errors:
        raise NavError("spec validation failed:\n- " + "\n- ".join(errors))
    context, manifest = build_context_bundle(root, task, task_path, index, docs, triggers)
    target = root / ".nabla" / "context" / task["task_id"]
    target.mkdir(parents=True, exist_ok=True)
    context_path = target / "context.md"
    manifest_path = target / "manifest.json"
    context_path.write_text(context, encoding="utf-8", newline="\n")
    manifest_path.write_text(canonical_json(manifest), encoding="utf-8", newline="\n")
    return context_path, manifest_path, manifest


def command_validate(args: argparse.Namespace, root: Path) -> int:
    errors, warnings, tasks, _ = validate_repository(root)
    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if errors:
        print(
            f"validation failed: {len(errors)} error(s), {len(warnings)} warning(s)",
            file=sys.stderr,
        )
        return 1
    print(f"validation passed: {len(tasks)} task card(s), {len(warnings)} warning(s)")
    return 0


def command_list_ready(args: argparse.Namespace, root: Path) -> int:
    errors, warnings, tasks, _ = validate_repository(root)
    if errors:
        raise NavError("repository validation failed:\n- " + "\n- ".join(errors))
    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    ready = [task for task in tasks.values() if task["state"] == "ready"]
    for task in sorted(ready, key=lambda item: item["task_id"]):
        print(f"{task['task_id']}\t{task['type']}\t{task['outcome']}")
    return 0


def command_prepare(args: argparse.Namespace, root: Path) -> int:
    errors, warnings, tasks, task_paths = validate_repository(root)
    if errors:
        raise NavError("repository validation failed:\n- " + "\n- ".join(errors))
    if args.task_id not in tasks:
        raise NavError(f"unknown task id: {args.task_id}")
    task = tasks[args.task_id]
    if task["state"] not in {"ready", "completed"}:
        raise NavError(f"{args.task_id}: task state is {task['state']}, not ready")
    context_path, manifest_path, manifest = write_context_bundle(
        root, task, task_paths[args.task_id], args.trigger
    )
    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    print(f"context: {context_path}")
    print(f"manifest: {manifest_path}")
    print(
        f"manifest_sha256: {manifest['manifest_sha256']}; "
        f"words: {manifest['context_words']}/16000"
    )
    return 0


def evidence_template(root: Path, task: dict[str, Any]) -> dict[str, Any]:
    task_id = task["task_id"]
    manifest_path = root / ".nabla" / "context" / task_id / "manifest.json"
    if not manifest_path.exists():
        raise NavError(f"{task_id}: run prepare before creating evidence")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "task_id": task_id,
        "context_manifest_sha256": manifest["manifest_sha256"],
        "selectors": manifest["selectors"],
        "document_hashes": {
            doc_id: entry["sha256"] for doc_id, entry in manifest["documents"].items()
        },
        "impact_tags": manifest["impact_tags"],
        "triggers": manifest["triggers"],
        "changed_paths": [],
        "changed_contracts": [],
        "tests": [
            {"requirement": requirement, "command": "", "exit_code": None}
            for requirement in task["acceptance"]["tests"]
        ],
        "acceptance_evidence": [
            {"requirement": requirement, "proof": ""}
            for requirement in task["acceptance"]["evidence"]
        ],
        "owner_approval": {"approved": False, "reference": ""},
        "unresolved_decisions": [],
        "pr_url": "",
    }


def command_evidence(args: argparse.Namespace, root: Path) -> int:
    tasks, _ = load_tasks(root)
    if args.task_id not in tasks:
        raise NavError(f"unknown task id: {args.task_id}")
    path = root / "roadmap" / "evidence" / f"{args.task_id}.yaml"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(
                evidence_template(root, tasks[args.task_id]),
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
            newline="\n",
        )
        print(f"created evidence template: {path}")
        return 0
    errors = validate_evidence(root, tasks[args.task_id])
    if errors:
        raise NavError("evidence validation failed:\n- " + "\n- ".join(errors))
    print(f"evidence valid: {path}")
    return 0


def match_any(path: str, patterns: Sequence[str]) -> bool:
    normalized = path.replace("\\", "/")
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in patterns)


def validate_changed_paths(task: dict[str, Any], changed_paths: Sequence[str]) -> list[str]:
    errors: list[str] = []
    include = task["scope"]["paths"]["include"]
    exclude = task["scope"]["paths"]["exclude"]
    for path in changed_paths:
        normalized = path.replace("\\", "/")
        if not match_any(normalized, include):
            errors.append(f"{task['task_id']}: changed path is outside scope: {normalized}")
        if match_any(normalized, exclude):
            errors.append(f"{task['task_id']}: changed path matches exclusion: {normalized}")
    normative = {
        "CONSTITUTION.md",
        "ARCHITECTURE.md",
        "DATA-CLASSIFICATION.md",
        "CAPABILITY-CONTRACT.md",
        "MODULE-MANIFEST.md",
        "LOOP-SPEC.md",
        "KNOWLEDGE-MODULE.md",
        "DOCUMENT-MODULE.md",
        "BACKUP-RECOVERY.md",
    }
    changed_normative = normative.intersection(path.replace("\\", "/") for path in changed_paths)
    if changed_normative and task["type"] not in {"spec", "adr"}:
        errors.append(
            f"{task['task_id']}: normative files require spec/adr task: "
            + ", ".join(sorted(changed_normative))
        )
    production_prefixes = ("src/", "app/", "core/")
    if task["type"] in {"spec", "adr"} and any(
        path.replace("\\", "/").startswith(production_prefixes) for path in changed_paths
    ):
        errors.append(f"{task['task_id']}: spec/adr task cannot change production code")
    return errors


def task_id_from_pr_title(title: str) -> str:
    match = PR_TITLE_RE.match(title.strip())
    if not match:
        raise NavError("PR title must start with [TASK-ID] followed by an outcome")
    return match.group(1)


def validate_pr_evidence(
    root: Path,
    task: dict[str, Any],
    task_path: Path,
    changed_paths: Sequence[str],
    pr_url: str,
) -> list[str]:
    errors: list[str] = []
    evidence_path = root / "roadmap" / "evidence" / f"{task['task_id']}.yaml"
    if not evidence_path.exists():
        return [f"{task['task_id']}: PR requires evidence file {evidence_path}"]
    evidence = read_yaml(evidence_path)
    errors.extend(validate_evidence(root, task))
    if errors:
        return errors
    index = spec_slice.load_index(root / "spec-index.json")
    spec_errors, _, docs = spec_slice.validate_index(root, index)
    if spec_errors:
        return ["spec validation failed before PR evidence check"]
    try:
        _, manifest = build_context_bundle(
            root,
            task,
            task_path,
            index,
            docs,
            evidence["triggers"],
        )
    except (NavError, spec_slice.SpecError, OSError) as exc:
        return [str(exc)]
    if evidence["context_manifest_sha256"] != manifest["manifest_sha256"]:
        errors.append(
            f"{task['task_id']}: evidence context manifest is stale; "
            "run prepare and update evidence"
        )
    expected_document_hashes = {
        doc_id: entry["sha256"] for doc_id, entry in manifest["documents"].items()
    }
    for field, expected in (
        ("selectors", manifest["selectors"]),
        ("document_hashes", expected_document_hashes),
        ("impact_tags", manifest["impact_tags"]),
        ("triggers", manifest["triggers"]),
    ):
        if evidence[field] != expected:
            errors.append(
                f"{task['task_id']}: evidence {field} does not match context manifest"
            )
    normalized_changed = sorted(path.replace("\\", "/") for path in changed_paths)
    evidence_changed = sorted(path.replace("\\", "/") for path in evidence["changed_paths"])
    if evidence_changed != normalized_changed:
        errors.append(f"{task['task_id']}: evidence changed_paths does not match PR diff")
    if evidence["pr_url"] != pr_url:
        errors.append(f"{task['task_id']}: evidence pr_url does not match current PR")
    return errors


def git_changed_paths(root: Path, base: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise NavError(f"git diff failed: {result.stderr.strip()}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def command_check_scope(args: argparse.Namespace, root: Path) -> int:
    tasks, _ = load_tasks(root)
    if args.task_id not in tasks:
        raise NavError(f"unknown task id: {args.task_id}")
    changed = args.path or git_changed_paths(root, args.base)
    errors = validate_changed_paths(tasks[args.task_id], changed)
    if errors:
        raise NavError("scope validation failed:\n- " + "\n- ".join(errors))
    print(f"scope valid: {args.task_id}; {len(changed)} changed path(s)")
    return 0


def command_ci_pr(args: argparse.Namespace, root: Path) -> int:
    task_id = task_id_from_pr_title(args.title)
    errors, warnings, tasks, task_paths = validate_repository(root)
    if errors:
        raise NavError("repository validation failed:\n- " + "\n- ".join(errors))
    if task_id not in tasks:
        raise NavError(f"PR references unknown task id: {task_id}")
    task = tasks[task_id]
    if task["state"] != "completed":
        raise NavError(f"{task_id}: PR task card must set state to completed")
    expected_prefix = f"task/{task_id}-"
    if not args.branch.startswith(expected_prefix):
        raise NavError(
            f"{task_id}: branch must start with {expected_prefix!r}, got {args.branch!r}"
        )
    changed = git_changed_paths(root, args.base)
    pr_errors = validate_changed_paths(task, changed)
    pr_errors.extend(
        validate_pr_evidence(
            root,
            task,
            task_paths[task_id],
            changed,
            args.pr_url,
        )
    )
    if pr_errors:
        raise NavError("PR gate failed:\n- " + "\n- ".join(pr_errors))
    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    print(f"PR gate passed: {task_id}; {len(changed)} changed path(s)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=repository_root(),
        help="repository root",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate", help="validate specifications, task cards and evidence")
    subparsers.add_parser("generate-lock", help="regenerate living spec lock")
    subparsers.add_parser("check-lock", help="verify living spec lock is current")
    subparsers.add_parser("list-ready", help="list ready task cards")
    prepare = subparsers.add_parser("prepare", help="prepare exact context for one task")
    prepare.add_argument("task_id")
    prepare.add_argument("--trigger", action="append", default=[])
    evidence = subparsers.add_parser("evidence", help="create or validate task evidence")
    evidence.add_argument("task_id")
    scope = subparsers.add_parser("check-scope", help="validate changed paths against task scope")
    scope.add_argument("task_id")
    scope.add_argument("--base", default="origin/main")
    scope.add_argument("--path", action="append", default=[])
    ci_pr = subparsers.add_parser("ci-pr", help="validate one pull request gate")
    ci_pr.add_argument("--title", required=True)
    ci_pr.add_argument("--base", required=True)
    ci_pr.add_argument("--branch", required=True)
    ci_pr.add_argument("--pr-url", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    spec_slice.configure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "validate":
            return command_validate(args, root)
        if args.command == "generate-lock":
            return command_generate_lock(args, root)
        if args.command == "check-lock":
            return command_check_lock(args, root)
        if args.command == "list-ready":
            return command_list_ready(args, root)
        if args.command == "prepare":
            return command_prepare(args, root)
        if args.command == "evidence":
            return command_evidence(args, root)
        if args.command == "check-scope":
            return command_check_scope(args, root)
        if args.command == "ci-pr":
            return command_ci_pr(args, root)
        raise NavError(f"unsupported command: {args.command}")
    except (NavError, spec_slice.SpecError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
