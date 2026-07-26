"""Exercise the disposable Rust Core probe through its real C ABI.

This process is an Embedded Core-shaped host for SPIKE-CORE-PORTABILITY-001.
It never opens the SQLite database itself; all persistence access occurs behind
the opaque Rust handle.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import sys
import traceback
from pathlib import Path
from typing import Sequence


FFI_OK = 0
FFI_BUFFER_TOO_SMALL = 5
FFI_PANIC = 7
EXPECTED_ABI_VERSION = 1
EXPECTED_MAX_REQUEST_BYTES = 64 * 1024

BytePointer = ctypes.POINTER(ctypes.c_uint8)
NullBytePointer = BytePointer()


class ProbeLibrary:
    def __init__(self, library_path: Path) -> None:
        self.library = ctypes.CDLL(str(library_path))
        self.library.nabla_core_probe_abi_version.argtypes = []
        self.library.nabla_core_probe_abi_version.restype = ctypes.c_uint32
        self.library.nabla_core_probe_max_request_bytes.argtypes = []
        self.library.nabla_core_probe_max_request_bytes.restype = ctypes.c_size_t
        self.library.nabla_core_probe_open.argtypes = [
            BytePointer,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self.library.nabla_core_probe_open.restype = ctypes.c_int32
        self.library.nabla_core_probe_execute.argtypes = [
            ctypes.c_void_p,
            BytePointer,
            ctypes.c_size_t,
            BytePointer,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        self.library.nabla_core_probe_execute.restype = ctypes.c_int32
        self.library.nabla_core_probe_close.argtypes = [ctypes.c_void_p]
        self.library.nabla_core_probe_close.restype = ctypes.c_int32

    def abi_version(self) -> int:
        return int(self.library.nabla_core_probe_abi_version())

    def max_request_bytes(self) -> int:
        return int(self.library.nabla_core_probe_max_request_bytes())

    def open(self, database_path: Path) -> tuple[int, ctypes.c_void_p]:
        path_bytes = str(database_path).encode("utf-8")
        path_buffer = (ctypes.c_uint8 * len(path_bytes)).from_buffer_copy(path_bytes)
        handle = ctypes.c_void_p()
        status = int(
            self.library.nabla_core_probe_open(
                path_buffer,
                len(path_bytes),
                ctypes.byref(handle),
            )
        )
        return status, handle

    def execute(
        self,
        handle: ctypes.c_void_p,
        request: dict[str, object],
    ) -> dict[str, object]:
        request_bytes = json.dumps(
            request,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        request_buffer = (ctypes.c_uint8 * len(request_bytes)).from_buffer_copy(
            request_bytes
        )
        required = ctypes.c_size_t()
        sizing_status = int(
            self.library.nabla_core_probe_execute(
                handle,
                request_buffer,
                len(request_bytes),
                NullBytePointer,
                0,
                ctypes.byref(required),
            )
        )

        observation: dict[str, object] = {
            "request": request,
            "request_size_bytes": len(request_bytes),
            "request_sha256": hashlib.sha256(request_bytes).hexdigest(),
            "sizing_status": sizing_status,
            "required_response_bytes": int(required.value),
            "status": sizing_status,
            "response": None,
            "response_text": None,
            "response_sha256": None,
        }
        if sizing_status == FFI_PANIC:
            return observation
        if sizing_status != FFI_BUFFER_TOO_SMALL or required.value == 0:
            return observation

        output = (ctypes.c_uint8 * required.value)()
        written = ctypes.c_size_t(required.value)
        status = int(
            self.library.nabla_core_probe_execute(
                handle,
                request_buffer,
                len(request_bytes),
                output,
                len(output),
                ctypes.byref(written),
            )
        )
        response_bytes = bytes(output[: written.value])
        response_text = response_bytes.decode("utf-8", errors="strict")
        try:
            response = json.loads(response_text)
        except json.JSONDecodeError:
            response = None

        observation.update(
            {
                "status": status,
                "written_response_bytes": int(written.value),
                "response": response,
                "response_text": response_text,
                "response_sha256": hashlib.sha256(response_bytes).hexdigest(),
            }
        )
        return observation

    def close(self, handle: ctypes.c_void_p) -> int:
        return int(self.library.nabla_core_probe_close(handle))


def _counts(observation: dict[str, object]) -> dict[str, object] | None:
    response = observation.get("response")
    if not isinstance(response, dict):
        return None
    counts = response.get("counts")
    return counts if isinstance(counts, dict) else None


def _response_code(observation: dict[str, object]) -> str | None:
    response = observation.get("response")
    if not isinstance(response, dict):
        return None
    code = response.get("code")
    return code if isinstance(code, str) else None


def _record_assertion(
    assertions: list[dict[str, object]],
    assertion_id: str,
    condition: bool,
    detail: str,
) -> None:
    assertions.append(
        {
            "id": assertion_id,
            "passed": bool(condition),
            "detail": detail,
        }
    )


def run_driver(library_path: Path, database_path: Path) -> dict[str, object]:
    probe = ProbeLibrary(library_path)
    assertions: list[dict[str, object]] = []
    calls: list[dict[str, object]] = []

    abi_version = probe.abi_version()
    max_request_bytes = probe.max_request_bytes()
    _record_assertion(
        assertions,
        "FFI-ABI-VERSION",
        abi_version == EXPECTED_ABI_VERSION,
        f"observed ABI version {abi_version}",
    )
    _record_assertion(
        assertions,
        "FFI-REQUEST-LIMIT",
        max_request_bytes == EXPECTED_MAX_REQUEST_BYTES,
        f"observed request limit {max_request_bytes} bytes",
    )

    open_status, handle = probe.open(database_path)
    _record_assertion(
        assertions,
        "FFI-OPEN",
        open_status == FFI_OK and bool(handle.value),
        f"open status {open_status}",
    )
    if open_status != FFI_OK or not handle.value:
        return {
            "schema_version": 1,
            "abi_version": abi_version,
            "max_request_bytes": max_request_bytes,
            "open_status": open_status,
            "calls": calls,
            "assertions": assertions,
            "overall_status": "failed",
        }

    requests: list[dict[str, object]] = [
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
        {
            "op": "apply",
            "request_id": "ffi-rollback",
            "fact_id": "ffi-rollback",
            "value": "rollback",
            "inject_failure": "after_outbox",
        },
        {"op": "inspect"},
        {"op": "panic_probe"},
        {"op": "integrity"},
    ]
    for request in requests:
        calls.append(probe.execute(handle, request))
    close_status = probe.close(handle)

    reopen_status, reopened_handle = probe.open(database_path)
    reopened_inspect: dict[str, object] | None = None
    reopened_close_status: int | None = None
    if reopen_status == FFI_OK and reopened_handle.value:
        reopened_inspect = probe.execute(reopened_handle, {"op": "inspect"})
        reopened_close_status = probe.close(reopened_handle)

    expected_counts = {
        "facts": 1,
        "idempotency": 1,
        "audit": 1,
        "outbox": 1,
    }
    _record_assertion(
        assertions,
        "FFI-INITIAL-EMPTY",
        _counts(calls[0])
        == {"facts": 0, "idempotency": 0, "audit": 0, "outbox": 0},
        "initial inspect is empty",
    )
    _record_assertion(
        assertions,
        "FFI-APPLY",
        calls[1].get("status") == FFI_OK
        and _response_code(calls[1]) == "APPLIED",
        "shared command is applied through the C ABI",
    )
    _record_assertion(
        assertions,
        "FFI-REPLAY",
        calls[2].get("status") == FFI_OK
        and _response_code(calls[2]) == "REPLAYED",
        "same request is replayed through the C ABI",
    )
    _record_assertion(
        assertions,
        "FFI-ROLLBACK",
        _response_code(calls[3]) == "INJECTED_FAILURE"
        and _counts(calls[4]) == expected_counts,
        "injected transaction failure leaves no partial second command",
    )
    _record_assertion(
        assertions,
        "FFI-PANIC-CONTAINED",
        calls[5].get("sizing_status") == FFI_PANIC
        and calls[5].get("required_response_bytes") == 0,
        "panic is caught at the FFI boundary",
    )
    integrity_response = calls[6].get("response")
    _record_assertion(
        assertions,
        "FFI-AFTER-PANIC",
        calls[6].get("status") == FFI_OK
        and isinstance(integrity_response, dict)
        and integrity_response.get("integrity") == "ok",
        "handle remains usable after the contained panic",
    )
    _record_assertion(
        assertions,
        "FFI-CLOSE",
        close_status == FFI_OK,
        f"close status {close_status}",
    )
    _record_assertion(
        assertions,
        "FFI-REOPEN",
        reopen_status == FFI_OK
        and reopened_inspect is not None
        and _counts(reopened_inspect) == expected_counts
        and reopened_close_status == FFI_OK,
        "committed state is durable after closing and reopening the FFI handle",
    )

    return {
        "schema_version": 1,
        "abi_version": abi_version,
        "max_request_bytes": max_request_bytes,
        "open_status": open_status,
        "calls": calls,
        "close_status": close_status,
        "reopen_status": reopen_status,
        "reopened_inspect": reopened_inspect,
        "reopened_close_status": reopened_close_status,
        "assertions": assertions,
        "overall_status": (
            "passed"
            if assertions and all(item["passed"] for item in assertions)
            else "failed"
        ),
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    arguments = parser.parse_args(argv)

    try:
        result = run_driver(arguments.library, arguments.db)
    except Exception as error:  # noqa: BLE001 - raw spike evidence
        traceback.print_exc(file=sys.stderr)
        result = {
            "schema_version": 1,
            "overall_status": "failed",
            "fatal_error": f"{type(error).__name__}: {error}",
        }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("overall_status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(_main())
