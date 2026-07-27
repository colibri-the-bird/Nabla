"""Test-only helpers for SPIKE-BACKUP-RESTORE-001.

This module intentionally models a small experimental bundle. It is not a
production backup, restore, retention, purge, encryption, or migration API.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path, PurePosixPath
from typing import Any, Callable


FORMAT_ID = "nabla.backup-restore-spike.bundle"
FORMAT_VERSION = 1
COMPLETE_NAME = "COMPLETE.json"
INCOMPLETE_NAME = "INCOMPLETE.json"


class SpikeError(RuntimeError):
    """Typed expected failure used by the measurement harness."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise SpikeError("INVALID_JSON_OBJECT", path.name)
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def deterministic_bytes(seed: str, size: int) -> bytes:
    if size < 0:
        raise ValueError("size must be non-negative")
    output = bytearray()
    counter = 0
    while len(output) < size:
        output.extend(
            hashlib.sha256(f"{seed}:{counter}".encode("utf-8")).digest()
        )
        counter += 1
    return bytes(output[:size])


def blob_relative_path(blob_hash: str) -> str:
    return f"blobs/sha256/{blob_hash[:2]}/{blob_hash}"


def _checked_relative(value: str) -> PurePosixPath:
    relative = PurePosixPath(value)
    if relative.is_absolute() or not relative.parts:
        raise SpikeError("UNSAFE_MEMBER_PATH", value)
    if any(part in {"", ".", ".."} for part in relative.parts):
        raise SpikeError("UNSAFE_MEMBER_PATH", value)
    if "\\" in value or ":" in value:
        raise SpikeError("UNSAFE_MEMBER_PATH", value)
    return relative


def _local_member(root: Path, value: str) -> Path:
    relative = _checked_relative(value)
    candidate = root.joinpath(*relative.parts)
    if candidate.is_symlink():
        raise SpikeError("SYMLINK_MEMBER", value)
    return candidate


def _connect_rw(path: Path, busy_timeout_ms: int = 5000) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=busy_timeout_ms / 1000)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    return connection


def _connect_ro(
    path: Path,
    *,
    immutable: bool = False,
) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro"
    if immutable:
        uri += "&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _fixture_blob_map(
    fixture: dict[str, Any],
    blob_root: Path,
) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for declaration in fixture["blobs"]:
        content = deterministic_bytes(
            str(declaration["seed"]),
            int(declaration["size_bytes"]),
        )
        blob_hash = sha256_bytes(content)
        relative_path = blob_relative_path(blob_hash)
        target = _local_member(blob_root.parent, relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        mapping[str(declaration["key"])] = {
            "hash": blob_hash,
            "size_bytes": len(content),
            "mime": str(declaration["mime"]),
            "introduced_generation": int(
                declaration["introduced_generation"]
            ),
            "relative_path": relative_path,
        }
    return mapping


def _generation_by_number(
    fixture: dict[str, Any],
    generation: int,
) -> dict[str, Any]:
    for declaration in fixture["generations"]:
        if int(declaration["generation"]) == generation:
            return declaration
    raise SpikeError("UNKNOWN_FIXTURE_GENERATION", str(generation))


def _apply_generation(
    connection: sqlite3.Connection,
    fixture: dict[str, Any],
    blob_map: dict[str, dict[str, Any]],
    generation: int,
) -> None:
    declaration = _generation_by_number(fixture, generation)
    connection.execute("BEGIN IMMEDIATE")
    try:
        for key, blob in sorted(blob_map.items()):
            if int(blob["introduced_generation"]) != generation:
                continue
            connection.execute(
                """
                INSERT INTO blob_objects(
                    blob_hash, size_bytes, mime, relative_path,
                    introduced_generation
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    blob["hash"],
                    blob["size_bytes"],
                    blob["mime"],
                    blob["relative_path"],
                    generation,
                ),
            )
        for record in declaration["records"]:
            connection.execute(
                """
                INSERT INTO canonical_records(
                    record_id, title, introduced_generation, updated_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    record["record_id"],
                    record["title"],
                    generation,
                    declaration["committed_at"],
                ),
            )
            for position, blob_key in enumerate(record["blob_keys"]):
                blob = blob_map[str(blob_key)]
                connection.execute(
                    """
                    INSERT INTO record_blobs(
                        record_id, blob_hash, position, introduced_generation
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        record["record_id"],
                        blob["hash"],
                        position,
                        generation,
                    ),
                )
        connection.execute(
            """
            UPDATE logical_state
            SET current_generation = ?, committed_at = ?
            WHERE singleton = 1
            """,
            (generation, declaration["committed_at"]),
        )
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def materialize_source(
    root: Path,
    fixture: dict[str, Any],
    through_generation: int = 1,
) -> dict[str, Any]:
    source_root = root / "source"
    source_root.mkdir(parents=True, exist_ok=False)
    blob_root = source_root / "blobs"
    blob_map = _fixture_blob_map(fixture, blob_root)
    database_path = source_root / "canonical.sqlite3"
    database = fixture["database"]
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(f"PRAGMA page_size = {int(database['page_size'])}")
        observed_mode = connection.execute(
            f"PRAGMA journal_mode = {database['journal_mode']}"
        ).fetchone()[0]
        connection.execute(
            f"PRAGMA synchronous = {database['synchronous']}"
        )
        connection.execute(
            f"PRAGMA wal_autocheckpoint = {int(database['wal_autocheckpoint'])}"
        )
        connection.execute(
            f"PRAGMA busy_timeout = {int(database['busy_timeout_ms'])}"
        )
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA user_version = {int(database['user_version'])}")
        connection.executescript(
            """
            CREATE TABLE logical_state (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                current_generation INTEGER NOT NULL,
                committed_at TEXT NOT NULL
            );
            INSERT INTO logical_state(singleton, current_generation, committed_at)
            VALUES (1, 0, '1970-01-01T00:00:00Z');

            CREATE TABLE canonical_records (
                record_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                introduced_generation INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE blob_objects (
                blob_hash TEXT PRIMARY KEY,
                size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
                mime TEXT NOT NULL,
                relative_path TEXT NOT NULL UNIQUE,
                introduced_generation INTEGER NOT NULL
            );

            CREATE TABLE record_blobs (
                record_id TEXT NOT NULL
                    REFERENCES canonical_records(record_id) ON DELETE CASCADE,
                blob_hash TEXT NOT NULL
                    REFERENCES blob_objects(blob_hash) ON DELETE RESTRICT,
                position INTEGER NOT NULL,
                introduced_generation INTEGER NOT NULL,
                PRIMARY KEY(record_id, position)
            );

            CREATE TABLE padding (
                padding_id INTEGER PRIMARY KEY,
                payload BLOB NOT NULL
            );
            """
        )
        padding = deterministic_bytes(
            "nabla-backup-restore-padding",
            int(database["padding_bytes_per_row"]),
        )
        connection.executemany(
            "INSERT INTO padding(padding_id, payload) VALUES (?, ?)",
            (
                (row_number, padding)
                for row_number in range(int(database["padding_rows"]))
            ),
        )
        connection.commit()
        for generation in range(1, through_generation + 1):
            _apply_generation(
                connection,
                fixture,
                blob_map,
                generation,
            )
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        connection.commit()
    finally:
        connection.close()
    return {
        "root": source_root,
        "database": database_path,
        "blob_root": blob_root,
        "blob_map": blob_map,
        "journal_mode": str(observed_mode).upper(),
    }


def apply_generation(
    database_path: Path,
    fixture: dict[str, Any],
    blob_map: dict[str, dict[str, Any]],
    generation: int,
) -> None:
    database = fixture["database"]
    connection = _connect_rw(
        database_path,
        int(database["busy_timeout_ms"]),
    )
    try:
        connection.execute(
            f"PRAGMA wal_autocheckpoint = {int(database['wal_autocheckpoint'])}"
        )
        _apply_generation(
            connection,
            fixture,
            blob_map,
            generation,
        )
    finally:
        connection.close()


def sqlite_health(
    database_path: Path,
    *,
    immutable: bool = False,
) -> dict[str, Any]:
    try:
        connection = _connect_ro(database_path, immutable=immutable)
        try:
            integrity_rows = [
                str(row[0])
                for row in connection.execute("PRAGMA integrity_check")
            ]
            foreign_key_rows = [
                list(row)
                for row in connection.execute("PRAGMA foreign_key_check")
            ]
            user_version = int(
                connection.execute("PRAGMA user_version").fetchone()[0]
            )
        finally:
            connection.close()
    except sqlite3.DatabaseError as error:
        raise SpikeError(
            "SQLITE_CORRUPT",
            f"{type(error).__name__}: {error}",
        ) from error
    if integrity_rows != ["ok"]:
        raise SpikeError("SQLITE_INTEGRITY_FAILURE", "|".join(integrity_rows))
    if foreign_key_rows:
        raise SpikeError("SQLITE_FOREIGN_KEY_FAILURE", repr(foreign_key_rows))
    return {
        "integrity_check": integrity_rows,
        "foreign_key_violations": foreign_key_rows,
        "user_version": user_version,
    }


def canonical_state(
    database_path: Path,
    *,
    immutable: bool = False,
) -> dict[str, Any]:
    health = sqlite_health(database_path, immutable=immutable)
    connection = _connect_ro(database_path, immutable=immutable)
    try:
        state_row = connection.execute(
            """
            SELECT current_generation, committed_at
            FROM logical_state
            WHERE singleton = 1
            """
        ).fetchone()
        if state_row is None:
            raise SpikeError("MISSING_LOGICAL_STATE")
        records = [
            {
                "record_id": row[0],
                "title": row[1],
                "introduced_generation": int(row[2]),
                "updated_at": row[3],
            }
            for row in connection.execute(
                """
                SELECT record_id, title, introduced_generation, updated_at
                FROM canonical_records
                ORDER BY record_id
                """
            )
        ]
        blobs = [
            {
                "hash": row[0],
                "size_bytes": int(row[1]),
                "mime": row[2],
                "relative_path": row[3],
                "introduced_generation": int(row[4]),
            }
            for row in connection.execute(
                """
                SELECT blob_hash, size_bytes, mime, relative_path,
                       introduced_generation
                FROM blob_objects
                ORDER BY blob_hash
                """
            )
        ]
        references = [
            {
                "record_id": row[0],
                "blob_hash": row[1],
                "position": int(row[2]),
                "introduced_generation": int(row[3]),
            }
            for row in connection.execute(
                """
                SELECT record_id, blob_hash, position, introduced_generation
                FROM record_blobs
                ORDER BY record_id, position
                """
            )
        ]
        page_count = int(
            connection.execute("PRAGMA page_count").fetchone()[0]
        )
        page_size = int(
            connection.execute("PRAGMA page_size").fetchone()[0]
        )
    finally:
        connection.close()

    current_generation = int(state_row[0])
    all_generations = [
        item["introduced_generation"]
        for item in records + blobs + references
    ]
    if all_generations and max(all_generations) != current_generation:
        raise SpikeError(
            "TORN_LOGICAL_GENERATION",
            f"current={current_generation};max={max(all_generations)}",
        )
    if any(value > current_generation for value in all_generations):
        raise SpikeError(
            "FUTURE_GENERATION_MEMBER",
            str(current_generation),
        )
    blob_hashes = {item["hash"] for item in blobs}
    reference_hashes = {item["blob_hash"] for item in references}
    if blob_hashes != reference_hashes:
        raise SpikeError(
            "DB_BLOB_CLOSURE_MISMATCH",
            json.dumps(
                {
                    "unreferenced": sorted(blob_hashes - reference_hashes),
                    "missing": sorted(reference_hashes - blob_hashes),
                },
                sort_keys=True,
            ),
        )
    semantic = {
        "current_generation": current_generation,
        "committed_at": state_row[1],
        "records": records,
        "blobs": blobs,
        "references": references,
    }
    semantic_sha256 = sha256_bytes(
        json.dumps(
            semantic,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    return {
        **semantic,
        "semantic_sha256": semantic_sha256,
        "page_count": page_count,
        "page_size": page_size,
        "sqlite_bytes": database_path.stat().st_size,
        "health": health,
    }


def online_backup(
    source_database: Path,
    destination_database: Path,
    pages_per_step: int,
    progress: Callable[[int, int, int], None] | None = None,
) -> dict[str, Any]:
    destination_database.parent.mkdir(parents=True, exist_ok=True)
    source = _connect_ro(source_database)
    destination = sqlite3.connect(destination_database)
    started = time.monotonic()
    try:
        source.backup(
            destination,
            pages=int(pages_per_step),
            progress=progress,
            sleep=0.001,
        )
        destination.commit()
    finally:
        destination.close()
        source.close()
    duration_ms = int((time.monotonic() - started) * 1000)
    state = canonical_state(destination_database, immutable=True)
    return {
        "duration_ms": duration_ms,
        "generation": state["current_generation"],
        "page_count": state["page_count"],
        "page_size": state["page_size"],
        "sqlite_bytes": state["sqlite_bytes"],
        "semantic_sha256": state["semantic_sha256"],
    }


def manifest_from_snapshot(
    database_path: Path,
    *,
    immutable: bool = True,
) -> dict[str, Any]:
    state = canonical_state(database_path, immutable=immutable)
    blobs = [
        {
            "hash": item["hash"],
            "size_bytes": item["size_bytes"],
            "mime": item["mime"],
            "relative_path": item["relative_path"],
        }
        for item in state["blobs"]
    ]
    return {
        "schema_version": 1,
        "format_id": FORMAT_ID,
        "format_version": FORMAT_VERSION,
        "logical_generation": state["current_generation"],
        "database": {
            "relative_path": "database/snapshot.sqlite3",
            "user_version": state["health"]["user_version"],
            "semantic_sha256": state["semantic_sha256"],
        },
        "blobs": blobs,
        "counts": {
            "records": len(state["records"]),
            "blob_objects": len(blobs),
            "blob_references": len(state["references"]),
        },
        "exclusions": [
            "derived indexes",
            "device-local state",
            "secrets",
            "transport state",
        ],
    }


def validate_manifest_against_database(
    manifest: dict[str, Any],
    database_path: Path,
    *,
    immutable: bool = True,
) -> dict[str, Any]:
    state = canonical_state(database_path, immutable=immutable)
    manifest_generation = int(manifest.get("logical_generation", -1))
    if manifest_generation != state["current_generation"]:
        raise SpikeError(
            "DB_MANIFEST_GENERATION_MISMATCH",
            f"db={state['current_generation']};manifest={manifest_generation}",
        )
    database_manifest = manifest.get("database")
    if not isinstance(database_manifest, dict):
        raise SpikeError("INVALID_DATABASE_MANIFEST")
    if database_manifest.get("semantic_sha256") != state["semantic_sha256"]:
        raise SpikeError(
            "DB_MANIFEST_SEMANTIC_MISMATCH",
            str(database_manifest.get("semantic_sha256", "")),
        )
    blob_items = manifest.get("blobs")
    if not isinstance(blob_items, list):
        raise SpikeError("INVALID_BLOB_MANIFEST")
    manifest_hashes = {
        str(item["hash"])
        for item in blob_items
        if isinstance(item, dict) and "hash" in item
    }
    database_hashes = {item["hash"] for item in state["blobs"]}
    if manifest_hashes != database_hashes:
        raise SpikeError(
            "DB_MANIFEST_BLOB_CLOSURE_MISMATCH",
            json.dumps(
                {
                    "missing": sorted(database_hashes - manifest_hashes),
                    "extra": sorted(manifest_hashes - database_hashes),
                },
                sort_keys=True,
            ),
        )
    if len(manifest_hashes) != len(blob_items):
        raise SpikeError("DUPLICATE_BLOB_MANIFEST_ENTRY")
    return state


def _member_checksums(
    bundle_root: Path,
    member_paths: list[str],
) -> dict[str, Any]:
    members: dict[str, Any] = {}
    for relative_path in sorted(member_paths):
        member = _local_member(bundle_root, relative_path)
        members[relative_path] = {
            "sha256": sha256_file(member),
            "size_bytes": member.stat().st_size,
        }
    return {
        "schema_version": 1,
        "algorithm": "sha256",
        "members": members,
    }


def create_bundle(
    snapshot_database: Path,
    source_blob_root: Path,
    staging_root: Path,
    published_root: Path,
) -> dict[str, Any]:
    if staging_root.exists() or published_root.exists():
        raise SpikeError("NONEMPTY_BUNDLE_TARGET")
    staging_root.mkdir(parents=True)
    write_json(
        staging_root / INCOMPLETE_NAME,
        {"status": "incomplete", "format_id": FORMAT_ID},
    )
    manifest = manifest_from_snapshot(snapshot_database)
    database_relative = str(manifest["database"]["relative_path"])
    database_target = _local_member(staging_root, database_relative)
    database_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(snapshot_database, database_target)
    member_paths = [database_relative]
    for item in manifest["blobs"]:
        relative_path = str(item["relative_path"])
        source = _local_member(source_blob_root.parent, relative_path)
        if not source.is_file():
            raise SpikeError("SOURCE_BLOB_MISSING", str(item["hash"]))
        if source.stat().st_size != int(item["size_bytes"]):
            raise SpikeError("SOURCE_BLOB_SIZE_MISMATCH", str(item["hash"]))
        if sha256_file(source) != str(item["hash"]):
            raise SpikeError("SOURCE_BLOB_CHECKSUM_MISMATCH", str(item["hash"]))
        target = _local_member(staging_root, relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        member_paths.append(relative_path)
    manifest_path = staging_root / "manifest.json"
    checksums_path = staging_root / "checksums.json"
    write_json(manifest_path, manifest)
    write_json(
        checksums_path,
        _member_checksums(staging_root, member_paths),
    )
    _verify_bundle_contents(staging_root, require_complete=False)
    (staging_root / INCOMPLETE_NAME).unlink()
    write_json(
        staging_root / COMPLETE_NAME,
        {
            "schema_version": 1,
            "status": "complete",
            "format_id": FORMAT_ID,
            "format_version": FORMAT_VERSION,
            "manifest_sha256": sha256_file(manifest_path),
            "checksums_sha256": sha256_file(checksums_path),
        },
    )
    verification = verify_bundle(staging_root)
    os.replace(staging_root, published_root)
    return verification


def verify_bundle(bundle_root: Path) -> dict[str, Any]:
    return _verify_bundle_contents(bundle_root, require_complete=True)


def _verify_bundle_contents(
    bundle_root: Path,
    *,
    require_complete: bool,
) -> dict[str, Any]:
    manifest_path = bundle_root / "manifest.json"
    checksums_path = bundle_root / "checksums.json"
    if require_complete:
        complete_path = bundle_root / COMPLETE_NAME
        if not complete_path.is_file():
            raise SpikeError("BUNDLE_INCOMPLETE", "missing completeness marker")
        complete = load_json(complete_path)
        if (
            complete.get("status") != "complete"
            or complete.get("format_id") != FORMAT_ID
            or int(complete.get("format_version", -1)) != FORMAT_VERSION
        ):
            raise SpikeError("UNSUPPORTED_COMPLETE_MARKER")
        if not manifest_path.is_file() or not checksums_path.is_file():
            raise SpikeError("MISSING_BUNDLE_METADATA")
        if sha256_file(manifest_path) != complete.get("manifest_sha256"):
            raise SpikeError("MANIFEST_CHECKSUM_MISMATCH")
        if sha256_file(checksums_path) != complete.get("checksums_sha256"):
            raise SpikeError("CHECKSUM_MANIFEST_MISMATCH")
    else:
        if not (bundle_root / INCOMPLETE_NAME).is_file():
            raise SpikeError(
                "MISSING_STAGING_MARKER",
                "pre-publication validation requires INCOMPLETE.json",
            )
    if not manifest_path.is_file() or not checksums_path.is_file():
        raise SpikeError("MISSING_BUNDLE_METADATA")
    manifest = load_json(manifest_path)
    if (
        manifest.get("format_id") != FORMAT_ID
        or int(manifest.get("format_version", -1)) != FORMAT_VERSION
    ):
        raise SpikeError("UNSUPPORTED_BUNDLE_FORMAT")
    checksums = load_json(checksums_path)
    members = checksums.get("members")
    if not isinstance(members, dict):
        raise SpikeError("INVALID_CHECKSUM_MEMBERS")
    expected_members = {
        str(manifest["database"]["relative_path"]),
        *[str(item["relative_path"]) for item in manifest["blobs"]],
    }
    if set(members) != expected_members:
        raise SpikeError(
            "CHECKSUM_MEMBER_CLOSURE_MISMATCH",
            json.dumps(
                {
                    "missing": sorted(expected_members - set(members)),
                    "extra": sorted(set(members) - expected_members),
                },
                sort_keys=True,
            ),
        )
    for relative_path, declaration in sorted(members.items()):
        member = _local_member(bundle_root, relative_path)
        if not member.is_file():
            raise SpikeError("MISSING_MEMBER", relative_path)
        observed_size = member.stat().st_size
        if observed_size != int(declaration["size_bytes"]):
            raise SpikeError(
                "MEMBER_SIZE_MISMATCH",
                f"{relative_path}:{observed_size}",
            )
        observed_hash = sha256_file(member)
        if observed_hash != declaration["sha256"]:
            raise SpikeError("MEMBER_CHECKSUM_MISMATCH", relative_path)
    database_path = _local_member(
        bundle_root,
        str(manifest["database"]["relative_path"]),
    )
    state = validate_manifest_against_database(manifest, database_path)
    intact_blob_count = 0
    intact_blob_bytes = 0
    for item in manifest["blobs"]:
        relative_path = str(item["relative_path"])
        blob_path = _local_member(bundle_root, relative_path)
        observed_size = blob_path.stat().st_size
        if observed_size != int(item["size_bytes"]):
            raise SpikeError("BLOB_SIZE_MISMATCH", str(item["hash"]))
        observed_hash = sha256_file(blob_path)
        if observed_hash != str(item["hash"]):
            raise SpikeError("BLOB_CONTENT_HASH_MISMATCH", str(item["hash"]))
        if relative_path != blob_relative_path(observed_hash):
            raise SpikeError("BLOB_HASH_PATH_MISMATCH", relative_path)
        intact_blob_count += 1
        intact_blob_bytes += observed_size
    lifecycle_marker = COMPLETE_NAME if require_complete else INCOMPLETE_NAME
    allowed_files = {
        lifecycle_marker,
        "manifest.json",
        "checksums.json",
        *expected_members,
    }
    observed_files = {
        path.relative_to(bundle_root).as_posix()
        for path in bundle_root.rglob("*")
        if path.is_file()
    }
    if observed_files != allowed_files:
        raise SpikeError(
            "UNEXPECTED_BUNDLE_MEMBER",
            json.dumps(sorted(observed_files - allowed_files)),
        )
    return {
        "generation": state["current_generation"],
        "semantic_sha256": state["semantic_sha256"],
        "record_count": len(state["records"]),
        "blob_count": intact_blob_count,
        "blob_bytes": intact_blob_bytes,
        "sqlite_bytes": database_path.stat().st_size,
        "integrity_check": state["health"]["integrity_check"],
        "foreign_key_violations": state["health"][
            "foreign_key_violations"
        ],
    }


def refresh_member_integrity(bundle_root: Path, relative_path: str) -> None:
    checksums_path = bundle_root / "checksums.json"
    checksums = load_json(checksums_path)
    member = _local_member(bundle_root, relative_path)
    checksums["members"][relative_path] = {
        "sha256": sha256_file(member),
        "size_bytes": member.stat().st_size,
    }
    write_json(checksums_path, checksums)
    complete_path = bundle_root / COMPLETE_NAME
    complete = load_json(complete_path)
    complete["checksums_sha256"] = sha256_file(checksums_path)
    write_json(complete_path, complete)


def refresh_manifest_integrity(bundle_root: Path) -> None:
    complete_path = bundle_root / COMPLETE_NAME
    complete = load_json(complete_path)
    complete["manifest_sha256"] = sha256_file(bundle_root / "manifest.json")
    write_json(complete_path, complete)


def stage_restore(
    bundle_root: Path,
    install_root: Path,
    generation_name: str,
) -> Path:
    verification = verify_bundle(bundle_root)
    generations_root = install_root / "generations"
    generations_root.mkdir(parents=True, exist_ok=True)
    staging = generations_root / f"{generation_name}.staging"
    final = generations_root / generation_name
    if staging.exists() or final.exists():
        raise SpikeError("RESTORE_GENERATION_EXISTS", generation_name)
    staging.mkdir()
    manifest = load_json(bundle_root / "manifest.json")
    database_source = _local_member(
        bundle_root,
        str(manifest["database"]["relative_path"]),
    )
    shutil.copyfile(database_source, staging / "state.sqlite3")
    for item in manifest["blobs"]:
        source = _local_member(bundle_root, str(item["relative_path"]))
        relative = PurePosixPath(str(item["relative_path"]))
        target = staging.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    write_json(
        staging / "RESTORE_READY.json",
        {
            "status": "ready",
            "generation": verification["generation"],
            "semantic_sha256": verification["semantic_sha256"],
            "blob_count": verification["blob_count"],
        },
    )
    verify_staged_generation(staging)
    return staging


def verify_staged_generation(staging: Path) -> dict[str, Any]:
    marker = load_json(staging / "RESTORE_READY.json")
    state = canonical_state(staging / "state.sqlite3", immutable=True)
    if marker.get("semantic_sha256") != state["semantic_sha256"]:
        raise SpikeError("RESTORE_SEMANTIC_MISMATCH")
    blob_items = state["blobs"]
    total_bytes = 0
    for item in blob_items:
        relative = PurePosixPath(str(item["relative_path"]))
        target = staging.joinpath(*relative.parts)
        if not target.is_file():
            raise SpikeError("RESTORE_BLOB_MISSING", str(item["hash"]))
        if target.stat().st_size != int(item["size_bytes"]):
            raise SpikeError("RESTORE_BLOB_SIZE_MISMATCH", str(item["hash"]))
        if sha256_file(target) != str(item["hash"]):
            raise SpikeError(
                "RESTORE_BLOB_CHECKSUM_MISMATCH",
                str(item["hash"]),
            )
        total_bytes += target.stat().st_size
    return {
        "generation": state["current_generation"],
        "semantic_sha256": state["semantic_sha256"],
        "blob_count": len(blob_items),
        "blob_bytes": total_bytes,
    }


def publish_staged_restore(
    install_root: Path,
    generation_name: str,
) -> dict[str, Any]:
    staging = install_root / "generations" / f"{generation_name}.staging"
    final = install_root / "generations" / generation_name
    verification = verify_staged_generation(staging)
    if final.exists():
        raise SpikeError("RESTORE_GENERATION_EXISTS", generation_name)
    os.replace(staging, final)
    pointer_temp = install_root / "ACTIVE.tmp"
    pointer = install_root / "ACTIVE"
    with pointer_temp.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(generation_name + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(pointer_temp, pointer)
    return verification


def restore_bundle(
    bundle_root: Path,
    install_root: Path,
    generation_name: str,
) -> dict[str, Any]:
    stage_restore(bundle_root, install_root, generation_name)
    return publish_staged_restore(install_root, generation_name)


def active_install_state(install_root: Path) -> dict[str, Any] | None:
    pointer = install_root / "ACTIVE"
    if not pointer.is_file():
        return None
    generation_name = pointer.read_text(encoding="utf-8").strip()
    if (
        not generation_name
        or "/" in generation_name
        or "\\" in generation_name
        or generation_name in {".", ".."}
    ):
        raise SpikeError("UNSAFE_ACTIVE_POINTER", generation_name)
    generation_root = install_root / "generations" / generation_name
    verification = verify_staged_generation(generation_root)
    return {
        "pointer": generation_name,
        **verification,
    }


def checkpoint_and_block(
    checkpoint_path: Path,
    payload: dict[str, Any],
) -> None:
    write_json(checkpoint_path, payload)
    while True:
        time.sleep(1)
