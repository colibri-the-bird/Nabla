"""Run the bounded SPIKE-BACKUP-RESTORE-001 measurement.

The harness is deliberately self-contained and standard-library-only. It
produces observations for later specification/ADR work and does not implement
production backup or recovery.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

from _spike_harness import (
    COMPLETE_NAME,
    FORMAT_ID,
    FORMAT_VERSION,
    INCOMPLETE_NAME,
    SpikeError,
    active_install_state,
    apply_generation,
    canonical_state,
    create_bundle,
    load_json,
    manifest_from_snapshot,
    materialize_source,
    online_backup,
    refresh_member_integrity,
    restore_bundle,
    sha256_file,
    validate_manifest_against_database,
    verify_bundle,
    write_json,
)


SCRIPT_ROOT = Path(__file__).resolve().parent
FIXTURE_PATH = SCRIPT_ROOT / "fixtures" / "generation-v1.json"
WORKER_PATH = SCRIPT_ROOT / "worker.py"
DEFAULT_OUTPUT = SCRIPT_ROOT / "results" / "windows_x86_64.json"
CANONICAL_COMMAND = (
    "python tests/spikes/backup-restore/run_experiment.py "
    "--output tests/spikes/backup-restore/results/windows_x86_64.json"
)


class Case:
    def __init__(
        self,
        case_id: str,
        failure_domain: str,
        expected_outcome: str,
    ) -> None:
        self.started = time.monotonic()
        self.result: dict[str, Any] = {
            "id": case_id,
            "failure_domain": failure_domain,
            "expected_outcome": expected_outcome,
            "checks": [],
            "diagnostics": [],
            "observations": {},
        }

    def require(
        self,
        layer: str,
        check_id: str,
        passed: bool,
        expected: Any,
        observed: Any,
    ) -> None:
        self.result["checks"].append(
            {
                "layer": layer,
                "id": check_id,
                "expected": expected,
                "observed": observed,
                "passed": bool(passed),
            }
        )

    def diagnostic(self, code: str, detail: str = "") -> None:
        self.result["diagnostics"].append(
            {"code": code, "detail": detail}
        )

    def observe(self, key: str, value: Any) -> None:
        self.result["observations"][key] = value

    def finish(self) -> dict[str, Any]:
        self.result["duration_ms"] = int(
            (time.monotonic() - self.started) * 1000
        )
        self.result["passed"] = bool(self.result["checks"]) and all(
            check["passed"] for check in self.result["checks"]
        )
        return self.result


def _sanitize(text: str, work_root: Path) -> str:
    sanitized = text.replace(str(work_root), "<WORK_ROOT>")
    sanitized = sanitized.replace(str(SCRIPT_ROOT), "<HARNESS_ROOT>")
    return sanitized[-2000:]


def _expected_error(action: Callable[[], Any]) -> dict[str, str]:
    try:
        action()
    except SpikeError as error:
        return {"code": error.code, "detail": error.detail}
    return {"code": "NO_ERROR", "detail": ""}


def _run_case(
    results: list[dict[str, Any]],
    work_root: Path,
    case_id: str,
    failure_domain: str,
    expected_outcome: str,
    body: Callable[[Case], None],
) -> None:
    case = Case(case_id, failure_domain, expected_outcome)
    try:
        body(case)
    except BaseException as error:
        case.diagnostic(
            "UNEXPECTED_EXCEPTION",
            _sanitize(f"{type(error).__name__}: {error}", work_root),
        )
        case.require(
            "harness",
            "case_completed_without_unexpected_exception",
            False,
            "no unexpected exception",
            type(error).__name__,
        )
    results.append(case.finish())


def _wait_then_kill(
    command: list[str],
    checkpoint_path: Path,
    timeout_seconds: int,
    work_root: Path,
) -> dict[str, Any]:
    process = subprocess.Popen(
        command,
        cwd=SCRIPT_ROOT,
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + timeout_seconds
    checkpoint: dict[str, Any] | None = None
    timed_out = False
    while time.monotonic() < deadline:
        if checkpoint_path.is_file():
            checkpoint = load_json(checkpoint_path)
            break
        if process.poll() is not None:
            break
        time.sleep(0.02)
    else:
        timed_out = True
    if process.poll() is None:
        process.kill()
    try:
        stdout, stderr = process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate(timeout=5)
        timed_out = True
    return {
        "checkpoint_reached": checkpoint is not None,
        "checkpoint": checkpoint,
        "returncode": process.returncode,
        "timed_out": timed_out,
        "stdout": _sanitize(stdout, work_root),
        "stderr": _sanitize(stderr, work_root),
    }


def _copy_bundle(source: Path, destination: Path) -> Path:
    shutil.copytree(source, destination)
    return destination


def _flip_byte(path: Path, offset: int) -> None:
    with path.open("r+b") as handle:
        handle.seek(offset)
        original = handle.read(1)
        if len(original) != 1:
            raise RuntimeError("cannot flip byte outside file")
        handle.seek(offset)
        handle.write(bytes([original[0] ^ 0xFF]))
        handle.flush()
        os.fsync(handle.fileno())


def _blob_member(bundle: Path, largest: bool = False) -> dict[str, Any]:
    blobs = list(load_json(bundle / "manifest.json")["blobs"])
    if not blobs:
        raise RuntimeError("bundle has no blobs")
    key = (lambda item: int(item["size_bytes"]))
    return max(blobs, key=key) if largest else min(blobs, key=key)


def _count_intact_other_blobs(
    bundle: Path,
    excluded_hash: str,
) -> tuple[int, int]:
    manifest = load_json(bundle / "manifest.json")
    intact = 0
    total = 0
    for item in manifest["blobs"]:
        if item["hash"] == excluded_hash:
            continue
        total += 1
        path = bundle.joinpath(*Path(item["relative_path"]).parts)
        if (
            path.is_file()
            and path.stat().st_size == int(item["size_bytes"])
            and sha256_file(path) == item["hash"]
        ):
            intact += 1
    return intact, total


def _preflight_preserves_active(
    candidate_bundle: Path,
    baseline_bundle: Path,
    install_root: Path,
    generation_name: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    restore_bundle(baseline_bundle, install_root, "baseline-g1")
    before = active_install_state(install_root)
    error = _expected_error(
        lambda: restore_bundle(
            candidate_bundle,
            install_root,
            generation_name,
        )
    )
    after = active_install_state(install_root)
    if before is None or after is None:
        raise RuntimeError("baseline active installation disappeared")
    return before, after, error


def _compile_options() -> list[str]:
    connection = sqlite3.connect(":memory:")
    try:
        return sorted(
            str(row[0])
            for row in connection.execute("PRAGMA compile_options")
        )
    finally:
        connection.close()


def execute_measurement(work_root: Path) -> dict[str, Any]:
    fixture = load_json(FIXTURE_PATH)
    limits = fixture["limits"]
    cases: list[dict[str, Any]] = []
    shared: dict[str, Any] = {}
    run_started = time.monotonic()

    def quiescent_snapshot(case: Case) -> None:
        case_root = work_root / "01-quiescent"
        source = materialize_source(case_root, fixture, through_generation=1)
        source_state = canonical_state(source["database"])
        snapshot = case_root / "snapshot.sqlite3"
        backup_metrics = online_backup(
            source["database"],
            snapshot,
            int(limits["backup_pages_per_step"]),
        )
        snapshot_state = canonical_state(snapshot, immutable=True)
        bundle = case_root / "bundle"
        verification = create_bundle(
            snapshot,
            source["blob_root"],
            case_root / "bundle.staging",
            bundle,
        )
        case.require(
            "sqlite",
            "quiescent_snapshot_generation",
            snapshot_state["current_generation"] == 1,
            1,
            snapshot_state["current_generation"],
        )
        case.require(
            "semantic",
            "snapshot_matches_source",
            snapshot_state["semantic_sha256"]
            == source_state["semantic_sha256"],
            source_state["semantic_sha256"],
            snapshot_state["semantic_sha256"],
        )
        case.require(
            "bundle",
            "snapshot_derived_bundle_verifies",
            verification["integrity_check"] == ["ok"]
            and verification["foreign_key_violations"] == [],
            {"integrity_check": ["ok"], "foreign_key_violations": []},
            {
                "integrity_check": verification["integrity_check"],
                "foreign_key_violations": verification[
                    "foreign_key_violations"
                ],
            },
        )
        case.observe("backup", backup_metrics)
        case.observe(
            "bundle",
            {
                "generation": verification["generation"],
                "record_count": verification["record_count"],
                "blob_count": verification["blob_count"],
                "blob_bytes": verification["blob_bytes"],
            },
        )
        shared.update(
            {
                "baseline_source": source,
                "baseline_snapshot": snapshot,
                "baseline_bundle": bundle,
            }
        )

    _run_case(
        cases,
        work_root,
        "QUIESCENT_ONLINE_SNAPSHOT",
        "sqlite-snapshot",
        "A quiescent online backup and snapshot-derived blob bundle verify.",
        quiescent_snapshot,
    )

    def concurrent_snapshot(case: Case) -> None:
        case_root = work_root / "02-concurrent"
        source = materialize_source(case_root, fixture, through_generation=1)
        generation_one_state = canonical_state(source["database"])
        writer_start = threading.Event()
        writer_done = threading.Event()
        writer_errors: list[str] = []
        progress_rows: list[dict[str, int]] = []

        def writer() -> None:
            if not writer_start.wait(timeout=10):
                writer_errors.append("writer start timeout")
                writer_done.set()
                return
            try:
                apply_generation(
                    source["database"],
                    fixture,
                    source["blob_map"],
                    2,
                )
            except BaseException as error:
                writer_errors.append(f"{type(error).__name__}: {error}")
            finally:
                writer_done.set()

        writer_thread = threading.Thread(
            target=writer,
            name="bounded-wal-writer",
            daemon=True,
        )
        writer_thread.start()
        triggered = False

        def progress(status: int, remaining: int, total: int) -> None:
            nonlocal triggered
            if len(progress_rows) < 12:
                progress_rows.append(
                    {
                        "status": int(status),
                        "remaining_pages": int(remaining),
                        "total_pages": int(total),
                    }
                )
            if not triggered and remaining > 0:
                triggered = True
                writer_start.set()
                if not writer_done.wait(timeout=10):
                    raise RuntimeError("bounded WAL writer did not finish")

        snapshot = case_root / "snapshot.sqlite3"
        backup_metrics = online_backup(
            source["database"],
            snapshot,
            int(limits["backup_pages_per_step"]),
            progress,
        )
        writer_thread.join(timeout=2)
        source_state = canonical_state(source["database"])
        snapshot_state = canonical_state(snapshot, immutable=True)
        bundle = case_root / "bundle"
        verification = create_bundle(
            snapshot,
            source["blob_root"],
            case_root / "bundle.staging",
            bundle,
        )
        case.require(
            "concurrency",
            "writer_committed_generation_two",
            writer_done.is_set()
            and not writer_errors
            and source_state["current_generation"] == 2,
            {"writer_errors": [], "source_generation": 2},
            {
                "writer_errors": writer_errors,
                "source_generation": source_state["current_generation"],
            },
        )
        expected_snapshot_state = {
            1: generation_one_state,
            2: source_state,
        }.get(snapshot_state["current_generation"])
        exact_fixture_match = (
            expected_snapshot_state is not None
            and snapshot_state["semantic_sha256"]
            == expected_snapshot_state["semantic_sha256"]
            and len(snapshot_state["records"])
            == len(expected_snapshot_state["records"])
            and len(snapshot_state["blobs"])
            == len(expected_snapshot_state["blobs"])
            and len(snapshot_state["references"])
            == len(expected_snapshot_state["references"])
        )
        case.require(
            "sqlite",
            "snapshot_is_one_complete_generation",
            exact_fixture_match,
            "exact semantic state of fixture generation 1 or 2",
            {
                "generation": snapshot_state["current_generation"],
                "semantic_sha256": snapshot_state["semantic_sha256"],
                "record_count": len(snapshot_state["records"]),
                "blob_count": len(snapshot_state["blobs"]),
                "reference_count": len(snapshot_state["references"]),
            },
        )
        case.require(
            "bundle",
            "bundle_matches_captured_snapshot",
            verification["generation"]
            == snapshot_state["current_generation"]
            and verification["semantic_sha256"]
            == snapshot_state["semantic_sha256"],
            {
                "generation": snapshot_state["current_generation"],
                "semantic_sha256": snapshot_state["semantic_sha256"],
            },
            {
                "generation": verification["generation"],
                "semantic_sha256": verification["semantic_sha256"],
            },
        )
        case.observe("captured_generation", snapshot_state["current_generation"])
        case.observe("progress_sample", progress_rows)
        case.observe("backup", backup_metrics)
        shared.update(
            {
                "generation_two_source": source,
                "concurrent_snapshot": snapshot,
                "concurrent_bundle": bundle,
            }
        )

    _run_case(
        cases,
        work_root,
        "CONCURRENT_WAL_ONLINE_SNAPSHOT",
        "sqlite-snapshot",
        "A bounded concurrent commit may change the captured generation but cannot tear it.",
        concurrent_snapshot,
    )

    def wal_main_copy(case: Case) -> None:
        case_root = work_root / "03-main-file-copy"
        source = materialize_source(case_root, fixture, through_generation=1)
        guard = sqlite3.connect(source["database"])
        try:
            guard.execute("PRAGMA wal_autocheckpoint = 0")
            guard.execute("BEGIN")
            pinned_generation = int(
                guard.execute(
                    "SELECT current_generation FROM logical_state"
                ).fetchone()[0]
            )
            apply_generation(
                source["database"],
                fixture,
                source["blob_map"],
                2,
            )
            wal_path = Path(str(source["database"]) + "-wal")
            live_state = canonical_state(source["database"])
            copied_database = case_root / "main-file-only.sqlite3"
            shutil.copyfile(source["database"], copied_database)
            copied_state = canonical_state(
                copied_database,
                immutable=True,
            )
            case.require(
                "negative-control",
                "main_file_copy_loses_committed_wal_generation",
                live_state["current_generation"] == 2
                and copied_state["current_generation"] == 1
                and pinned_generation == 1,
                {"live_generation": 2, "copy_generation": 1},
                {
                    "live_generation": live_state["current_generation"],
                    "copy_generation": copied_state["current_generation"],
                },
            )
            case.require(
                "sqlite",
                "stale_copy_can_still_pass_integrity_check",
                copied_state["health"]["integrity_check"] == ["ok"],
                ["ok"],
                copied_state["health"]["integrity_check"],
            )
            case.observe(
                "wal_bytes",
                wal_path.stat().st_size if wal_path.exists() else 0,
            )
            case.observe(
                "semantic_digests_differ",
                live_state["semantic_sha256"]
                != copied_state["semantic_sha256"],
            )
        finally:
            guard.close()

    _run_case(
        cases,
        work_root,
        "LIVE_WAL_MAIN_FILE_COPY_NEGATIVE_CONTROL",
        "sqlite-snapshot",
        "Copying only the live DB main file is detected as stale despite structural integrity.",
        wal_main_copy,
    )

    def live_manifest_negative(case: Case) -> None:
        live_manifest = manifest_from_snapshot(
            shared["generation_two_source"]["database"],
            immutable=False,
        )
        error = _expected_error(
            lambda: validate_manifest_against_database(
                live_manifest,
                shared["baseline_snapshot"],
            )
        )
        case.require(
            "closure",
            "live_manifest_rejected_for_older_snapshot",
            error["code"] == "DB_MANIFEST_GENERATION_MISMATCH",
            "DB_MANIFEST_GENERATION_MISMATCH",
            error["code"],
        )
        case.diagnostic(error["code"], error["detail"])
        case.observe(
            "snapshot_generation",
            canonical_state(
                shared["baseline_snapshot"],
                immutable=True,
            )[
                "current_generation"
            ],
        )
        case.observe(
            "live_manifest_generation",
            live_manifest["logical_generation"],
        )

    _run_case(
        cases,
        work_root,
        "LIVE_MANIFEST_NEGATIVE_CONTROL",
        "db-blob-generation",
        "A blob manifest from a newer live DB is rejected against the snapshot.",
        live_manifest_negative,
    )

    def clean_restore(case: Case) -> None:
        case_root = work_root / "05-clean-restore"
        source = shared["generation_two_source"]
        stable_snapshot = case_root / "snapshot-g2.sqlite3"
        online_backup(
            source["database"],
            stable_snapshot,
            int(limits["backup_pages_per_step"]),
        )
        stable_bundle = case_root / "bundle-g2"
        bundle_verification = create_bundle(
            stable_snapshot,
            source["blob_root"],
            case_root / "bundle-g2.staging",
            stable_bundle,
        )
        install_root = case_root / "install"
        before = active_install_state(install_root)
        restored = restore_bundle(
            stable_bundle,
            install_root,
            "generation-two",
        )
        after = active_install_state(install_root)
        case.require(
            "activation",
            "active_pointer_absent_before_restore",
            before is None,
            None,
            before,
        )
        case.require(
            "restore",
            "restored_semantics_match_snapshot",
            after is not None
            and after["semantic_sha256"]
            == bundle_verification["semantic_sha256"]
            == restored["semantic_sha256"],
            bundle_verification["semantic_sha256"],
            None if after is None else after["semantic_sha256"],
        )
        case.require(
            "restore",
            "restored_generation_and_blobs_complete",
            after is not None
            and after["generation"] == 2
            and after["blob_count"] == bundle_verification["blob_count"],
            {
                "generation": 2,
                "blob_count": bundle_verification["blob_count"],
            },
            None
            if after is None
            else {
                "generation": after["generation"],
                "blob_count": after["blob_count"],
            },
        )
        case.observe("bundle", bundle_verification)
        case.observe("active_pointer", after["pointer"] if after else None)
        shared.update(
            {
                "stable_snapshot": stable_snapshot,
                "stable_bundle": stable_bundle,
            }
        )

    _run_case(
        cases,
        work_root,
        "CLEAN_INSTALL_RESTORE",
        "restore",
        "A fully verified generation-two bundle restores into an empty installation.",
        clean_restore,
    )

    def interrupted_database_backup(case: Case) -> None:
        case_root = work_root / "06-interrupted-db"
        source = shared["generation_two_source"]
        before = canonical_state(source["database"])
        staging = case_root / "bundle.staging"
        checkpoint = case_root / "checkpoint.json"
        process = _wait_then_kill(
            [
                sys.executable,
                str(WORKER_PATH),
                "interrupt-database-backup",
                "--source-database",
                str(source["database"]),
                "--staging",
                str(staging),
                "--checkpoint",
                str(checkpoint),
                "--after-callbacks",
                str(limits["crash_after_backup_callbacks"]),
            ],
            checkpoint,
            int(limits["subprocess_timeout_seconds"]),
            work_root,
        )
        after = canonical_state(source["database"])
        rejection = _expected_error(lambda: verify_bundle(staging))
        partial = staging / "database" / "snapshot.sqlite3.partial"
        case.require(
            "fault-injection",
            "exact_database_backup_checkpoint_reached",
            process["checkpoint_reached"] and not process["timed_out"],
            {"checkpoint_reached": True, "timed_out": False},
            {
                "checkpoint_reached": process["checkpoint_reached"],
                "timed_out": process["timed_out"],
            },
        )
        case.require(
            "publication",
            "interrupted_database_backup_not_published",
            process["returncode"] != 0
            and not (staging / COMPLETE_NAME).exists()
            and rejection["code"] == "BUNDLE_INCOMPLETE",
            {
                "returncode": "non-zero",
                "complete_marker": False,
                "verification": "BUNDLE_INCOMPLETE",
            },
            {
                "returncode": process["returncode"],
                "complete_marker": (staging / COMPLETE_NAME).exists(),
                "verification": rejection["code"],
            },
        )
        case.require(
            "source-safety",
            "source_unchanged_after_worker_termination",
            before["semantic_sha256"] == after["semantic_sha256"]
            and after["health"]["integrity_check"] == ["ok"],
            before["semantic_sha256"],
            after["semantic_sha256"],
        )
        case.observe("process", process)
        case.observe(
            "partial_database_bytes",
            partial.stat().st_size if partial.exists() else 0,
        )
        case.diagnostic(rejection["code"], rejection["detail"])

    _run_case(
        cases,
        work_root,
        "INTERRUPTED_DATABASE_BACKUP",
        "backup-job",
        "Termination during SQLite backup leaves no published bundle and does not alter the source.",
        interrupted_database_backup,
    )

    def interrupted_blob_copy(case: Case) -> None:
        case_root = work_root / "07-interrupted-blob"
        source_bundle = shared["stable_bundle"]
        blob = _blob_member(source_bundle, largest=True)
        source_blob = source_bundle.joinpath(
            *Path(blob["relative_path"]).parts
        )
        staging = case_root / "bundle.staging"
        staging.mkdir(parents=True)
        write_json(
            staging / INCOMPLETE_NAME,
            {"status": "incomplete", "format_id": FORMAT_ID},
        )
        partial = staging / "blob.partial"
        final = staging / "blob.final"
        checkpoint = case_root / "checkpoint.json"
        process = _wait_then_kill(
            [
                sys.executable,
                str(WORKER_PATH),
                "interrupt-blob-copy",
                "--source",
                str(source_blob),
                "--partial",
                str(partial),
                "--final",
                str(final),
                "--checkpoint",
                str(checkpoint),
                "--chunk-size",
                str(limits["blob_copy_chunk_bytes"]),
                "--after-chunks",
                str(limits["crash_after_blob_chunks"]),
            ],
            checkpoint,
            int(limits["subprocess_timeout_seconds"]),
            work_root,
        )
        rejection = _expected_error(lambda: verify_bundle(staging))
        expected_partial = (
            int(limits["blob_copy_chunk_bytes"])
            * int(limits["crash_after_blob_chunks"])
        )
        case.require(
            "fault-injection",
            "exact_blob_copy_checkpoint_reached",
            process["checkpoint_reached"] and not process["timed_out"],
            {"checkpoint_reached": True, "timed_out": False},
            {
                "checkpoint_reached": process["checkpoint_reached"],
                "timed_out": process["timed_out"],
            },
        )
        case.require(
            "blob",
            "partial_blob_never_promoted",
            partial.is_file()
            and partial.stat().st_size == expected_partial
            and not final.exists()
            and rejection["code"] == "BUNDLE_INCOMPLETE",
            {
                "partial_bytes": expected_partial,
                "final_exists": False,
                "verification": "BUNDLE_INCOMPLETE",
            },
            {
                "partial_bytes": (
                    partial.stat().st_size if partial.exists() else 0
                ),
                "final_exists": final.exists(),
                "verification": rejection["code"],
            },
        )
        case.require(
            "source-safety",
            "source_bundle_remains_verified",
            verify_bundle(source_bundle)["generation"] == 2,
            2,
            verify_bundle(source_bundle)["generation"],
        )
        case.observe("process", process)
        case.diagnostic(rejection["code"], rejection["detail"])

    _run_case(
        cases,
        work_root,
        "INTERRUPTED_BLOB_COPY",
        "blob",
        "Termination after finite blob chunks leaves only an incomplete staging file.",
        interrupted_blob_copy,
    )

    def interrupted_restore(case: Case) -> None:
        case_root = work_root / "08-interrupted-restore"
        install_root = case_root / "install"
        restore_bundle(
            shared["baseline_bundle"],
            install_root,
            "baseline-g1",
        )
        before = active_install_state(install_root)
        checkpoint = case_root / "checkpoint.json"
        process = _wait_then_kill(
            [
                sys.executable,
                str(WORKER_PATH),
                "interrupt-restore",
                "--bundle",
                str(shared["stable_bundle"]),
                "--install-root",
                str(install_root),
                "--generation-name",
                "candidate-g2",
                "--checkpoint",
                str(checkpoint),
            ],
            checkpoint,
            int(limits["subprocess_timeout_seconds"]),
            work_root,
        )
        after_crash = active_install_state(install_root)
        candidate_final = install_root / "generations" / "candidate-g2"
        candidate_staging = (
            install_root / "generations" / "candidate-g2.staging"
        )
        retried = restore_bundle(
            shared["stable_bundle"],
            install_root,
            "retry-g2",
        )
        after_retry = active_install_state(install_root)
        case.require(
            "fault-injection",
            "restore_pre_activation_checkpoint_reached",
            process["checkpoint_reached"] and not process["timed_out"],
            {"checkpoint_reached": True, "timed_out": False},
            {
                "checkpoint_reached": process["checkpoint_reached"],
                "timed_out": process["timed_out"],
            },
        )
        case.require(
            "activation",
            "active_generation_unchanged_after_termination",
            before is not None
            and after_crash is not None
            and before["pointer"] == after_crash["pointer"]
            and before["semantic_sha256"]
            == after_crash["semantic_sha256"]
            and not candidate_final.exists()
            and candidate_staging.exists(),
            {
                "pointer": "baseline-g1",
                "candidate_final": False,
                "candidate_staging": True,
            },
            None
            if after_crash is None
            else {
                "pointer": after_crash["pointer"],
                "candidate_final": candidate_final.exists(),
                "candidate_staging": candidate_staging.exists(),
            },
        )
        case.require(
            "retry",
            "fresh_staging_retry_succeeds",
            after_retry is not None
            and after_retry["generation"] == 2
            and after_retry["semantic_sha256"]
            == retried["semantic_sha256"],
            {"generation": 2},
            None
            if after_retry is None
            else {"generation": after_retry["generation"]},
        )
        case.observe("process", process)

    _run_case(
        cases,
        work_root,
        "INTERRUPTED_RESTORE_BEFORE_ACTIVATION",
        "restore",
        "Termination after staging verification preserves the active generation; a fresh retry succeeds.",
        interrupted_restore,
    )

    def database_corruption(case: Case) -> None:
        case_root = work_root / "09-db-corruption"
        outer_bundle = _copy_bundle(
            shared["stable_bundle"],
            case_root / "outer-corrupt",
        )
        database_relative = str(
            load_json(outer_bundle / "manifest.json")["database"][
                "relative_path"
            ]
        )
        outer_database = outer_bundle.joinpath(
            *Path(database_relative).parts
        )
        _flip_byte(outer_database, 0)
        outer_error = _expected_error(lambda: verify_bundle(outer_bundle))

        inner_bundle = _copy_bundle(
            shared["stable_bundle"],
            case_root / "inner-corrupt",
        )
        inner_database = inner_bundle.joinpath(
            *Path(database_relative).parts
        )
        _flip_byte(inner_database, 0)
        refresh_member_integrity(inner_bundle, database_relative)
        before, after, inner_error = _preflight_preserves_active(
            inner_bundle,
            shared["baseline_bundle"],
            case_root / "install",
            "corrupt-g2",
        )
        case.require(
            "outer-checksum",
            "database_corruption_detected_by_member_checksum",
            outer_error["code"] == "MEMBER_CHECKSUM_MISMATCH",
            "MEMBER_CHECKSUM_MISMATCH",
            outer_error["code"],
        )
        case.require(
            "sqlite",
            "database_corruption_detected_after_outer_checksum_refresh",
            inner_error["code"] == "SQLITE_CORRUPT",
            "SQLITE_CORRUPT",
            inner_error["code"],
        )
        case.require(
            "activation",
            "corrupt_database_does_not_replace_active_generation",
            before["pointer"] == after["pointer"]
            and before["semantic_sha256"] == after["semantic_sha256"],
            {
                "pointer": before["pointer"],
                "semantic_sha256": before["semantic_sha256"],
            },
            {
                "pointer": after["pointer"],
                "semantic_sha256": after["semantic_sha256"],
            },
        )
        case.diagnostic(outer_error["code"], outer_error["detail"])
        case.diagnostic(inner_error["code"], inner_error["detail"])

    _run_case(
        cases,
        work_root,
        "DATABASE_HEADER_CORRUPTION",
        "sqlite",
        "Outer checksums and SQLite structural preflight independently reject a corrupt database.",
        database_corruption,
    )

    def missing_blob(case: Case) -> None:
        case_root = work_root / "10-missing-blob"
        candidate = _copy_bundle(
            shared["stable_bundle"],
            case_root / "candidate",
        )
        blob = _blob_member(candidate, largest=True)
        path = candidate.joinpath(*Path(blob["relative_path"]).parts)
        path.unlink()
        intact, total = _count_intact_other_blobs(
            candidate,
            str(blob["hash"]),
        )
        before, after, error = _preflight_preserves_active(
            candidate,
            shared["baseline_bundle"],
            case_root / "install",
            "missing-blob-g2",
        )
        case.require(
            "blob",
            "missing_blob_rejected",
            error["code"] == "MISSING_MEMBER",
            "MISSING_MEMBER",
            error["code"],
        )
        case.require(
            "failure-localization",
            "unaffected_blobs_remain_verifiable",
            intact == total and total > 0,
            total,
            intact,
        )
        case.require(
            "activation",
            "missing_blob_does_not_replace_active_generation",
            before["semantic_sha256"] == after["semantic_sha256"],
            before["semantic_sha256"],
            after["semantic_sha256"],
        )
        case.diagnostic(error["code"], error["detail"])

    _run_case(
        cases,
        work_root,
        "MISSING_BLOB_IN_BUNDLE",
        "blob",
        "A missing required blob is rejected without harming intact blobs or the active generation.",
        missing_blob,
    )

    def partial_blob(case: Case) -> None:
        case_root = work_root / "11-partial-blob"
        candidate = _copy_bundle(
            shared["stable_bundle"],
            case_root / "candidate",
        )
        blob = _blob_member(candidate, largest=True)
        relative_path = str(blob["relative_path"])
        path = candidate.joinpath(*Path(relative_path).parts)
        original_size = path.stat().st_size
        with path.open("r+b") as handle:
            handle.truncate(original_size // 2)
            handle.flush()
            os.fsync(handle.fileno())
        refresh_member_integrity(candidate, relative_path)
        intact, total = _count_intact_other_blobs(
            candidate,
            str(blob["hash"]),
        )
        before, after, error = _preflight_preserves_active(
            candidate,
            shared["baseline_bundle"],
            case_root / "install",
            "partial-blob-g2",
        )
        case.require(
            "blob",
            "partial_blob_rejected_by_manifest_size",
            error["code"] == "BLOB_SIZE_MISMATCH",
            "BLOB_SIZE_MISMATCH",
            error["code"],
        )
        case.require(
            "failure-localization",
            "other_blobs_intact_after_partial_fault",
            intact == total and total > 0,
            total,
            intact,
        )
        case.require(
            "activation",
            "partial_blob_does_not_replace_active_generation",
            before["semantic_sha256"] == after["semantic_sha256"],
            before["semantic_sha256"],
            after["semantic_sha256"],
        )
        case.observe(
            "sizes",
            {
                "expected_bytes": original_size,
                "partial_bytes": path.stat().st_size,
            },
        )
        case.diagnostic(error["code"], error["detail"])

    _run_case(
        cases,
        work_root,
        "PARTIAL_BLOB_IN_BUNDLE",
        "blob",
        "A truncated blob is rejected by manifest size after outer checksum refresh.",
        partial_blob,
    )

    def same_size_corrupt_blob(case: Case) -> None:
        case_root = work_root / "12-corrupt-blob"
        candidate = _copy_bundle(
            shared["stable_bundle"],
            case_root / "candidate",
        )
        blob = _blob_member(candidate, largest=True)
        relative_path = str(blob["relative_path"])
        path = candidate.joinpath(*Path(relative_path).parts)
        original_size = path.stat().st_size
        _flip_byte(path, max(0, original_size // 2))
        refresh_member_integrity(candidate, relative_path)
        intact, total = _count_intact_other_blobs(
            candidate,
            str(blob["hash"]),
        )
        before, after, error = _preflight_preserves_active(
            candidate,
            shared["baseline_bundle"],
            case_root / "install",
            "corrupt-blob-g2",
        )
        case.require(
            "blob",
            "same_size_corruption_rejected_by_content_hash",
            error["code"] == "BLOB_CONTENT_HASH_MISMATCH"
            and path.stat().st_size == original_size,
            {
                "code": "BLOB_CONTENT_HASH_MISMATCH",
                "size_bytes": original_size,
            },
            {
                "code": error["code"],
                "size_bytes": path.stat().st_size,
            },
        )
        case.require(
            "failure-localization",
            "other_blobs_intact_after_corruption",
            intact == total and total > 0,
            total,
            intact,
        )
        case.require(
            "activation",
            "corrupt_blob_does_not_replace_active_generation",
            before["semantic_sha256"] == after["semantic_sha256"],
            before["semantic_sha256"],
            after["semantic_sha256"],
        )
        case.diagnostic(error["code"], error["detail"])

    _run_case(
        cases,
        work_root,
        "SAME_SIZE_BLOB_CORRUPTION",
        "blob",
        "A same-size byte flip is rejected by content identity, not merely size.",
        same_size_corrupt_blob,
    )

    def source_blob_disappears(case: Case) -> None:
        case_root = work_root / "13-source-blob-missing"
        source_blob_root = case_root / "source" / "blobs"
        shutil.copytree(
            shared["generation_two_source"]["blob_root"],
            source_blob_root,
        )
        manifest = manifest_from_snapshot(shared["stable_snapshot"])
        victim = max(
            manifest["blobs"],
            key=lambda item: int(item["size_bytes"]),
        )
        victim_path = source_blob_root.parent.joinpath(
            *Path(victim["relative_path"]).parts
        )
        victim_path.unlink()
        staging = case_root / "bundle.staging"
        published = case_root / "bundle"
        error = _expected_error(
            lambda: create_bundle(
                shared["stable_snapshot"],
                source_blob_root,
                staging,
                published,
            )
        )
        rejection = _expected_error(lambda: verify_bundle(staging))
        snapshot_state = canonical_state(
            shared["stable_snapshot"],
            immutable=True,
        )
        case.require(
            "blob-lifetime",
            "missing_source_blob_blocks_publication",
            error["code"] == "SOURCE_BLOB_MISSING"
            and not published.exists()
            and not (staging / COMPLETE_NAME).exists(),
            {
                "error": "SOURCE_BLOB_MISSING",
                "published": False,
                "complete_marker": False,
            },
            {
                "error": error["code"],
                "published": published.exists(),
                "complete_marker": (staging / COMPLETE_NAME).exists(),
            },
        )
        case.require(
            "publication",
            "residual_stage_is_explicitly_incomplete",
            rejection["code"] == "BUNDLE_INCOMPLETE",
            "BUNDLE_INCOMPLETE",
            rejection["code"],
        )
        case.require(
            "sqlite",
            "snapshot_remains_healthy_after_copy_failure",
            snapshot_state["health"]["integrity_check"] == ["ok"],
            ["ok"],
            snapshot_state["health"]["integrity_check"],
        )
        case.diagnostic(error["code"], error["detail"])
        case.diagnostic(rejection["code"], rejection["detail"])

    _run_case(
        cases,
        work_root,
        "SOURCE_BLOB_DISAPPEARS_AFTER_SNAPSHOT",
        "db-blob-generation",
        "A source blob lost after the DB snapshot prevents publication and leaves an incomplete stage.",
        source_blob_disappears,
    )

    assertion_count = sum(len(case["checks"]) for case in cases)
    passed_assertions = sum(
        1
        for case in cases
        for check in case["checks"]
        if check["passed"]
    )
    passed_cases = sum(1 for case in cases if case["passed"])
    result = {
        "schema_version": 1,
        "task_id": "SPIKE-BACKUP-RESTORE-001",
        "artifact_id": "BACKUP-RESTORE-SPIKE-v1",
        "experimental_bundle": {
            "format_id": FORMAT_ID,
            "format_version": FORMAT_VERSION,
            "normative": False,
        },
        "fixture": {
            "id": fixture["fixture_id"],
            "path": "tests/spikes/backup-restore/fixtures/generation-v1.json",
            "sha256": sha256_file(FIXTURE_PATH),
            "generations": [
                int(item["generation"])
                for item in fixture["generations"]
            ],
        },
        "environment": {
            "os": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "sqlite_runtime": sqlite3.sqlite_version,
            "sqlite_compile_options": _compile_options(),
            "journal_mode": fixture["database"]["journal_mode"],
            "synchronous": fixture["database"]["synchronous"],
            "wal_autocheckpoint": fixture["database"][
                "wal_autocheckpoint"
            ],
        },
        "command": CANONICAL_COMMAND,
        "run": {
            "observed_at_utc": dt.datetime.now(dt.timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            "duration_ms": int((time.monotonic() - run_started) * 1000),
            "limits": limits,
            "temporary_paths_recorded": False,
        },
        "cases": cases,
        "summary": {
            "case_count": len(cases),
            "cases_passed": passed_cases,
            "cases_failed": len(cases) - passed_cases,
            "required_assertions": assertion_count,
            "assertions_passed": passed_assertions,
            "assertions_failed": assertion_count - passed_assertions,
            "passed": passed_cases == len(cases)
            and passed_assertions == assertion_count,
        },
        "limitations": [
            "The bundle and activation pointer are experimental and non-normative.",
            "No production encryption, key recovery, retention, purge, migration, or GC pin mechanism is implemented.",
            "The captured generation during a concurrent commit and backup progress callback counts are observations, not portable assertions.",
            "Process-level pointer replacement is not a claim of power-loss durability for directory metadata on Windows.",
            "SQLite 3.45.3 predates later WAL-reset fixes; automatic checkpoints are disabled and concurrent checkpoint/write stress is excluded.",
            "Exact SQLite corruption messages and residual partial-file shapes are version-dependent observations.",
        ],
    }
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Raw JSON observation path.",
    )
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(
            prefix="nabla-backup-restore-spike-"
        ) as temporary:
            work_root = Path(temporary)
            result = execute_measurement(work_root)
        result["run"]["temporary_cleanup_completed"] = True
    except BaseException as error:
        result = {
            "schema_version": 1,
            "task_id": "SPIKE-BACKUP-RESTORE-001",
            "artifact_id": "BACKUP-RESTORE-SPIKE-v1",
            "command": CANONICAL_COMMAND,
            "environment": {
                "os": platform.platform(),
                "machine": platform.machine(),
                "python": platform.python_version(),
                "sqlite_runtime": sqlite3.sqlite_version,
            },
            "run": {
                "observed_at_utc": dt.datetime.now(dt.timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
                "duration_ms": int((time.monotonic() - started) * 1000),
                "temporary_cleanup_completed": True,
            },
            "cases": [],
            "summary": {
                "passed": False,
                "fatal_error": f"{type(error).__name__}: {error}",
            },
        }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(arguments.output, result)
    summary = result["summary"]
    print(
        json.dumps(
            {
                "output": arguments.output.as_posix(),
                "passed": summary.get("passed", False),
                "cases": summary.get("case_count", 0),
                "cases_failed": summary.get("cases_failed", 0),
                "assertions": summary.get("required_assertions", 0),
                "assertions_failed": summary.get(
                    "assertions_failed",
                    0,
                ),
            },
            sort_keys=True,
        )
    )
    return 0 if summary.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
