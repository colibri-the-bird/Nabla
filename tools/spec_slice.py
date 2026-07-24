#!/usr/bin/env python3
"""Validate and slice Nabla Markdown specifications by stable section selectors.

The tool is intentionally standard-library only. It reads repository files,
never executes Markdown, never accesses the network, and writes slices to stdout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
SECTION_KEY_RE = re.compile(r"^(?:(I\d+)|(\d+(?:\.\d+)*))(?:\.|\s|$)")
STATUS_RE = re.compile(r"^\*\*Статус:\*\*\s*(.+?)\s{0,2}$", re.MULTILINE)
VERSION_RE = re.compile(r"^\*\*Версия:\*\*\s*`?([^`\s]+)", re.MULTILINE)
TITLE_VERSION_RE = re.compile(r"^#\s+.+?\bv(\d+(?:\.\d+)+)\s*$", re.MULTILINE)
WORD_RE = re.compile(r"\b[\wА-Яа-яЁё-]+\b", re.UNICODE)
DOC_REF_RE = re.compile(r"`([A-Z][A-Z0-9-]+\.md)`")


class SpecError(RuntimeError):
    pass


@dataclass(frozen=True)
class Heading:
    key: str
    title: str
    level: int
    start: int
    end: int


@dataclass
class ParsedDocument:
    doc_id: str
    path: Path
    text: str
    lines: list[str]
    headings: dict[str, Heading]
    heading_order: list[Heading]
    meta_end: int
    sha256: str
    status: str | None
    version: str | None

    def slice_for(self, key: str) -> tuple[int, int]:
        if key == "meta":
            return (0, self.meta_end)
        if key == "full":
            return (0, len(self.lines))
        try:
            heading = self.headings[key]
        except KeyError as exc:
            raise SpecError(f"{self.doc_id}:{key}: selector does not resolve") from exc
        return (heading.start, heading.end)


def word_count(text: str) -> int:
    return len(WORD_RE.findall(text))


def load_index(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SpecError(f"cannot read index {path}: {exc}") from exc
    if data.get("schema_version") != 1:
        raise SpecError("unsupported spec-index schema_version")
    return data


def safe_resolve(root: Path, relative: str) -> Path | None:
    candidate = root / relative
    if not candidate.exists():
        return None
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise SpecError(f"path escapes project root: {relative}")
    if candidate.is_symlink():
        raise SpecError(f"symlink specification path is not allowed: {relative}")
    if not candidate.is_file():
        raise SpecError(f"specification path is not a regular file: {relative}")
    return candidate


def resolve_document_path(root: Path, entry: dict) -> Path | None:
    candidates = [entry["canonical_path"], *entry.get("aliases", [])]
    found: list[Path] = []
    for relative in candidates:
        path = safe_resolve(root, relative)
        if path is not None:
            found.append(path)
    if len(found) > 1:
        canonical = root / entry["canonical_path"]
        if canonical in found:
            return canonical
        raise SpecError(
            f"{entry['id']}: multiple aliases exist without canonical path: "
            + ", ".join(str(p) for p in found)
        )
    return found[0] if found else None


def parse_heading_key(title: str) -> str | None:
    match = SECTION_KEY_RE.match(title.strip())
    if not match:
        return None
    return match.group(1) or match.group(2)


def parse_document(doc_id: str, path: Path) -> ParsedDocument:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SpecError(f"{doc_id}: not valid UTF-8: {path}") from exc
    lines = text.splitlines(keepends=True)
    provisional: list[tuple[str, str, int, int]] = []
    in_fence = False
    fence_marker: str | None = None
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
                fence_marker = None
            continue
        if in_fence:
            continue
        match = HEADING_RE.match(line.rstrip("\r\n"))
        if not match:
            continue
        level = len(match.group(1))
        title = match.group(2).strip()
        key = parse_heading_key(title)
        if key is not None:
            provisional.append((key, title, level, index))
    if in_fence:
        raise SpecError(f"{doc_id}: unclosed fenced code block")

    headings: dict[str, Heading] = {}
    heading_order: list[Heading] = []
    for position, (key, title, level, start) in enumerate(provisional):
        end = len(lines)
        for _, _, following_level, following_start in provisional[position + 1 :]:
            if following_level <= level:
                end = following_start
                break
        if key in headings:
            previous = headings[key]
            raise SpecError(
                f"{doc_id}: duplicate section key {key} at lines "
                f"{previous.start + 1} and {start + 1}"
            )
        heading = Heading(key, title, level, start, end)
        headings[key] = heading
        heading_order.append(heading)

    meta_end = provisional[0][3] if provisional else len(lines)
    status_match = STATUS_RE.search(text[: min(len(text), 5000)])
    version_match = VERSION_RE.search(text[: min(len(text), 5000)])
    title_version_match = TITLE_VERSION_RE.search(text[: min(len(text), 1000)])
    return ParsedDocument(
        doc_id=doc_id,
        path=path,
        text=text,
        lines=lines,
        headings=headings,
        heading_order=heading_order,
        meta_end=meta_end,
        sha256=hashlib.sha256(raw).hexdigest(),
        status=status_match.group(1).strip() if status_match else None,
        version=(
            version_match.group(1).strip()
            if version_match
            else (title_version_match.group(1).strip() if title_version_match else None)
        ),
    )


def document_entries(index: dict) -> dict[str, dict]:
    entries: dict[str, dict] = {}
    for entry in index.get("documents", []):
        doc_id = entry.get("id")
        if not doc_id or doc_id in entries:
            raise SpecError(f"duplicate or missing document id: {doc_id!r}")
        entries[doc_id] = entry
    return entries


def load_documents(root: Path, index: dict, include_planned: bool = False) -> dict[str, ParsedDocument]:
    result: dict[str, ParsedDocument] = {}
    for doc_id, entry in document_entries(index).items():
        path = resolve_document_path(root, entry)
        if path is None:
            if entry.get("planned") and not include_planned:
                continue
            raise SpecError(f"{doc_id}: missing canonical file {entry['canonical_path']}")
        result[doc_id] = parse_document(doc_id, path)
    return result


def parse_selector(selector: str) -> tuple[str, str]:
    if ":" not in selector:
        raise SpecError(f"invalid selector {selector!r}; expected DOC:section")
    doc_id, key = selector.split(":", 1)
    doc_id = doc_id.strip()
    key = key.strip()
    if not doc_id or not key:
        raise SpecError(f"invalid selector {selector!r}")
    if key.endswith("+children"):
        key = key[: -len("+children")]
    return doc_id, key


def validate_selector(selector: str, docs: dict[str, ParsedDocument], entries: dict[str, dict]) -> None:
    doc_id, key = parse_selector(selector)
    if doc_id not in entries:
        raise SpecError(f"{selector}: unknown document id")
    if doc_id not in docs:
        state = "planned" if entries[doc_id].get("planned") else "missing"
        raise SpecError(f"{selector}: document is {state}, selector cannot be active")
    docs[doc_id].slice_for(key)


def pipe_count_outside_code(line: str) -> int:
    count = 0
    in_code = False
    backtick_run = 0
    i = 0
    while i < len(line):
        char = line[i]
        if char == "\\" and i + 1 < len(line):
            i += 2
            continue
        if char == "`":
            run = 1
            while i + run < len(line) and line[i + run] == "`":
                run += 1
            if not in_code:
                in_code = True
                backtick_run = run
            elif run == backtick_run:
                in_code = False
                backtick_run = 0
            i += run
            continue
        if char == "|" and not in_code:
            count += 1
        i += 1
    return count


def validate_markdown_tables(doc: ParsedDocument) -> list[str]:
    errors: list[str] = []
    block: list[tuple[int, str, int]] = []

    def finish() -> None:
        nonlocal block
        if len(block) >= 2:
            expected = block[0][2]
            separator_like = bool(re.match(r"^\s*\|?\s*:?-{3,}", block[1][1]))
            if separator_like:
                for line_no, line, count in block[1:]:
                    if count != expected:
                        errors.append(
                            f"{doc.doc_id}: malformed Markdown table at line {line_no}: "
                            f"expected {expected} pipes, found {count}"
                        )
        block = []

    in_fence = False
    for line_no, line in enumerate(doc.lines, start=1):
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            finish()
            continue
        is_table_row = not in_fence and stripped.startswith("|") and stripped.endswith("|")
        if is_table_row:
            block.append((line_no, line, pipe_count_outside_code(line)))
        else:
            finish()
    finish()
    return errors


def dependency_cycles(entries: dict[str, dict]) -> list[str]:
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []
    errors: list[str] = []

    def visit(node: str) -> None:
        if node in visited:
            return
        if node in visiting:
            start = stack.index(node)
            errors.append("dependency cycle: " + " -> ".join(stack[start:] + [node]))
            return
        visiting.add(node)
        stack.append(node)
        for dependency in entries[node].get("depends_on", []):
            if dependency not in entries:
                errors.append(f"{node}: unknown dependency {dependency}")
            else:
                visit(dependency)
        stack.pop()
        visiting.remove(node)
        visited.add(node)

    for doc_id in entries:
        visit(doc_id)
    return errors


def validate_index(root: Path, index: dict) -> tuple[list[str], list[str], dict[str, ParsedDocument]]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        entries = document_entries(index)
        docs = load_documents(root, index)
    except SpecError as exc:
        return [str(exc)], warnings, {}

    errors.extend(dependency_cycles(entries))
    for doc_id, doc in docs.items():
        entry = entries[doc_id]
        expected_version = entry.get("version")
        if expected_version and doc.version and not doc.version.startswith(expected_version):
            errors.append(
                f"{doc_id}: index version {expected_version} differs from file version {doc.version}"
            )
        errors.extend(validate_markdown_tables(doc))
        canonical_names = {item["canonical_path"] for item in entries.values()}
        aliases = {alias for item in entries.values() for alias in item.get("aliases", [])}
        historical = set(index.get("known_external_references", []))
        for ref in DOC_REF_RE.findall(doc.text):
            if ref not in canonical_names and ref not in aliases and ref not in historical:
                warnings.append(f"{doc_id}: unresolved/unindexed document reference {ref}")

    for tag, selectors in index.get("impact_tags", {}).items():
        if not isinstance(selectors, list) or not selectors:
            errors.append(f"impact tag {tag}: selectors must be a non-empty list")
            continue
        for selector in selectors:
            try:
                validate_selector(selector, docs, entries)
            except SpecError as exc:
                errors.append(f"impact tag {tag}: {exc}")

    for pack_id, pack in index.get("context_packs", {}).items():
        if not isinstance(pack.get("version"), int):
            errors.append(f"context pack {pack_id}: integer version required")
        for tag in pack.get("tags", []):
            if tag not in index.get("impact_tags", {}):
                errors.append(f"context pack {pack_id}: unknown impact tag {tag}")
        for selector in pack.get("selectors", []):
            try:
                validate_selector(selector, docs, entries)
            except SpecError as exc:
                errors.append(f"context pack {pack_id}: {exc}")
    return errors, sorted(set(warnings)), docs


def expand_context(index: dict, pack_ids: Sequence[str], tags: Sequence[str], selectors: Sequence[str]) -> list[str]:
    expanded: list[str] = list(selectors)
    all_tags: list[str] = list(tags)
    packs = index.get("context_packs", {})
    for pack_id in pack_ids:
        if pack_id not in packs:
            raise SpecError(f"unknown context pack: {pack_id}")
        pack = packs[pack_id]
        expanded.extend(pack.get("selectors", []))
        all_tags.extend(pack.get("tags", []))
    tag_map = index.get("impact_tags", {})
    for tag in all_tags:
        if tag not in tag_map:
            raise SpecError(f"unknown impact tag: {tag}")
        expanded.extend(tag_map[tag])
    seen: set[str] = set()
    unique: list[str] = []
    for selector in expanded:
        doc_id, key = parse_selector(selector)
        normalized = f"{doc_id}:{key}"
        if normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)
    return unique


def merge_ranges(ranges: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def build_slice(
    docs: dict[str, ParsedDocument],
    entries: dict[str, dict],
    selectors: Sequence[str],
    requested_selectors: Sequence[str] = (),
    packs: Sequence[str] = (),
    tags: Sequence[str] = (),
) -> str:
    by_doc: dict[str, list[str]] = {}
    for selector in selectors:
        doc_id, key = parse_selector(selector)
        validate_selector(selector, docs, entries)
        by_doc.setdefault(doc_id, []).append(key)

    chunks: list[str] = []
    total_words = 0
    for doc_id in entries:
        if doc_id not in by_doc:
            continue
        doc = docs[doc_id]
        keys = by_doc[doc_id]
        ranges = [doc.slice_for(key) for key in keys]
        if "full" not in keys and "meta" not in keys:
            ranges.append(doc.slice_for("meta"))
        merged = merge_ranges(ranges)
        body = "".join("".join(doc.lines[start:end]) for start, end in merged)
        words = word_count(body)
        total_words += words
        relative = entries[doc_id]["canonical_path"]
        chunks.append(
            "\n<!-- NABLA-SPEC-SOURCE\n"
            f"document_id: {doc_id}\n"
            f"canonical_path: {relative}\n"
            f"resolved_path: {doc.path.name}\n"
            f"version: {doc.version or entries[doc_id].get('version') or 'unknown'}\n"
            f"status: {doc.status or 'unknown'}\n"
            f"sha256: {doc.sha256}\n"
            f"selectors: {', '.join(f'{doc_id}:{key}' for key in keys)}\n"
            f"slice_words: {words}\n"
            "-->\n\n"
            + body.rstrip()
            + "\n"
        )
    header = (
        "<!-- Generated by tools/spec_slice.py; do not treat this slice as a "
        "source independent of the referenced specifications. -->\n"
        f"<!-- requested_selectors: {', '.join(requested_selectors) or 'none'} -->\n"
        f"<!-- context_packs: {', '.join(packs) or 'none'}; "
        f"impact_tags: {', '.join(tags) or 'none'} -->\n"
        f"<!-- expanded_selectors: {', '.join(selectors)}; total_words: {total_words} -->\n"
    )
    return header + "".join(chunks)


def command_validate(args: argparse.Namespace, root: Path, index: dict) -> int:
    errors, warnings, docs = validate_index(root, index)
    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if errors:
        print(f"validation failed: {len(errors)} error(s), {len(warnings)} warning(s)", file=sys.stderr)
        return 1
    sections = sum(len(doc.headings) for doc in docs.values())
    words = sum(word_count(doc.text) for doc in docs.values())
    print(
        f"validation passed: {len(docs)} document(s), {sections} section(s), "
        f"{words} word(s), {len(warnings)} warning(s)"
    )
    return 0


def command_list_docs(args: argparse.Namespace, root: Path, index: dict) -> int:
    entries = document_entries(index)
    for doc_id, entry in entries.items():
        path = resolve_document_path(root, entry)
        state = "planned" if entry.get("planned") else (path.name if path else "missing")
        print(f"{doc_id}\t{entry['canonical_path']}\t{state}")
    return 0


def command_list_sections(args: argparse.Namespace, root: Path, index: dict) -> int:
    entries = document_entries(index)
    if args.document not in entries:
        raise SpecError(f"unknown document id: {args.document}")
    path = resolve_document_path(root, entries[args.document])
    if path is None:
        raise SpecError(f"{args.document}: file is missing/planned")
    doc = parse_document(args.document, path)
    print(f"{args.document}:meta\tmetadata/preamble")
    for heading in doc.heading_order:
        print(f"{args.document}:{heading.key}\t{'  ' * (heading.level - 1)}{heading.title}")
    return 0


def command_slice(args: argparse.Namespace, root: Path, index: dict) -> int:
    errors, warnings, docs = validate_index(root, index)
    if errors:
        raise SpecError("index validation failed before slice:\n- " + "\n- ".join(errors))
    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    selectors = expand_context(index, args.pack, args.tag, args.selector)
    if not selectors:
        raise SpecError("slice requires at least one selector, tag or pack")
    selected_doc_ids = {parse_selector(selector)[0] for selector in selectors}
    for doc_id in sorted(selected_doc_ids):
        status = (docs[doc_id].status or "unknown").lower()
        approved = (
            ("утвержден" in status or "утверждён" in status or "approved" in status)
            and "к утвержд" not in status
            and "draft" not in status
            and not status.startswith("проект")
        )
        if not approved:
            print(
                f"WARNING: {doc_id} status is {docs[doc_id].status or 'unknown'}; "
                "slice contains draft requirements",
                file=sys.stderr,
            )
    content = build_slice(
        docs,
        document_entries(index),
        selectors,
        requested_selectors=args.selector,
        packs=args.pack,
        tags=args.tag,
    )
    words = word_count(content)
    if words > args.max_words:
        message = f"slice has {words} words; budget is {args.max_words}"
        if args.fail_over_budget:
            raise SpecError(message)
        print(f"WARNING: {message}", file=sys.stderr)
    else:
        print(f"slice words: {words}/{args.max_words}", file=sys.stderr)
    sys.stdout.write(content)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--index",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "spec-index.json",
        help="path to spec-index.json",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="specification root; defaults to index parent",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("validate", help="validate files, selectors, packs and Markdown structure")
    subparsers.add_parser("list-docs", help="list document ids and resolved paths")
    sections = subparsers.add_parser("list-sections", help="list stable selectors for one document")
    sections.add_argument("document")

    slice_parser = subparsers.add_parser("slice", help="write exact selected normative sections to stdout")
    slice_parser.add_argument("--selector", action="append", default=[], help="DOC:section selector")
    slice_parser.add_argument("--tag", action="append", default=[], help="impact tag")
    slice_parser.add_argument("--pack", action="append", default=[], help="context pack id")
    slice_parser.add_argument("--max-words", type=int, default=16000)
    slice_parser.add_argument("--fail-over-budget", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    index_path = args.index.resolve()
    root = (args.root.resolve() if args.root else index_path.parent.resolve())
    try:
        index = load_index(index_path)
        if args.command == "validate":
            return command_validate(args, root, index)
        if args.command == "list-docs":
            return command_list_docs(args, root, index)
        if args.command == "list-sections":
            return command_list_sections(args, root, index)
        if args.command == "slice":
            return command_slice(args, root, index)
        raise SpecError(f"unsupported command: {args.command}")
    except SpecError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
