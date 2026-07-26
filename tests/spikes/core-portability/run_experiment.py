"""Run the reproducible Core portability experiment and emit raw JSON evidence.

The harness is intentionally dependency-free. It builds the disposable Rust
probe in a temporary target directory, exercises both adapters, records exact
bounded subprocess observations, and returns non-zero when a required
assertion fails. Android is attempted only when the exact required local
toolchain is present; an unavailable build is recorded as a negative result,
not converted into runtime evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import struct
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from probe_environment import (
    collect_environment,
    run_bounded,
    sanitize_path,
    sanitize_text,
    sha256_file,
)


SCHEMA_VERSION = 1
HARNESS_TIMEOUT_SECONDS = 600.0
RUNTIME_TIMEOUT_SECONDS = 30.0
MAX_CAPTURE_BYTES = 256 * 1024
ANDROID_TARGET = "aarch64-linux-android"
ANDROID_ABI = "arm64-v8a"

PROBE_ROOT = Path(__file__).resolve().parent
CRATE_ROOT = PROBE_ROOT / "rust-probe"
MANIFEST_PATH = CRATE_ROOT / "Cargo.toml"
REPOSITORY_ROOT = PROBE_ROOT.parents[2]

EXPECTED_EMPTY_COUNTS = {
    "facts": 0,
    "idempotency": 0,
    "audit": 0,
    "outbox": 0,
}
EXPECTED_ONE_COUNTS = {
    "facts": 1,
    "idempotency": 1,
    "audit": 1,
    "outbox": 1,
}
EXPECTED_TWO_COUNTS = {
    "facts": 2,
    "idempotency": 2,
    "audit": 2,
    "outbox": 2,
}


def _normalize_text(value: str, work_root: Path) -> str:
    sanitized = sanitize_text(value)
    work_spellings = {
        sanitize_path(work_root),
        sanitize_path(work_root).replace("/", "\\"),
    }
    for spelling in sorted(work_spellings, key=len, reverse=True):
        sanitized = sanitized.replace(spelling, "<WORK>")
    return sanitized


def _normalize_value(value: object, work_root: Path) -> object:
    if isinstance(value, str):
        return _normalize_text(value, work_root)
    if isinstance(value, list):
        return [_normalize_value(item, work_root) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _normalize_value(item, work_root)
            for key, item in value.items()
        }
    return value


def _run_command(
    argv: Sequence[str | os.PathLike[str]],
    *,
    work_root: Path,
    timeout_seconds: float = HARNESS_TIMEOUT_SECONDS,
    stdin_bytes: bytes | None = None,
    env_overrides: Mapping[str, str] | None = None,
    cwd: Path = REPOSITORY_ROOT,
) -> dict[str, object]:
    observation = run_bounded(
        argv,
        timeout_seconds=timeout_seconds,
        max_output_bytes=MAX_CAPTURE_BYTES,
        stdin_bytes=stdin_bytes,
        cwd=cwd,
        env_overrides=env_overrides,
    )
    normalized = _normalize_value(observation, work_root)
    if not isinstance(normalized, dict):
        raise AssertionError("normalized command observation is not a mapping")
    return normalized


def _command_passed(observation: Mapping[str, object]) -> bool:
    return (
        observation.get("status") == "completed"
        and observation.get("exit_code") == 0
        and observation.get("capture_complete") is True
        and observation.get("input_complete") is True
    )


def _stream_text(
    observation: Mapping[str, object],
    stream_name: str = "stdout",
) -> str:
    stream = observation.get(stream_name)
    if not isinstance(stream, dict):
        return ""
    text = stream.get("text")
    if isinstance(text, str):
        return text
    preview = stream.get("preview")
    return preview if isinstance(preview, str) else ""


def _request_payload(requests: Sequence[Mapping[str, object]]) -> bytes:
    lines = [
        json.dumps(request, separators=(",", ":"), sort_keys=True)
        for request in requests
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _parse_json_lines(observation: Mapping[str, object]) -> list[object]:
    text = _stream_text(observation)
    if not text:
        return []
    parsed: list[object] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            parsed.append(json.loads(line))
        except json.JSONDecodeError:
            parsed.append({"unparsed_line": line})
    return parsed


def _run_service(
    service_path: Path,
    database_path: Path,
    requests: Sequence[Mapping[str, object]],
    *,
    work_root: Path,
) -> dict[str, object]:
    observation = _run_command(
        [service_path, "--db", database_path],
        work_root=work_root,
        timeout_seconds=RUNTIME_TIMEOUT_SECONDS,
        stdin_bytes=_request_payload(requests),
        cwd=work_root,
    )
    observation["requests"] = list(requests)
    observation["responses"] = _parse_json_lines(observation)
    return observation


def _response_code(response: object) -> str | None:
    if not isinstance(response, dict):
        return None
    value = response.get("code")
    return value if isinstance(value, str) else None


def _response_counts(response: object) -> dict[str, object] | None:
    if not isinstance(response, dict):
        return None
    value = response.get("counts")
    return value if isinstance(value, dict) else None


def _response_integrity(response: object) -> str | None:
    if not isinstance(response, dict):
        return None
    value = response.get("integrity")
    return value if isinstance(value, str) else None


def _record_assertion(
    assertions: list[dict[str, object]],
    assertion_id: str,
    condition: bool,
    detail: str,
    evidence: Sequence[str],
    *,
    required: bool = True,
) -> None:
    assertions.append(
        {
            "id": assertion_id,
            "required": required,
            "passed": bool(condition),
            "detail": detail,
            "evidence": list(evidence),
        }
    )


def _host_artifact_paths(target_root: Path) -> tuple[Path, Path]:
    release = target_root / "release"
    if os.name == "nt":
        return (
            release / "nabla-core-probe-service.exe",
            release / "nabla_core_portability_probe.dll",
        )
    if sys.platform == "darwin":
        return (
            release / "nabla-core-probe-service",
            release / "libnabla_core_portability_probe.dylib",
        )
    return (
        release / "nabla-core-probe-service",
        release / "libnabla_core_portability_probe.so",
    )


def _binary_format(path: Path) -> dict[str, object]:
    data = path.read_bytes()[:4096]
    result: dict[str, object] = {"format": "unknown"}
    if data.startswith(b"MZ") and len(data) >= 64:
        pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
        with path.open("rb") as stream:
            stream.seek(pe_offset)
            header = stream.read(6)
        if len(header) == 6 and header[:4] == b"PE\0\0":
            machine = struct.unpack_from("<H", header, 4)[0]
            result = {
                "format": "PE",
                "machine": {
                    0x014C: "x86",
                    0x8664: "x86_64",
                    0xAA64: "aarch64",
                }.get(machine, f"0x{machine:04x}"),
            }
    elif data.startswith(b"\x7fELF") and len(data) >= 20:
        byte_order = "<" if data[5] == 1 else ">"
        machine = struct.unpack_from(f"{byte_order}H", data, 18)[0]
        result = {
            "format": "ELF",
            "class": {1: "32-bit", 2: "64-bit"}.get(data[4], data[4]),
            "endianness": {1: "little", 2: "big"}.get(data[5], data[5]),
            "machine": {
                0x03: "x86",
                0x3E: "x86_64",
                0xB7: "aarch64",
            }.get(machine, f"0x{machine:04x}"),
        }
    elif data[:4] in {
        b"\xfe\xed\xfa\xce",
        b"\xce\xfa\xed\xfe",
        b"\xfe\xed\xfa\xcf",
        b"\xcf\xfa\xed\xfe",
    }:
        result = {"format": "Mach-O"}
    return result


def _artifact_fact(path: Path, work_root: Path) -> dict[str, object]:
    return {
        "path": _normalize_text(str(path), work_root).replace("\\", "/"),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "binary": _binary_format(path),
    }


def _dependency_observation(
    path: Path,
    *,
    work_root: Path,
) -> dict[str, object]:
    candidates: list[tuple[str, list[str]]] = []
    if os.name == "nt":
        candidates.extend(
            [
                ("dumpbin", ["/DEPENDENTS", str(path)]),
                ("llvm-objdump", ["-p", str(path)]),
                ("objdump", ["-p", str(path)]),
            ]
        )
    elif sys.platform == "darwin":
        candidates.append(("otool", ["-L", str(path)]))
    else:
        candidates.append(("ldd", [str(path)]))

    discoveries: list[dict[str, object]] = []
    attempts: list[dict[str, object]] = []
    for name, arguments in candidates:
        executable = shutil.which(name)
        discoveries.append(
            {
                "name": name,
                "available": executable is not None,
            }
        )
        if executable is not None:
            command = _run_command(
                [executable, *arguments],
                work_root=work_root,
                timeout_seconds=RUNTIME_TIMEOUT_SECONDS,
            )
            attempts.append({"tool": name, "command": command})
            if _command_passed(command):
                return {
                    "status": "observed",
                    "tool": name,
                    "discoveries": discoveries,
                    "attempts": attempts,
                    "command": command,
                }
    return {
        "status": "failed" if attempts else "unavailable",
        "tool": None,
        "discoveries": discoveries,
        "attempts": attempts,
        "command": None,
    }


def _source_inventory() -> list[dict[str, object]]:
    relative_paths = [
        "probe_environment.py",
        "ffi_driver.py",
        "run_experiment.py",
        "rust-probe/.gitignore",
        "rust-probe/Cargo.toml",
        "rust-probe/Cargo.lock",
        "rust-probe/README.md",
        "rust-probe/include/nabla_core_probe.h",
        "rust-probe/src/core.rs",
        "rust-probe/src/lib.rs",
        "rust-probe/src/bin/service.rs",
    ]
    return [
        {
            "path": f"tests/spikes/core-portability/{relative_path}",
            "size_bytes": (PROBE_ROOT / relative_path).stat().st_size,
            "sha256": sha256_file(PROBE_ROOT / relative_path),
        }
        for relative_path in relative_paths
    ]


def _parse_single_json(observation: Mapping[str, object]) -> dict[str, object] | None:
    text = _stream_text(observation)
    if not text:
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _android_case(
    environment: Mapping[str, object],
    cargo_path: str,
    *,
    work_root: Path,
    target_root: Path,
    offline: bool,
) -> dict[str, object]:
    rust = environment.get("rust")
    android = environment.get("android")
    installed_targets: list[object] = []
    cargo_ndk_available = False
    if isinstance(rust, dict):
        value = rust.get("installed_targets")
        if isinstance(value, list):
            installed_targets = value
        cargo_ndk = rust.get("cargo_ndk")
        if isinstance(cargo_ndk, dict):
            cargo_ndk_available = cargo_ndk.get("available") is True

    ndk_packages: list[object] = []
    if isinstance(android, dict):
        packages = android.get("packages")
        if isinstance(packages, dict):
            ndk_value = packages.get("ndk")
            if isinstance(ndk_value, list):
                ndk_packages = ndk_value

    blockers: list[str] = []
    if ANDROID_TARGET not in installed_targets:
        blockers.append(f"rust target {ANDROID_TARGET} is not installed")
    if not cargo_ndk_available:
        blockers.append("cargo-ndk is not available")
    if not ndk_packages:
        blockers.append("Android NDK package is not available")

    if blockers:
        return {
            "classification": "UNAVAILABLE",
            "target": ANDROID_TARGET,
            "abi": ANDROID_ABI,
            "blockers": blockers,
            "command": None,
            "artifacts": [],
            "runtime_exercised": False,
        }

    android_target_root = target_root / "android"
    command_argv: list[str | os.PathLike[str]] = [
        cargo_path,
        "ndk",
        "-t",
        ANDROID_ABI,
        "-P",
        "21",
        "-o",
        work_root / "android-jni",
        "--manifest-path",
        MANIFEST_PATH,
        "build",
        "--release",
        "--locked",
    ]
    if offline:
        command_argv.append("--offline")
    command_argv.append("--lib")
    command = _run_command(
        command_argv,
        work_root=work_root,
        cwd=CRATE_ROOT,
        env_overrides={
            "CARGO_TARGET_DIR": str(android_target_root),
            "CARGO_INCREMENTAL": "0",
            "CARGO_TERM_COLOR": "never",
        },
    )
    library = (
        android_target_root
        / ANDROID_TARGET
        / "release"
        / "libnabla_core_portability_probe.so"
    )
    artifacts = (
        [_artifact_fact(library, work_root)]
        if _command_passed(command) and library.is_file()
        else []
    )
    dynamic_dependencies = (
        _dependency_observation(library, work_root=work_root)
        if artifacts
        else None
    )
    return {
        "classification": (
            "BUILD-ONLY"
            if _command_passed(command) and artifacts
            else "FAILED"
        ),
        "target": ANDROID_TARGET,
        "abi": ANDROID_ABI,
        "blockers": [],
        "command": command,
        "artifacts": artifacts,
        "dynamic_dependencies": dynamic_dependencies,
        "runtime_exercised": False,
    }


def _run_measurements(work_root: Path, *, offline: bool) -> dict[str, object]:
    target_root = work_root / "target"
    database_root = work_root / "databases"
    database_root.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    environment = collect_environment()
    cargo_path = shutil.which("cargo")
    assertions: list[dict[str, object]] = []
    commands: dict[str, object] = {}

    if cargo_path is None:
        _record_assertion(
            assertions,
            "TOOL-CARGO-AVAILABLE",
            False,
            "cargo is required to build the candidate probe",
            ["environment.executables.cargo"],
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "task_id": "SPIKE-CORE-PORTABILITY-001",
            "started_at_utc": started_at,
            "completed_at_utc": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "environment": environment,
            "commands": commands,
            "cases": {},
            "assertions": assertions,
            "source_inventory": _source_inventory(),
            "overall_status": "failed",
        }

    build_environment = {
        "CARGO_TARGET_DIR": str(target_root),
        "CARGO_INCREMENTAL": "0",
        "CARGO_TERM_COLOR": "never",
    }
    commands["python_self_test"] = _run_command(
        [sys.executable, PROBE_ROOT / "probe_environment.py", "--self-test"],
        work_root=work_root,
        timeout_seconds=RUNTIME_TIMEOUT_SECONDS,
    )
    commands["cargo_fmt"] = _run_command(
        [
            cargo_path,
            "fmt",
            "--manifest-path",
            MANIFEST_PATH,
            "--",
            "--check",
        ],
        work_root=work_root,
        timeout_seconds=RUNTIME_TIMEOUT_SECONDS,
    )
    cargo_test_argv: list[str | os.PathLike[str]] = [
        cargo_path,
        "test",
        "--manifest-path",
        MANIFEST_PATH,
        "--locked",
    ]
    if offline:
        cargo_test_argv.append("--offline")
    commands["cargo_test"] = _run_command(
        cargo_test_argv,
        work_root=work_root,
        env_overrides=build_environment,
    )
    cargo_build_argv: list[str | os.PathLike[str]] = [
        cargo_path,
        "build",
        "--manifest-path",
        MANIFEST_PATH,
        "--release",
        "--locked",
    ]
    if offline:
        cargo_build_argv.append("--offline")
    commands["cargo_build_release"] = _run_command(
        cargo_build_argv,
        work_root=work_root,
        env_overrides=build_environment,
    )
    cargo_metadata_argv: list[str | os.PathLike[str]] = [
        cargo_path,
        "metadata",
        "--manifest-path",
        MANIFEST_PATH,
        "--locked",
        "--format-version",
        "1",
        "--no-deps",
    ]
    if offline:
        cargo_metadata_argv.append("--offline")
    commands["cargo_metadata"] = _run_command(
        cargo_metadata_argv,
        work_root=work_root,
        timeout_seconds=RUNTIME_TIMEOUT_SECONDS,
        env_overrides=build_environment,
    )
    cargo_tree_argv: list[str | os.PathLike[str]] = [
        cargo_path,
        "tree",
        "--manifest-path",
        MANIFEST_PATH,
        "--locked",
    ]
    if offline:
        cargo_tree_argv.append("--offline")
    commands["cargo_tree"] = _run_command(
        cargo_tree_argv,
        work_root=work_root,
        timeout_seconds=RUNTIME_TIMEOUT_SECONDS,
        env_overrides=build_environment,
    )

    for name in (
        "python_self_test",
        "cargo_fmt",
        "cargo_test",
        "cargo_build_release",
        "cargo_metadata",
        "cargo_tree",
    ):
        observation = commands[name]
        _record_assertion(
            assertions,
            f"TOOL-{name.upper().replace('_', '-')}",
            isinstance(observation, dict) and _command_passed(observation),
            f"{name} completed successfully",
            [f"commands.{name}"],
        )

    service_path, library_path = _host_artifact_paths(target_root)
    build_ready = (
        isinstance(commands["cargo_build_release"], dict)
        and _command_passed(commands["cargo_build_release"])
        and service_path.is_file()
        and library_path.is_file()
    )
    _record_assertion(
        assertions,
        "PACKAGE-HOST-ARTIFACTS",
        build_ready,
        "release service and C ABI library exist for the host",
        ["commands.cargo_build_release", "cases.PACKAGE-001.artifacts"],
    )

    cases: dict[str, object] = {}
    if build_ready:
        desktop_initial_requests = [
            {"op": "inspect"},
            {
                "op": "apply",
                "request_id": "shared-request",
                "fact_id": "shared-fact",
                "value": "alpha",
            },
            {
                "op": "apply",
                "request_id": "shared-request",
                "fact_id": "shared-fact",
                "value": "alpha",
            },
            {"op": "inspect"},
            {"op": "panic_probe"},
            {"op": "integrity"},
        ]
        desktop_database = database_root / "desktop.sqlite3"
        desktop_initial = _run_service(
            service_path,
            desktop_database,
            desktop_initial_requests,
            work_root=work_root,
        )
        desktop_reopen = _run_service(
            service_path,
            desktop_database,
            [{"op": "inspect"}],
            work_root=work_root,
        )

        rollback_requests: list[dict[str, object]] = [{"op": "inspect"}]
        for stage in (
            "after_fact",
            "after_idempotency",
            "after_audit",
            "after_outbox",
        ):
            rollback_requests.extend(
                [
                    {
                        "op": "apply",
                        "request_id": f"rollback-{stage}",
                        "fact_id": f"rollback-{stage}",
                        "value": "rollback",
                        "inject_failure": stage,
                    },
                    {"op": "inspect"},
                ]
            )
        rollback_database = database_root / "rollback.sqlite3"
        rollback = _run_service(
            service_path,
            rollback_database,
            rollback_requests,
            work_root=work_root,
        )
        rollback_reopen = _run_service(
            service_path,
            rollback_database,
            [{"op": "inspect"}],
            work_root=work_root,
        )

        crash_database = database_root / "crash.sqlite3"
        crash = _run_service(
            service_path,
            crash_database,
            [
                {
                    "op": "apply",
                    "request_id": "baseline",
                    "fact_id": "baseline",
                    "value": "committed",
                },
                {
                    "op": "crash_probe",
                    "request_id": "crashed-command",
                    "fact_id": "crashed-command",
                    "value": "must-rollback",
                    "crash_after": "after_outbox",
                },
            ],
            work_root=work_root,
        )
        crash_reopen = _run_service(
            service_path,
            crash_database,
            [
                {"op": "inspect"},
                {
                    "op": "apply",
                    "request_id": "crashed-command",
                    "fact_id": "crashed-command",
                    "value": "recovered",
                },
                {"op": "inspect"},
            ],
            work_root=work_root,
        )

        ffi_driver = _run_command(
            [
                sys.executable,
                PROBE_ROOT / "ffi_driver.py",
                "--library",
                library_path,
                "--db",
                database_root / "embedded.sqlite3",
            ],
            work_root=work_root,
            timeout_seconds=RUNTIME_TIMEOUT_SECONDS,
        )
        ffi_result = _parse_single_json(ffi_driver)

        desktop_responses = desktop_initial.get("responses")
        desktop_reopen_responses = desktop_reopen.get("responses")
        rollback_responses = rollback.get("responses")
        rollback_reopen_responses = rollback_reopen.get("responses")
        crash_responses = crash.get("responses")
        crash_reopen_responses = crash_reopen.get("responses")

        desktop_semantics = (
            _command_passed(desktop_initial)
            and isinstance(desktop_responses, list)
            and len(desktop_responses) == 6
            and _response_counts(desktop_responses[0]) == EXPECTED_EMPTY_COUNTS
            and _response_code(desktop_responses[1]) == "APPLIED"
            and _response_code(desktop_responses[2]) == "REPLAYED"
            and _response_counts(desktop_responses[3]) == EXPECTED_ONE_COUNTS
            and _response_code(desktop_responses[4]) == "PANIC_CONTAINED"
            and _response_integrity(desktop_responses[5]) == "ok"
        )
        _record_assertion(
            assertions,
            "DESKTOP-COMMAND-SEMANTICS",
            desktop_semantics,
            "process adapter applies, replays, inspects and survives a contained panic",
            ["cases.DESKTOP-001.initial"],
        )
        _record_assertion(
            assertions,
            "SQLITE-COMMIT-REOPEN",
            _command_passed(desktop_reopen)
            and isinstance(desktop_reopen_responses, list)
            and len(desktop_reopen_responses) == 1
            and _response_counts(desktop_reopen_responses[0])
            == EXPECTED_ONE_COUNTS
            and _response_integrity(desktop_reopen_responses[0]) == "ok",
            "committed command is durable and integral after process restart",
            ["cases.DESKTOP-001.reopen"],
        )

        rollback_ok = (
            _command_passed(rollback)
            and isinstance(rollback_responses, list)
            and len(rollback_responses) == 9
            and _response_counts(rollback_responses[0]) == EXPECTED_EMPTY_COUNTS
        )
        if rollback_ok and isinstance(rollback_responses, list):
            for offset in (1, 3, 5, 7):
                rollback_ok = rollback_ok and (
                    _response_code(rollback_responses[offset])
                    == "INJECTED_FAILURE"
                    and _response_counts(rollback_responses[offset + 1])
                    == EXPECTED_EMPTY_COUNTS
                )
        rollback_ok = rollback_ok and (
            _command_passed(rollback_reopen)
            and isinstance(rollback_reopen_responses, list)
            and len(rollback_reopen_responses) == 1
            and _response_counts(rollback_reopen_responses[0])
            == EXPECTED_EMPTY_COUNTS
            and _response_integrity(rollback_reopen_responses[0]) == "ok"
        )
        _record_assertion(
            assertions,
            "SQLITE-ROLLBACK-ALL-STAGES",
            rollback_ok,
            "all four injected pre-commit stages leave no partial rows before or after reopen",
            ["cases.SQLITE-001.rollback", "cases.SQLITE-001.rollback_reopen"],
        )

        crash_exit = crash.get("exit_code")
        crash_ok = (
            crash.get("status") == "completed"
            and isinstance(crash_exit, int)
            and crash_exit != 0
            and crash.get("timed_out") is False
            and crash.get("capture_complete") is True
            and crash.get("input_complete") is True
            and isinstance(crash_responses, list)
            and len(crash_responses) == 1
            and _response_code(crash_responses[0]) == "APPLIED"
            and _command_passed(crash_reopen)
            and isinstance(crash_reopen_responses, list)
            and len(crash_reopen_responses) == 3
            and _response_counts(crash_reopen_responses[0])
            == EXPECTED_ONE_COUNTS
            and _response_integrity(crash_reopen_responses[0]) == "ok"
            and _response_code(crash_reopen_responses[1]) == "APPLIED"
            and _response_counts(crash_reopen_responses[2])
            == EXPECTED_TWO_COUNTS
        )
        _record_assertion(
            assertions,
            "PROCESS-CRASH-RECOVERY",
            crash_ok,
            "abrupt child termination rolls back the in-flight transaction and permits restart",
            ["cases.FAILURE-001.crash", "cases.FAILURE-001.crash_reopen"],
        )

        ffi_assertions = (
            ffi_result.get("assertions")
            if isinstance(ffi_result, dict)
            else None
        )
        ffi_ok = (
            _command_passed(ffi_driver)
            and isinstance(ffi_result, dict)
            and ffi_result.get("overall_status") == "passed"
            and isinstance(ffi_assertions, list)
            and all(
                isinstance(item, dict) and item.get("passed") is True
                for item in ffi_assertions
            )
        )
        _record_assertion(
            assertions,
            "FFI-EMBEDDED-SHAPE",
            ffi_ok,
            "actual C ABI preserves command, rollback, panic and reopen behavior",
            ["cases.FFI-001.driver", "cases.FFI-001.result"],
        )

        ffi_calls = ffi_result.get("calls") if isinstance(ffi_result, dict) else None
        shared_responses_match = False
        if (
            isinstance(desktop_responses, list)
            and len(desktop_responses) == 6
            and isinstance(ffi_calls, list)
            and len(ffi_calls) == 7
            and all(isinstance(item, dict) for item in ffi_calls)
        ):
            shared_responses_match = all(
                desktop_responses[desktop_index]
                == ffi_calls[ffi_index].get("response")
                for desktop_index, ffi_index in (
                    (0, 0),
                    (1, 1),
                    (2, 2),
                    (3, 4),
                    (5, 6),
                )
            )
        _record_assertion(
            assertions,
            "SHARED-COMMAND-MEANING",
            desktop_semantics and ffi_ok and shared_responses_match,
            "full typed inspect/apply/replay/post-state/integrity responses match across process and FFI adapters",
            ["cases.DESKTOP-001.initial", "cases.FFI-001.result"],
        )

        artifacts = [
            _artifact_fact(service_path, work_root),
            _artifact_fact(library_path, work_root),
        ]
        dependency_observations = {
            "service": _dependency_observation(service_path, work_root=work_root),
            "library": _dependency_observation(library_path, work_root=work_root),
        }
        _record_assertion(
            assertions,
            "PACKAGE-DEPENDENCY-OBSERVATION",
            all(
                observation.get("status") == "observed"
                for observation in dependency_observations.values()
            ),
            "native dependency inspection completed for the host service and C ABI library",
            ["cases.PACKAGE-001.dynamic_dependencies"],
        )
        cases.update(
            {
                "DESKTOP-001": {
                    "classification": "OBSERVED",
                    "initial": desktop_initial,
                    "reopen": desktop_reopen,
                },
                "EMBED-001": {
                    "classification": (
                        "OBSERVED" if ffi_ok else "FAILED"
                    ),
                    "host_shape": "Python ctypes host loading the Rust C ABI",
                    "mobile_runtime_exercised": False,
                },
                "SQLITE-001": {
                    "classification": (
                        "OBSERVED" if rollback_ok else "FAILED"
                    ),
                    "rollback": rollback,
                    "rollback_reopen": rollback_reopen,
                },
                "FAILURE-001": {
                    "classification": (
                        "OBSERVED" if crash_ok and ffi_ok else "FAILED"
                    ),
                    "crash": crash,
                    "crash_reopen": crash_reopen,
                    "crash_working_directory": "<WORK>",
                    "core_dump_cleanup": "covered by temporary work-root cleanup",
                    "ffi_panic_reference": "cases.FFI-001.result.calls[5]",
                },
                "IPC-001": {
                    "classification": (
                        "OBSERVED" if desktop_semantics else "FAILED"
                    ),
                    "transport": "bounded NDJSON over child stdin/stdout",
                    "security_boundary_proven": False,
                    "observation_reference": "cases.DESKTOP-001.initial",
                },
                "FFI-001": {
                    "classification": "OBSERVED" if ffi_ok else "FAILED",
                    "driver": ffi_driver,
                    "result": ffi_result,
                },
                "PACKAGE-001": {
                    "classification": "OBSERVED",
                    "artifacts": artifacts,
                    "dynamic_dependencies": dependency_observations,
                    "cargo_metadata_reference": "commands.cargo_metadata",
                    "cargo_tree_reference": "commands.cargo_tree",
                },
            }
        )
    else:
        for assertion_id, detail in (
            (
                "DESKTOP-COMMAND-SEMANTICS",
                "host release artifacts were unavailable",
            ),
            ("SQLITE-COMMIT-REOPEN", "host release artifacts were unavailable"),
            (
                "SQLITE-ROLLBACK-ALL-STAGES",
                "host release artifacts were unavailable",
            ),
            ("PROCESS-CRASH-RECOVERY", "host release artifacts were unavailable"),
            ("FFI-EMBEDDED-SHAPE", "host release artifacts were unavailable"),
            ("SHARED-COMMAND-MEANING", "host release artifacts were unavailable"),
        ):
            _record_assertion(
                assertions,
                assertion_id,
                False,
                detail,
                ["commands.cargo_build_release"],
            )

    android_case = _android_case(
        environment,
        cargo_path,
        work_root=work_root,
        target_root=target_root,
        offline=offline,
    )
    cases["ANDROID-BUILD-001"] = android_case
    _record_assertion(
        assertions,
        "ANDROID-CASE-CLASSIFIED",
        android_case.get("classification")
        in {"BUILD-ONLY", "UNAVAILABLE", "FAILED"},
        "Android is classified from direct local toolchain evidence without a runtime claim",
        ["environment.android", "environment.rust", "cases.ANDROID-BUILD-001"],
    )

    cases["TOOL-001"] = {
        "classification": (
            "OBSERVED"
            if all(
                isinstance(commands.get(name), dict)
                and _command_passed(commands[name])  # type: ignore[arg-type]
                for name in (
                    "python_self_test",
                    "cargo_fmt",
                    "cargo_test",
                    "cargo_build_release",
                    "cargo_metadata",
                    "cargo_tree",
                )
            )
            else "FAILED"
        ),
        "commands_reference": "commands",
        "environment_reference": "environment",
        "timeout_seconds": HARNESS_TIMEOUT_SECONDS,
        "max_capture_bytes_per_stream": MAX_CAPTURE_BYTES,
        "shell_invocation": False,
    }

    required_assertions = [
        item for item in assertions if item.get("required") is True
    ]
    overall_status = (
        "passed"
        if required_assertions
        and all(item.get("passed") is True for item in required_assertions)
        else "failed"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": "SPIKE-CORE-PORTABILITY-001",
        "artifact_id": "CORE-PORTABILITY-SPIKE-v1",
        "started_at_utc": started_at,
        "completed_at_utc": datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "host_summary": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "limits": {
            "command_timeout_seconds": HARNESS_TIMEOUT_SECONDS,
            "runtime_timeout_seconds": RUNTIME_TIMEOUT_SECONDS,
            "max_capture_bytes_per_stream": MAX_CAPTURE_BYTES,
            "max_stdin_bytes": 1024 * 1024,
            "android_api_level": 21,
        },
        "network": {
            "runtime_cases_require_network": False,
            "cargo_commands_ran_offline": offline,
            "cargo_build_may_require_registry_access_on_an_uncached_host": not offline,
        },
        "run_configuration": {
            "offline": offline,
            "cargo_incremental": False,
            "cargo_term_color": "never",
        },
        "environment": environment,
        "commands": commands,
        "cases": cases,
        "assertions": assertions,
        "source_inventory": _source_inventory(),
        "cleanup": {
            "work_root": "<WORK>",
            "policy": "temporary build products and fixture databases are removed when the runner exits",
        },
        "overall_status": overall_status,
    }


def _render_json(result: Mapping[str, object]) -> str:
    return json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _write_output(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _contains_private_path(content: str) -> bool:
    candidates = {
        str(Path.home()),
        str(REPOSITORY_ROOT),
        str(PROBE_ROOT),
    }
    lowered = content.casefold()
    return any(candidate.casefold() in lowered for candidate in candidates)


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="require all Cargo commands to use the existing local cache",
    )
    arguments = parser.parse_args(argv)

    try:
        work_root: Path | None = None
        with tempfile.TemporaryDirectory(prefix="nabla-core-portability-") as raw_work:
            work_root = Path(raw_work)
            result = _run_measurements(work_root, offline=arguments.offline)

        cleanup_succeeded = work_root is not None and not work_root.exists()
        cleanup = result.get("cleanup")
        if isinstance(cleanup, dict):
            cleanup.update(
                {
                    "attempted": True,
                    "succeeded": cleanup_succeeded,
                    "residual_paths": [] if cleanup_succeeded else ["<WORK>"],
                }
            )
        assertions = result.get("assertions")
        if isinstance(assertions, list):
            _record_assertion(
                assertions,
                "HARNESS-TEMP-CLEANUP",
                cleanup_succeeded,
                "temporary build products and fixture databases were removed",
                ["cleanup"],
            )

        rendered = _render_json(result)
        path_sanitized = not _contains_private_path(rendered)
        if isinstance(assertions, list):
            _record_assertion(
                assertions,
                "EVIDENCE-PATH-SANITIZATION",
                path_sanitized,
                (
                    "structured result contains no home or repository absolute path"
                    if path_sanitized
                    else "structured result contains a private host or repository path"
                ),
                ["structured result"],
            )
        rendered = _render_json(result)
        result_size_bounded = len(rendered.encode("utf-8")) <= 4 * 1024 * 1024
        if isinstance(assertions, list):
            _record_assertion(
                assertions,
                "EVIDENCE-SIZE-BOUND",
                result_size_bounded,
                "structured result is bounded to at most 4 MiB",
                ["structured result"],
            )
            required = [
                item
                for item in assertions
                if isinstance(item, dict) and item.get("required") is True
            ]
            result["overall_status"] = (
                "passed"
                if required
                and all(item.get("passed") is True for item in required)
                else "failed"
            )
        rendered = _render_json(result)
    except Exception as error:  # noqa: BLE001 - raw spike evidence
        traceback.print_exc(file=sys.stderr)
        result = {
            "schema_version": SCHEMA_VERSION,
            "task_id": "SPIKE-CORE-PORTABILITY-001",
            "overall_status": "failed",
            "fatal_error": sanitize_text(f"{type(error).__name__}: {error}"),
        }
        rendered = _render_json(result)

    output_path = arguments.output.resolve()
    _write_output(output_path, rendered)
    output_sha256 = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    summary = {
        "overall_status": result.get("overall_status"),
        "output": sanitize_path(output_path),
        "output_sha256": output_sha256,
    }
    print(json.dumps(summary, sort_keys=True))
    return 0 if result.get("overall_status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(_main())
