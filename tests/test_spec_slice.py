from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import spec_slice  # noqa: E402


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def base_index(*documents: dict) -> dict:
    return {
        "schema_version": 1,
        "generated_policy": "test",
        "documents": list(documents),
        "impact_tags": {},
        "context_packs": {},
    }


def document(
    doc_id: str,
    path: str,
    *,
    aliases: list[str] | None = None,
    depends_on: list[str] | None = None,
    planned: bool = False,
) -> dict:
    return {
        "id": doc_id,
        "canonical_path": path,
        "aliases": aliases or [],
        "authority_rank": 1,
        "version": "0.1",
        "depends_on": depends_on or [],
        "planned": planned,
    }


def test_selector_includes_children_and_ignores_fenced_headings(tmp_path: Path) -> None:
    path = tmp_path / "DOC.md"
    write_text(
        path,
        """# Document v0.1

**Статус:** утверждён

# 1. Parent
parent

## 1.1 Child
child

```markdown
# 9. Not a section
```

# 2. Next
next
""",
    )
    parsed = spec_slice.parse_document("DOC", path)

    start, end = parsed.slice_for("1")
    selected = "".join(parsed.lines[start:end])

    assert "# 1. Parent" in selected
    assert "## 1.1 Child" in selected
    assert "# 2. Next" not in selected
    assert "9" not in parsed.headings


def test_duplicate_section_key_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "DOC.md"
    write_text(path, "# Document v0.1\n# 1. First\n# 1. Duplicate\n")

    with pytest.raises(spec_slice.SpecError, match="duplicate section key 1"):
        spec_slice.parse_document("DOC", path)


def test_unclosed_fence_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "DOC.md"
    write_text(path, "# Document v0.1\n# 1. First\n```text\nunterminated\n")

    with pytest.raises(spec_slice.SpecError, match="unclosed fenced code block"):
        spec_slice.parse_document("DOC", path)


def test_canonical_path_wins_over_alias(tmp_path: Path) -> None:
    write_text(tmp_path / "DOC.md", "# Canonical v0.1\n# 1. Canonical\n")
    write_text(tmp_path / "OLD.md", "# Alias v0.1\n# 1. Alias\n")
    entry = document("DOC", "DOC.md", aliases=["OLD.md"])

    resolved = spec_slice.resolve_document_path(tmp_path, entry)

    assert resolved == tmp_path / "DOC.md"


def test_planned_document_may_be_absent(tmp_path: Path) -> None:
    write_text(tmp_path / "DOC.md", "# Document v0.1\n# 1. Present\n")
    index = base_index(
        document("DOC", "DOC.md"),
        document("FUTURE", "FUTURE.md", planned=True),
    )

    errors, warnings, docs = spec_slice.validate_index(tmp_path, index)

    assert errors == []
    assert warnings == []
    assert set(docs) == {"DOC"}


def test_dependency_cycle_is_rejected(tmp_path: Path) -> None:
    write_text(tmp_path / "A.md", "# A v0.1\n# 1. A\n")
    write_text(tmp_path / "B.md", "# B v0.1\n# 1. B\n")
    index = base_index(
        document("A", "A.md", depends_on=["B"]),
        document("B", "B.md", depends_on=["A"]),
    )

    errors, _, _ = spec_slice.validate_index(tmp_path, index)

    assert any("dependency cycle: A -> B -> A" in error for error in errors)


def test_path_escape_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.md"
    write_text(outside, "# Outside v0.1\n# 1. Outside\n")

    with pytest.raises(spec_slice.SpecError, match="path escapes project root"):
        spec_slice.safe_resolve(tmp_path, f"../{outside.name}")


def test_malformed_markdown_table_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "DOC.md"
    write_text(
        path,
        """# Document v0.1
# 1. Table
| A | B |
|---|---|
| one |
""",
    )
    parsed = spec_slice.parse_document("DOC", path)

    errors = spec_slice.validate_markdown_tables(parsed)

    assert len(errors) == 1
    assert "malformed Markdown table" in errors[0]


def test_cli_is_utf8_safe_when_parent_requests_cp1251() -> None:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "cp1251"
    env["PYTHONUTF8"] = "0"
    result = subprocess.run(
        [
            sys.executable,
            str(TOOLS / "spec_slice.py"),
            "slice",
            "--selector",
            "NAV:0",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        check=False,
    )

    stdout = result.stdout.decode("utf-8")
    stderr = result.stderr.decode("utf-8")
    assert result.returncode == 0, stderr
    assert "Назначение" in stdout
    assert "slice words:" in stderr


def test_cli_slice_is_byte_deterministic() -> None:
    command = [
        sys.executable,
        str(TOOLS / "spec_slice.py"),
        "slice",
        "--pack",
        "spec-authoring",
    ]
    first = subprocess.run(command, cwd=ROOT, capture_output=True, check=True)
    second = subprocess.run(command, cwd=ROOT, capture_output=True, check=True)

    assert first.stdout == second.stdout
    assert first.stderr == second.stderr


def test_repository_index_is_valid_json() -> None:
    index = json.loads((ROOT / "spec-index.json").read_text(encoding="utf-8"))

    assert index["schema_version"] == 1


def test_all_context_packs_fit_hard_budget_and_known_large_packs_warn() -> None:
    index = spec_slice.load_index(ROOT / "spec-index.json")
    errors, _, docs = spec_slice.validate_index(ROOT, index)
    assert errors == []
    entries = spec_slice.document_entries(index)
    pack_words: dict[str, int] = {}

    for pack_id, pack in index["context_packs"].items():
        selectors = spec_slice.expand_context(index, [pack_id], [], [])
        content = spec_slice.build_slice(
            docs,
            entries,
            selectors,
            requested_selectors=(),
            packs=[pack_id],
            tags=pack.get("tags", []),
        )
        pack_words[pack_id] = spec_slice.word_count(content)

    assert all(words <= 16000 for words in pack_words.values())
    assert {
        pack_id for pack_id, words in pack_words.items() if words > 12000
    } == {"knowledge-note-core", "knowledge-import"}
