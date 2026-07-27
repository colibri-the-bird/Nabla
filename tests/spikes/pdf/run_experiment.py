#!/usr/bin/env python3
"""Reproducible, bounded PDF and anchor experiment for SPIKE-PDF-001."""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import difflib
import hashlib
from importlib import metadata
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Iterable

from PIL import Image, ImageDraw, ImageFont


SPIKE_DIR = Path(__file__).resolve().parent
WORKSPACE = SPIKE_DIR.parents[2]
FIXTURE_DIR = SPIKE_DIR / "fixtures"
ARTIFACT_DIR = SPIKE_DIR / "artifacts"
WORKER = SPIKE_DIR / "worker.py"
GENERATOR = SPIKE_DIR / "generate_fixtures.py"
LOCK_FILE = SPIKE_DIR / "requirements.lock.txt"

SCHEMA_VERSION = 1
PUBLIC_PASSWORD = "nabla-spike-public"
WRONG_PASSWORD = "nabla-spike-wrong"
PASSWORD_ENV = "NABLA_PDF_PASSWORD"

MIB = 1024 * 1024
LIMITS = {
    "candidate_count": 2,
    "concurrency": 1,
    "retries": 0,
    "render_dpi": 144,
    "render_scale": 2.0,
    "max_pixels_per_page": 20_000_000,
    "normal_fixture_bytes": 16 * MIB,
    "normal_fixture_pages": 64,
    "stress_fixture_bytes": 96 * MIB,
    "stress_fixture_pages": 512,
    "extracted_output_bytes_per_case": 16 * MIB,
    "stdout_bytes_per_case": 1 * MIB,
    "stderr_bytes_per_case": 1 * MIB,
    "result_json_bytes": 16 * MIB,
    "temp_bytes": 512 * MIB,
    "normal_timeout_seconds": 30.0,
    "hostile_timeout_seconds": 10.0,
    "stress_timeout_seconds": 180.0,
    "overall_timeout_seconds": 20 * 60.0,
    "child_memory_bytes": 1536 * MIB,
    "warmups": 1,
    "measured_runs": 3,
}
WINDOWS_ABSOLUTE_PREFIX_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])[A-Z]:(?=(?:\\\\|\\|/))"
)
INTERMEDIATE_ARTIFACT_DIR_NAMES = (
    "debug-basic",
    "basic-repeat-1",
    "basic-repeat-2",
    "basic-repeat-3",
    "boxes-rotation",
    "scan-layers",
    "anchor-v0",
)

LICENSE_SOURCES = {
    "pypdfium2": "https://pypdfium2.readthedocs.io/en/stable/readme.html#licensing",
    "pdfium": "https://pdfium.googlesource.com/pdfium/+/refs/heads/main/LICENSE",
    "pdfplumber": "https://github.com/jsvine/pdfplumber/blob/stable/LICENSE.txt",
    "pdfminer.six": "https://github.com/pdfminer/pdfminer.six/blob/master/LICENSE",
    "pypdf": "https://github.com/py-pdf/pypdf/blob/main/LICENSE",
    "reportlab": "https://docs.reportlab.com/developerfaqs/#licensing",
}
RUN_DEADLINE_MONOTONIC: float | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return path.resolve().relative_to(WORKSPACE.resolve()).as_posix()


def scrub(value: str) -> str:
    replacements = {
        str(WORKSPACE.resolve()): "<workspace>",
        str(Path.home().resolve()): "<home>",
        str(Path(sys.executable).resolve()): "<python>",
        PUBLIC_PASSWORD: "<redacted>",
        WRONG_PASSWORD: "<redacted>",
    }
    result = value
    for original, replacement in replacements.items():
        variants = {
            original,
            original.replace("\\", "/"),
            original.replace("\\", "\\\\"),
        }
        for variant in sorted(variants, key=len, reverse=True):
            result = result.replace(variant, replacement)
    return WINDOWS_ABSOLUTE_PREFIX_RE.sub("<absolute>", result)


def leak_reasons(value: str) -> list[str]:
    reasons: list[str] = []
    markers = {
        "workspace": str(WORKSPACE.resolve()),
        "home": str(Path.home().resolve()),
        "python": str(Path(sys.executable).resolve()),
        "public_password": PUBLIC_PASSWORD,
        "wrong_password": WRONG_PASSWORD,
    }
    for label, marker in markers.items():
        variants = {
            marker,
            marker.replace("\\", "/"),
            marker.replace("\\", "\\\\"),
        }
        if any(variant in value for variant in variants):
            reasons.append(label)
    if WINDOWS_ABSOLUTE_PREFIX_RE.search(value):
        reasons.append("windows_absolute_path")
    return sorted(set(reasons))


def scrub_tree(value: Any) -> Any:
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, dict):
        return {scrub(str(key)): scrub_tree(item) for key, item in value.items()}
    if isinstance(value, list):
        return [scrub_tree(item) for item in value]
    return value


def cleanup_intermediate_artifacts() -> bool:
    for name in INTERMEDIATE_ARTIFACT_DIR_NAMES:
        path = ARTIFACT_DIR / name
        if path.exists():
            shutil.rmtree(path)
    return all(
        not (ARTIFACT_DIR / name).exists()
        for name in INTERMEDIATE_ARTIFACT_DIR_NAMES
    )


def command_for_record(args: list[str]) -> list[str]:
    recorded: list[str] = []
    for value in args:
        cleaned = scrub(value)
        try:
            path = Path(value)
            if path.is_absolute() and path.exists():
                cleaned = rel(path)
        except (OSError, ValueError):
            pass
        recorded.append(cleaned)
    if recorded and Path(args[0]).resolve() == Path(sys.executable).resolve():
        recorded[0] = "<python>"
    return recorded


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        loaded = json.load(stream)
    if not isinstance(loaded, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return loaded


def finite_tree(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(finite_tree(key) and finite_tree(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return all(finite_tree(item) for item in value)
    return True


def distribution_info(name: str) -> dict[str, Any]:
    try:
        dist = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return {"status": "unavailable"}
    license_value = (
        dist.metadata.get("License-Expression")
        or dist.metadata.get("License")
        or "not declared in package metadata"
    )
    license_files: list[dict[str, Any]] = []
    for relative_file in dist.files or []:
        lowered_parts = {
            part.casefold() for part in Path(str(relative_file)).parts
        }
        if not any(
            "license" in part
            or part in {"copying", "notice"}
            for part in lowered_parts
        ):
            continue
        located = Path(dist.locate_file(relative_file))
        if not located.is_file():
            continue
        license_files.append(
            {
                "path": Path(str(relative_file)).as_posix(),
                "bytes": located.stat().st_size,
                "sha256": sha256_file(located),
            }
        )
    return {
        "status": "available",
        "version": dist.version,
        "license_metadata": scrub(str(license_value))[:2048],
        "home_page": dist.metadata.get("Home-page") or dist.metadata.get("Project-URL"),
        "official_license_source": LICENSE_SOURCES.get(name),
        "installed_license_files": sorted(
            license_files,
            key=lambda item: item["path"],
        ),
    }


def binary_inventory() -> list[dict[str, Any]]:
    import pypdfium2

    package_dir = Path(pypdfium2.__file__).resolve().parent
    roots = [package_dir, package_dir.parent / "pypdfium2_raw"]
    seen: set[Path] = set()
    entries: list[dict[str, Any]] = []
    for root in roots:
        if not root.exists():
            continue
        for pattern in ("*.dll", "*.pyd", "*.so", "*.dylib"):
            for path in root.rglob(pattern):
                resolved = path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                entries.append(
                    {
                        "name": path.name,
                        "bytes": path.stat().st_size,
                        "sha256": sha256_file(path),
                    }
                )
    return sorted(entries, key=lambda item: item["name"])


def parse_lock() -> dict[str, str]:
    locked: dict[str, str] = {}
    for raw_line in LOCK_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        name, version = line.split("==", 1)
        locked[name.lower()] = version
    return locked


class ProcessMemoryCountersEx(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


def windows_working_set(pid: int) -> int | None:
    if os.name != "nt":
        return None
    process_query_limited_information = 0x1000
    process_vm_read = 0x0010
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ProcessMemoryCountersEx),
        wintypes.DWORD,
    ]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(
        process_query_limited_information | process_vm_read,
        False,
        pid,
    )
    if not handle:
        return None
    try:
        counters = ProcessMemoryCountersEx()
        counters.cb = ctypes.sizeof(counters)
        ok = psapi.GetProcessMemoryInfo(
            handle,
            ctypes.byref(counters),
            counters.cb,
        )
        return int(counters.WorkingSetSize) if ok else None
    finally:
        kernel32.CloseHandle(handle)


class StreamCollector:
    def __init__(self, retain_limit: int) -> None:
        self.retain_limit = retain_limit
        self.retained = bytearray()
        self.total_bytes = 0
        self.digest = hashlib.sha256()

    def drain(self, stream: Any) -> None:
        while True:
            chunk = stream.read(65_536)
            if not chunk:
                break
            self.total_bytes += len(chunk)
            self.digest.update(chunk)
            remaining = self.retain_limit - len(self.retained)
            if remaining > 0:
                self.retained.extend(chunk[:remaining])

    def metadata(self) -> dict[str, Any]:
        excerpt = bytes(self.retained[:16_384]).decode(
            "utf-8", errors="replace"
        )
        return {
            "bytes": self.total_bytes,
            "sha256": self.digest.hexdigest(),
            "excerpt": scrub(excerpt),
            "over_limit": self.total_bytes > self.retain_limit,
        }


def run_process(
    case_id: str,
    group: str,
    args: list[str],
    timeout_seconds: float,
    env_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    started_utc = utc_now()
    started = time.perf_counter()
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        args,
        cwd=WORKSPACE,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
    )
    stdout_collector = StreamCollector(LIMITS["stdout_bytes_per_case"])
    stderr_collector = StreamCollector(LIMITS["stderr_bytes_per_case"])
    stdout_thread = threading.Thread(
        target=stdout_collector.drain,
        args=(process.stdout,),
        name=f"{case_id}-stdout",
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=stderr_collector.drain,
        args=(process.stderr,),
        name=f"{case_id}-stderr",
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    peak_working_set = 0
    samples = 0
    termination = "exit"
    while process.poll() is None:
        elapsed = time.perf_counter() - started
        if (
            RUN_DEADLINE_MONOTONIC is not None
            and time.perf_counter() >= RUN_DEADLINE_MONOTONIC
        ):
            termination = "overall_timeout"
            process.kill()
            break
        working_set = windows_working_set(process.pid)
        if working_set is not None:
            peak_working_set = max(peak_working_set, working_set)
            samples += 1
            if working_set > LIMITS["child_memory_bytes"]:
                termination = "memory_limit"
                process.kill()
                break
        if elapsed > timeout_seconds:
            termination = "timeout"
            process.kill()
            break
        time.sleep(0.01)
    process.wait()
    stdout_thread.join(timeout=5.0)
    stderr_thread.join(timeout=5.0)
    stdout = bytes(stdout_collector.retained)
    stderr = bytes(stderr_collector.retained)
    duration_ms = (time.perf_counter() - started) * 1000.0
    parsed: dict[str, Any] | None = None
    parse_error: str | None = None
    if stdout and not stdout_collector.metadata()["over_limit"]:
        try:
            parsed_value = json.loads(stdout.decode("utf-8", errors="strict").splitlines()[-1])
            if isinstance(parsed_value, dict):
                parsed = scrub_tree(parsed_value)
            else:
                parse_error = "worker output was not a JSON object"
        except Exception as exc:
            parse_error = scrub(f"{type(exc).__name__}: {exc}")
    else:
        parse_error = (
            "worker stdout exceeded capture limit"
            if stdout_collector.metadata()["over_limit"]
            else "worker produced no stdout"
        )
    return {
        "id": case_id,
        "group": group,
        "command": command_for_record(args),
        "environment": {
            key: "<redacted>" if key == PASSWORD_ENV else scrub(value)
            for key, value in (env_overrides or {}).items()
        },
        "started_utc": started_utc,
        "finished_utc": utc_now(),
        "duration_ms": round(duration_ms, 3),
        "timeout_seconds": timeout_seconds,
        "termination": termination,
        "exit_code": process.returncode,
        "peak_working_set_bytes": peak_working_set or None,
        "working_set_samples": samples,
        "stdout": stdout_collector.metadata(),
        "stderr": stderr_collector.metadata(),
        "parsed": parsed,
        "parse_error": parse_error,
    }


def fixture_entries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    fixtures = manifest.get("fixtures")
    if isinstance(fixtures, dict):
        return [{"id": key, **value} for key, value in fixtures.items()]
    if isinstance(fixtures, list):
        return fixtures
    raise ValueError("fixture manifest must contain fixtures list or object")


def fixture_path(entry: dict[str, Any]) -> Path:
    raw = entry.get("path") or entry.get("file")
    if not isinstance(raw, str):
        raise ValueError(f"fixture {entry.get('id')} has no path")
    path = (FIXTURE_DIR / raw).resolve()
    path.relative_to(FIXTURE_DIR.resolve())
    return path


def fixture_by_id(entries: list[dict[str, Any]], fixture_id: str) -> dict[str, Any]:
    for entry in entries:
        if entry.get("id") == fixture_id:
            return entry
    raise KeyError(f"missing fixture {fixture_id}")


def find_fixture(
    entries: list[dict[str, Any]],
    *,
    exact_ids: Iterable[str] = (),
    id_prefix: str | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    exact_set = set(exact_ids)
    for entry in entries:
        fixture_id = str(entry.get("id", ""))
        if fixture_id in exact_set:
            return entry
        if id_prefix and fixture_id.startswith(id_prefix):
            return entry
        if kind and entry.get("kind") == kind:
            return entry
    criteria = {"exact_ids": sorted(exact_set), "id_prefix": id_prefix, "kind": kind}
    raise KeyError(f"fixture not found: {criteria}")


def worker_args(
    entry: dict[str, Any],
    *,
    action: str = "inspect",
    pages: str | None = None,
    queries: Iterable[str] = (),
    render_dir: Path | None = None,
    with_pdfplumber: bool = False,
    no_render: bool = False,
    password_env: bool = False,
    delay_ms: int = 0,
) -> list[str]:
    args = [
        sys.executable,
        str(WORKER),
        "--action",
        action,
        "--input",
        str(fixture_path(entry)),
        "--render-scale",
        str(LIMITS["render_scale"]),
        "--max-pixels",
        str(LIMITS["max_pixels_per_page"]),
        "--max-pages",
        str(
            LIMITS["stress_fixture_pages"]
            if action == "stress"
            else LIMITS["normal_fixture_pages"]
        ),
        "--max-extracted-bytes",
        str(LIMITS["extracted_output_bytes_per_case"]),
        "--offline",
    ]
    if pages is not None:
        args.extend(["--pages", pages])
    for query in queries:
        args.extend(["--query", query])
    if render_dir is not None:
        args.extend(["--render-dir", str(render_dir)])
    if with_pdfplumber:
        args.append("--with-pdfplumber")
    if no_render:
        args.append("--no-render")
    if password_env:
        args.extend(["--password-env", PASSWORD_ENV])
    if delay_ms:
        args.extend(["--delay-ms", str(delay_ms)])
    return args


def parsed_ok(case: dict[str, Any]) -> bool:
    parsed = case.get("parsed")
    return (
        case.get("termination") == "exit"
        and case.get("exit_code") == 0
        and isinstance(parsed, dict)
        and parsed.get("status") == "ok"
    )


def parsed_observation(case: dict[str, Any]) -> dict[str, Any]:
    if not parsed_ok(case):
        raise ValueError(f"case {case['id']} did not complete successfully")
    observation = case["parsed"]["observation"]
    if not isinstance(observation, dict):
        raise ValueError(f"case {case['id']} observation is not an object")
    return observation


def candidate_observations(case: dict[str, Any]) -> list[dict[str, Any]]:
    if not parsed_ok(case):
        return []
    observation = case["parsed"].get("observation")
    if not isinstance(observation, dict):
        return []
    if "candidate" in observation:
        return [observation]
    return [
        item
        for item in observation.values()
        if isinstance(item, dict) and isinstance(item.get("candidate"), str)
    ]


def normalize_text(value: str) -> str:
    return " ".join(value.replace("\u00ad", "").split()).casefold()


def text_similarity(left: str, right: str) -> float:
    return round(difflib.SequenceMatcher(None, normalize_text(left), normalize_text(right)).ratio(), 6)


def box_iou(left: list[float], right: list[float]) -> float:
    ix0 = max(left[0], right[0])
    iy0 = max(left[1], right[1])
    ix1 = min(left[2], right[2])
    iy1 = min(left[3], right[3])
    intersection = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    left_area = max(0.0, left[2] - left[0]) * max(0.0, left[3] - left[1])
    right_area = max(0.0, right[2] - right[0]) * max(0.0, right[3] - right[1])
    union = left_area + right_area - intersection
    return round(intersection / union, 6) if union else 0.0


def hash64_hamming_distance(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


def union_char_boxes(page: dict[str, Any], start: int, count: int) -> list[float]:
    selected = [
        item["box"]
        for item in page.get("char_boxes", [])
        if "box" in item and start <= int(item["index"]) < start + count
    ]
    if not selected:
        raise ValueError("target char boxes were not captured")
    return [
        min(box[0] for box in selected),
        min(box[1] for box in selected),
        max(box[2] for box in selected),
        max(box[3] for box in selected),
    ]


def make_highlight(
    source_png: Path,
    output_png: Path,
    box_pdf: list[float],
    page_height_pt: float,
    scale: float,
) -> None:
    image = Image.open(source_png).convert("RGBA")
    left = round(box_pdf[0] * scale)
    top = round((page_height_pt - box_pdf[3]) * scale)
    right = round(box_pdf[2] * scale)
    bottom = round((page_height_pt - box_pdf[1]) * scale)
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rounded_rectangle(
        [left - 3, top - 3, right + 3, bottom + 3],
        radius=4,
        fill=(255, 221, 0, 96),
        outline=(230, 126, 0, 230),
        width=3,
    )
    Image.alpha_composite(image, overlay).convert("RGB").save(output_png, "PNG")


def make_contact_sheet(image_paths: list[Path], output_path: Path) -> None:
    loaded: list[tuple[Path, Image.Image]] = []
    for path in image_paths:
        if path.exists():
            image = Image.open(path).convert("RGB")
            image.thumbnail((420, 320), Image.Resampling.LANCZOS)
            loaded.append((path, image.copy()))
    if not loaded:
        raise ValueError("no images available for contact sheet")
    columns = 2
    cell_width = 460
    cell_height = 370
    rows = math.ceil(len(loaded) / columns)
    sheet = Image.new("RGB", (columns * cell_width, rows * cell_height), "white")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for index, (path, image) in enumerate(loaded):
        x = (index % columns) * cell_width
        y = (index // columns) * cell_height
        sheet.paste(image, (x + (cell_width - image.width) // 2, y + 28))
        try:
            label = path.relative_to(ARTIFACT_DIR).as_posix()
        except ValueError:
            label = path.name
        draw.text((x + 10, y + 8), label, fill="black", font=font)
    sheet.save(output_path, "PNG")


def measure_basic_visual_oracle(
    fixture: dict[str, Any],
    render_dir: Path,
    scale: float,
) -> list[dict[str, Any]]:
    visual_oracle = fixture["expectations"]["visual_oracle"]
    measurements: list[dict[str, Any]] = []
    for page_oracle in visual_oracle["pages"]:
        if page_oracle["rotation_degrees"] != 0:
            raise ValueError("basic visual oracle must use unrotated pages")
        page_index = int(page_oracle["page_index"])
        media_box = [float(value) for value in page_oracle["media_box"]]
        crop_box = [float(value) for value in page_oracle["crop_box"]]
        if media_box != crop_box or media_box[:2] != [0.0, 0.0]:
            raise ValueError("basic visual oracle requires full-origin crop")
        page_height = media_box[3] - media_box[1]
        image_path = render_dir / f"page-{page_index + 1:03d}.png"
        image = Image.open(image_path).convert("RGB")
        for region in page_oracle["color_regions"]:
            left, bottom, right, top = [
                float(value) for value in region["box"]
            ]
            x = min(image.width - 1, max(0, round(((left + right) / 2.0) * scale)))
            y = min(
                image.height - 1,
                max(
                    0,
                    round(
                        (
                            page_height
                            - ((bottom + top) / 2.0)
                        )
                        * scale
                    ),
                ),
            )
            actual = [int(value) for value in image.getpixel((x, y))]
            expected = [int(value) for value in region["expected_rgb"]]
            errors = [
                abs(actual_value - expected_value)
                for actual_value, expected_value in zip(
                    actual, expected, strict=True
                )
            ]
            tolerance = int(region["channel_tolerance"])
            measurements.append(
                {
                    "page_index": page_index,
                    "region": region["id"],
                    "sample_pixel": [x, y],
                    "expected_rgb": expected,
                    "actual_rgb": actual,
                    "channel_errors": errors,
                    "channel_tolerance": tolerance,
                    "match": max(errors) <= tolerance,
                }
            )
    return measurements


def compare_fixture_manifests(
    committed: dict[str, Any],
    regenerated: dict[str, Any],
) -> dict[str, Any]:
    committed_bytes = json.dumps(
        committed,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    regenerated_bytes = json.dumps(
        regenerated,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "match": committed_bytes == regenerated_bytes,
        "committed_manifest_sha256": sha256_bytes(committed_bytes),
        "regenerated_manifest_sha256": sha256_bytes(regenerated_bytes),
    }


def assertion(
    assertion_id: str,
    passed: bool,
    evidence: Any,
    *,
    required: bool = True,
) -> dict[str, Any]:
    return {
        "id": assertion_id,
        "required": required,
        "status": "passed" if passed else "failed",
        "evidence": evidence,
    }


def main() -> int:
    global RUN_DEADLINE_MONOTONIC
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=SPIKE_DIR / "results" / "windows-x86_64.json",
    )
    args = parser.parse_args()
    overall_started = time.perf_counter()
    RUN_DEADLINE_MONOTONIC = (
        overall_started + LIMITS["overall_timeout_seconds"]
    )
    if not args.offline:
        raise ValueError("--offline is mandatory")
    output_path = args.output
    if not output_path.is_absolute():
        output_path = (WORKSPACE / output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    if not cleanup_intermediate_artifacts():
        raise RuntimeError("failed to reset intermediate artifact directories")

    manifest_path = FIXTURE_DIR / "manifest.json"
    manifest = load_json(manifest_path)
    fixtures = fixture_entries(manifest)
    fixture_hashes_before = {
        entry["id"]: sha256_file(fixture_path(entry)) for entry in fixtures
    }
    declared_fixture_hashes = {
        entry["id"]: entry.get("sha256") for entry in fixtures
    }
    fixture_hashes_declared_correctly = (
        fixture_hashes_before == declared_fixture_hashes
    )
    fixture_bounds: dict[str, dict[str, Any]] = {}
    for entry in fixtures:
        is_stress = entry.get("kind") == "bounded_large_document"
        byte_limit = (
            LIMITS["stress_fixture_bytes"]
            if is_stress
            else LIMITS["normal_fixture_bytes"]
        )
        page_limit = (
            LIMITS["stress_fixture_pages"]
            if is_stress
            else LIMITS["normal_fixture_pages"]
        )
        expected_page_count = entry.get("expectations", {}).get("page_count")
        page_count_within_bound = (
            expected_page_count is None
            or (
                isinstance(expected_page_count, int)
                and 0 < expected_page_count <= page_limit
            )
        )
        fixture_bounds[str(entry["id"])] = {
            "bytes": fixture_path(entry).stat().st_size,
            "byte_limit": byte_limit,
            "bytes_within_bound": (
                fixture_path(entry).stat().st_size <= byte_limit
            ),
            "expected_page_count": expected_page_count,
            "page_limit": page_limit,
            "page_count_within_bound": page_count_within_bound,
            "within_bound": (
                fixture_path(entry).stat().st_size <= byte_limit
                and page_count_within_bound
            ),
        }

    locked = parse_lock()
    package_names = [
        "pypdfium2",
        "reportlab",
        "pypdf",
        "pdfplumber",
        "pdfminer.six",
        "Pillow",
        "cryptography",
        "charset-normalizer",
        "cffi",
        "pycparser",
    ]
    packages = {name: distribution_info(name) for name in package_names}
    lock_matches = {
        name: info.get("version") == locked.get(name.lower())
        for name, info in packages.items()
    }
    external_tool_paths = {
        command: shutil.which(command)
        for command in (
            "pdftoppm",
            "pdfinfo",
            "pdftotext",
            "mutool",
            "qpdf",
            "gswin64c",
        )
    }

    with tempfile.TemporaryDirectory(prefix="nabla-pdf-fixtures-") as temp_raw:
        temp_dir = Path(temp_raw)
        regenerate_args = [
            sys.executable,
            str(GENERATOR),
            "--output-dir",
            str(temp_dir),
        ]
        regeneration = run_process(
            "fixture-regeneration",
            "fixture",
            regenerate_args,
            LIMITS["normal_timeout_seconds"],
        )
        regenerated_manifest = (
            load_json(temp_dir / "manifest.json") if regeneration["exit_code"] == 0 else {}
        )
        reproducibility = (
            compare_fixture_manifests(manifest, regenerated_manifest)
            if regenerated_manifest
            else {"match": False, "committed": [], "regenerated": []}
        )
        temporary_fixture_bytes = sum(
            path.stat().st_size for path in temp_dir.rglob("*") if path.is_file()
        )
    temporary_directory_cleaned = not temp_dir.exists()

    basic = find_fixture(
        fixtures,
        exact_ids=("F01-basic-vector", "basic-vector", "basic"),
        id_prefix="F01",
        kind="basic",
    )
    glyph = find_fixture(
        fixtures,
        exact_ids=("F03-glyph-map", "glyph-map", "basic"),
        id_prefix="F03",
        kind="basic",
    )
    boxes = find_fixture(
        fixtures,
        exact_ids=("F05-boxes-rotation", "boxes-rotation"),
        id_prefix="F05",
        kind="boxes_rotation",
    )
    reading = find_fixture(
        fixtures,
        exact_ids=("F06-reading-order", "reading-order", "basic"),
        id_prefix="F06",
        kind="basic",
    )
    scan = find_fixture(
        fixtures,
        exact_ids=("F07-scan-layers", "scan-layers", "basic"),
        id_prefix="F07",
        kind="basic",
    )
    search_fixture = find_fixture(
        fixtures,
        exact_ids=("F08-search", "search", "basic"),
        id_prefix="F08",
        kind="basic",
    )
    stress = find_fixture(
        fixtures,
        exact_ids=("F10-large-text-128", "large-text-128", "stress-128"),
        id_prefix="F10",
        kind="stress",
    )
    encrypted = find_fixture(
        fixtures,
        exact_ids=("F12-encrypted", "encrypted", "encrypted-basic"),
        id_prefix="F12-encrypted",
        kind="encrypted",
    )

    anchor_target = manifest["anchor_target"]
    target_quote = str(anchor_target["quote"])
    target_prefix = str(anchor_target.get("prefix", ""))
    target_suffix = str(anchor_target.get("suffix", ""))
    anchor_versions = manifest["anchor_versions"]
    if not isinstance(anchor_versions, list):
        raise ValueError("anchor_versions must be a list")
    base_version_id = str(anchor_target["base_version"])
    search_queries = [
        str(item["text"])
        for item in manifest.get("search_oracle", [])
        if isinstance(item, dict) and "text" in item
    ]

    cases: list[dict[str, Any]] = [regeneration]
    external_probe_cases: list[dict[str, Any]] = []
    for command, resolved in external_tool_paths.items():
        if not resolved:
            continue
        if os.name == "nt" and Path(resolved).suffix.casefold() in {
            ".bat",
            ".cmd",
        }:
            probe_args = [
                os.environ.get("COMSPEC", "cmd.exe"),
                "/d",
                "/c",
                "call",
                resolved,
                "-v",
            ]
        else:
            probe_args = [resolved, "-v"]
        probe = run_process(
            f"external-{command}-version",
            "tool_probe",
            probe_args,
            5.0,
        )
        external_probe_cases.append(probe)
        cases.append(probe)
    for run_index in range(3):
        render_dir = ARTIFACT_DIR / f"basic-repeat-{run_index + 1}"
        cases.append(
            run_process(
                f"basic-repeat-{run_index + 1}",
                "render_repeatability",
                worker_args(
                    basic,
                    queries=(target_quote,),
                    render_dir=render_dir,
                    with_pdfplumber=run_index == 0,
                ),
                LIMITS["normal_timeout_seconds"],
            )
        )

    cases.extend(
        [
            run_process(
                "glyph-map",
                "text_mapping",
                worker_args(glyph, with_pdfplumber=True),
                LIMITS["normal_timeout_seconds"],
            ),
            run_process(
                "boxes-rotation",
                "coordinates",
                worker_args(
                    boxes,
                    render_dir=ARTIFACT_DIR / "boxes-rotation",
                ),
                LIMITS["normal_timeout_seconds"],
            ),
            run_process(
                "reading-order",
                "text_mapping",
                worker_args(reading, with_pdfplumber=True),
                LIMITS["normal_timeout_seconds"],
            ),
            run_process(
                "scan-layers",
                "text_mapping",
                worker_args(
                    scan,
                    render_dir=ARTIFACT_DIR / "scan-layers",
                    with_pdfplumber=True,
                ),
                LIMITS["normal_timeout_seconds"],
            ),
            run_process(
                "search",
                "search",
                worker_args(
                    search_fixture,
                    queries=search_queries,
                    with_pdfplumber=True,
                ),
                LIMITS["normal_timeout_seconds"],
            ),
        ]
    )

    anchor_case_ids: dict[str, str] = {}
    for version in anchor_versions:
        version_id = str(version["id"])
        fixture_id = str(version.get("fixture_id") or version_id)
        entry = fixture_by_id(fixtures, fixture_id)
        case_id = f"anchor-case-{version_id.lower()}"
        anchor_case_ids[version_id] = case_id
        render_dir = (
            ARTIFACT_DIR / "anchor-v0"
            if version_id == base_version_id
            else None
        )
        cases.append(
            run_process(
                case_id,
                "anchors",
                worker_args(
                    entry,
                    queries=(target_quote,),
                    render_dir=render_dir,
                ),
                LIMITS["normal_timeout_seconds"],
            )
        )

    for run_index in range(LIMITS["warmups"] + LIMITS["measured_runs"]):
        phase = "warmup" if run_index == 0 else "measure"
        ordinal = 1 if run_index == 0 else run_index
        cases.append(
            run_process(
                f"stress-{phase}-{ordinal}",
                "large_document",
                worker_args(stress, action="stress"),
                LIMITS["stress_timeout_seconds"],
            )
        )

    cases.extend(
        [
            run_process(
                "encrypted-no-password",
                "encrypted",
                worker_args(encrypted, pages="0", no_render=True),
                LIMITS["hostile_timeout_seconds"],
            ),
            run_process(
                "encrypted-wrong-password",
                "encrypted",
                worker_args(
                    encrypted,
                    pages="0",
                    no_render=True,
                    password_env=True,
                ),
                LIMITS["hostile_timeout_seconds"],
                {PASSWORD_ENV: WRONG_PASSWORD},
            ),
            run_process(
                "encrypted-correct-password",
                "encrypted",
                worker_args(
                    encrypted,
                    pages="0",
                    password_env=True,
                ),
                LIMITS["hostile_timeout_seconds"],
                {PASSWORD_ENV: PUBLIC_PASSWORD},
            ),
        ]
    )

    hostile_entries = [
        entry
        for entry in fixtures
        if str(entry.get("kind", "")).startswith(("malformed", "hostile", "extreme"))
        or str(entry.get("id", "")).startswith(("F13", "malformed-", "extreme-"))
    ]
    for entry in hostile_entries:
        hostile_id = str(entry["id"]).lower()
        cases.append(
            run_process(
                f"hostile-{hostile_id}",
                "hostile",
                worker_args(entry, pages="0"),
                LIMITS["hostile_timeout_seconds"],
            )
        )
        cases.append(
            run_process(
                f"canary-after-{hostile_id}",
                "hostile_canary",
                worker_args(basic, pages="0", no_render=True),
                LIMITS["hostile_timeout_seconds"],
            )
        )

    cases.append(
        run_process(
            "forced-timeout",
            "cleanup",
            worker_args(basic, pages="0", no_render=True, delay_ms=1000),
            0.1,
        )
    )
    cases.append(
        run_process(
            "canary-after-forced-timeout",
            "hostile_canary",
            worker_args(basic, pages="0", no_render=True),
            LIMITS["hostile_timeout_seconds"],
        )
    )

    case_map = {case["id"]: case for case in cases}
    basic_observations = [
        parsed_observation(case_map[f"basic-repeat-{index}"])["pdfium"]
        for index in (1, 2, 3)
    ]
    render_hash_runs = [
        [page["render"]["rgb_sha256"] for page in observation["pages"]]
        for observation in basic_observations
    ]
    repeatable = render_hash_runs[0] == render_hash_runs[1] == render_hash_runs[2]

    first_basic = basic_observations[0]
    extraction_comparison: list[dict[str, Any]] = []
    basic_both = parsed_observation(case_map["basic-repeat-1"])
    for pdfium_page, plumber_page in zip(
        basic_both["pdfium"]["pages"],
        basic_both["pdfplumber"]["pages"],
        strict=True,
    ):
        pdfium_text = pdfium_page["text"]["excerpt"]
        plumber_text = plumber_page["text"]["excerpt"]
        extraction_comparison.append(
            {
                "page_index": pdfium_page["index"],
                "pdfium_sha256": pdfium_page["text"]["sha256"],
                "pdfplumber_sha256": plumber_page["text"]["sha256"],
                "normalized_similarity": text_similarity(pdfium_text, plumber_text),
                "exact_equal": pdfium_text == plumber_text,
            }
        )

    coordinate_case = parsed_observation(case_map["boxes-rotation"])["pdfium"]
    coordinate_oracle_pages = boxes["expectations"]["visual_oracle"]["pages"]
    page_box_measurements: list[dict[str, Any]] = []
    for page_oracle in coordinate_oracle_pages:
        page_index = int(page_oracle["page_index"])
        observed_page = next(
            page
            for page in coordinate_case["pages"]
            if page["index"] == page_index
        )
        expected_media = [
            float(value) for value in page_oracle["media_box"]
        ]
        expected_crop = [
            float(value) for value in page_oracle["crop_box"]
        ]
        expected_rotation = int(page_oracle["rotation_degrees"])
        page_box_measurements.append(
            {
                "page_index": page_index,
                "expected_media_box": expected_media,
                "observed_media_box": observed_page["media_box"],
                "media_box_matches": (
                    observed_page["media_box"] == expected_media
                ),
                "expected_crop_box": expected_crop,
                "observed_crop_box": observed_page["crop_box"],
                "crop_box_matches": (
                    observed_page["crop_box"] == expected_crop
                ),
                "expected_rotation_degrees": expected_rotation,
                "observed_rotation_degrees": observed_page[
                    "rotation_degrees"
                ],
                "rotation_matches": (
                    observed_page["rotation_degrees"]
                    == expected_rotation
                ),
            }
        )
    roundtrip_errors = [
        point["max_error_pt"]
        for page in coordinate_case["pages"]
        for point in page.get("render", {}).get("coordinate_roundtrips", [])
    ]
    max_roundtrip_error = max(roundtrip_errors, default=float("inf"))

    search_case = parsed_observation(case_map["search"])["pdfium"]
    search_measurements: list[dict[str, Any]] = []
    for oracle in manifest.get("search_oracle", []):
        query = str(oracle["text"])
        occurrences: list[dict[str, Any]] = []
        for page in search_case["pages"]:
            for hit in page.get("searches", {}).get(query, []):
                occurrences.append(
                    {
                        "page_index": page["index"],
                        "char_index": hit["index"],
                        "char_count": hit["count"],
                        "char_box_union": union_char_boxes(
                            page, hit["index"], hit["count"]
                        ),
                    }
                )
        hits = len(occurrences)
        expected = int(oracle["expected_count"])
        expected_pages = sorted(set(oracle.get("expected_pages", [])))
        observed_pages = sorted(
            {occurrence["page_index"] for occurrence in occurrences}
        )
        pages_match = observed_pages == expected_pages
        search_measurements.append(
            {
                "query": query,
                "expected_count": expected,
                "observed_count": hits,
                "expected_pages": expected_pages,
                "observed_pages": observed_pages,
                "pages_match": pages_match,
                "occurrences": occurrences,
                "precision": 1.0 if hits == expected else 0.0,
                "recall": 1.0 if hits == expected else min(1.0, hits / max(1, expected)),
                "match": hits == expected and pages_match,
            }
        )

    anchor_measurements: list[dict[str, Any]] = []
    base_version = next(
        item for item in anchor_versions if item["id"] == base_version_id
    )
    base_case = parsed_observation(
        case_map[anchor_case_ids[base_version_id]]
    )["pdfium"]
    base_fixture_id = str(
        base_version.get("fixture_id") or str(base_version["id"])
    )
    base_fixture = fixture_by_id(fixtures, base_fixture_id)
    base_sha = sha256_file(fixture_path(base_fixture))
    base_occurrences: list[tuple[int, dict[str, int]]] = []
    for page in base_case["pages"]:
        for hit in page["searches"].get(target_quote, []):
            base_occurrences.append((page["index"], hit))
    if len(base_occurrences) != 1:
        raise ValueError("V0 target must occur exactly once")
    base_page_index, base_hit = base_occurrences[0]
    base_page = base_case["pages"][base_page_index]
    captured_box = union_char_boxes(base_page, base_hit["index"], base_hit["count"])
    expected_box = [float(value) for value in anchor_target["expected_box"]]
    highlight_iou = box_iou(captured_box, expected_box)
    highlight_source = ARTIFACT_DIR / "anchor-v0" / f"page-{base_page_index + 1:03d}.png"
    highlight_path = ARTIFACT_DIR / "anchor-v0-highlight.png"
    make_highlight(
        source_png=highlight_source,
        output_png=highlight_path,
        box_pdf=captured_box,
        page_height_pt=float(base_page["height_pt"]),
        scale=float(LIMITS["render_scale"]),
    )

    base_page_text_sha = base_page["text"]["sha256"]
    base_page_visual_sha = base_page["render"]["rgb_sha256"]
    base_page_visual_dhash = base_page["render"]["dhash64"]
    for version in anchor_versions:
        version_id = str(version["id"])
        candidate_case = parsed_observation(case_map[anchor_case_ids[version_id]])["pdfium"]
        fixture_id = str(version.get("fixture_id") or version_id)
        entry = fixture_by_id(fixtures, fixture_id)
        document_sha = sha256_file(fixture_path(entry))
        occurrences: list[dict[str, Any]] = []
        text_page_matches: list[int] = []
        visual_page_matches: list[int] = []
        visual_perceptual_distances: list[dict[str, int]] = []
        for page in candidate_case["pages"]:
            if page["text"]["sha256"] == base_page_text_sha:
                text_page_matches.append(page["index"])
            if page.get("render", {}).get("rgb_sha256") == base_page_visual_sha:
                visual_page_matches.append(page["index"])
            candidate_dhash = page.get("render", {}).get("dhash64")
            if candidate_dhash:
                visual_perceptual_distances.append(
                    {
                        "page_index": page["index"],
                        "hamming_distance": hash64_hamming_distance(
                            base_page_visual_dhash,
                            candidate_dhash,
                        ),
                    }
                )
            for hit in page["searches"].get(target_quote, []):
                excerpt = page["text"]["excerpt"]
                start = int(hit["index"])
                count = int(hit["count"])
                prefix_window = excerpt[
                    max(0, start - len(target_prefix) - 16) : start
                ]
                suffix_window = excerpt[
                    start
                    + count : start
                    + count
                    + len(target_suffix)
                    + 16
                ]
                prefix_matches = (
                    not target_prefix
                    or normalize_text(prefix_window).endswith(
                        normalize_text(target_prefix)
                    )
                )
                suffix_matches = (
                    not target_suffix
                    or normalize_text(suffix_window).startswith(
                        normalize_text(target_suffix)
                    )
                )
                occurrences.append(
                    {
                        "page_index": page["index"],
                        "index": start,
                        "count": count,
                        "prefix_matches": prefix_matches,
                        "suffix_matches": suffix_matches,
                        "char_box_union": union_char_boxes(
                            page, start, count
                        ),
                    }
                )
        contextual_occurrences = [
            occurrence
            for occurrence in occurrences
            if occurrence["prefix_matches"] and occurrence["suffix_matches"]
        ]
        if document_sha == base_sha:
            resolution = (
                "exact_same_version"
                if len(contextual_occurrences) == 1
                else "not_found"
            )
            resolution_method = "exact_document_version"
        elif len(contextual_occurrences) == 1:
            resolution = "proposal_unique"
            resolution_method = "quote_with_prefix_suffix"
        elif len(occurrences) == 1:
            resolution = "proposal_unique"
            resolution_method = "unique_exact_quote_with_context_degradation"
        elif len(occurrences) > 1:
            resolution = "proposal_ambiguous"
            resolution_method = "exact_quote_ambiguous"
        else:
            resolution = "not_found"
            resolution_method = "exact_quote_absent"
        expected_resolution_map = {
            "exact": "exact_same_version",
            "unique_quote": "proposal_unique",
            "context_disambiguated": "proposal_unique",
            "unresolved": "not_found",
        }
        oracle_resolution = expected_resolution_map.get(
            str(version["expected_resolution"]),
            str(version["expected_resolution"]),
        )
        oracle_page = version.get("target_page")
        resolved_candidates = (
            contextual_occurrences
            if len(contextual_occurrences) == 1
            else occurrences
        )
        resolved_page = (
            resolved_candidates[0]["page_index"]
            if resolution in {"exact_same_version", "proposal_unique"}
            and len(resolved_candidates) == 1
            else None
        )
        resolved_box = (
            resolved_candidates[0]["char_box_union"]
            if resolution in {"exact_same_version", "proposal_unique"}
            and len(resolved_candidates) == 1
            else None
        )
        oracle_box = version.get("expected_box")
        target_page_matches_oracle = (
            (resolved_page is None and oracle_page is None)
            or (
                resolved_page is not None
                and oracle_page is not None
                and resolved_page == int(oracle_page)
            )
        )
        resolved_box_iou_oracle = (
            box_iou(
                [float(value) for value in resolved_box],
                [float(value) for value in oracle_box],
            )
            if resolved_box is not None and oracle_box is not None
            else None
        )
        resolved_box_matches_oracle = (
            (resolved_box is None and oracle_box is None)
            or (
                resolved_box_iou_oracle is not None
                and resolved_box_iou_oracle >= 0.90
            )
        )
        best_visual_distance = min(
            (
                item["hamming_distance"]
                for item in visual_perceptual_distances
            ),
            default=None,
        )
        best_visual_pages = [
            item["page_index"]
            for item in visual_perceptual_distances
            if item["hamming_distance"] == best_visual_distance
        ]
        rendered_target_page = int(version["rendered_target_page"])
        expected_text_fingerprint_match = bool(
            version[
                "expected_page_text_fingerprint_match_to_v0"
            ]
        )
        expected_visual_fingerprint_match = bool(
            version[
                "expected_page_visual_fingerprint_match_to_v0"
            ]
        )
        observed_text_fingerprint_match = (
            rendered_target_page in text_page_matches
        )
        observed_visual_fingerprint_match = (
            rendered_target_page in visual_page_matches
        )
        anchor_measurements.append(
            {
                "version": version_id,
                "document_sha256": document_sha,
                "oracle_change": version.get("change") or version.get("controlled_change"),
                "oracle_expected_resolution": oracle_resolution,
                "oracle_expected_resolution_source": version["expected_resolution"],
                "oracle_target_page": oracle_page,
                "resolution": resolution,
                "resolution_method": resolution_method,
                "resolution_matches_oracle": resolution == oracle_resolution,
                "occurrences": occurrences,
                "contextual_occurrences": contextual_occurrences,
                "resolved_page": resolved_page,
                "resolved_box": resolved_box,
                "target_page_delta": (
                    resolved_page - int(oracle_page)
                    if resolved_page is not None and oracle_page is not None
                    else None
                ),
                "target_page_matches_oracle": target_page_matches_oracle,
                "oracle_expected_box": oracle_box,
                "resolved_box_iou_oracle": resolved_box_iou_oracle,
                "resolved_box_matches_oracle": resolved_box_matches_oracle,
                "page_text_fingerprint_matches": text_page_matches,
                "page_visual_fingerprint_matches": visual_page_matches,
                "rendered_target_page": rendered_target_page,
                "expected_page_text_fingerprint_match_to_v0": (
                    expected_text_fingerprint_match
                ),
                "page_text_fingerprint_oracle_rationale": version[
                    "page_text_fingerprint_oracle_rationale"
                ],
                "observed_page_text_fingerprint_match_to_v0": (
                    observed_text_fingerprint_match
                ),
                "page_text_fingerprint_matches_oracle": (
                    observed_text_fingerprint_match
                    == expected_text_fingerprint_match
                ),
                "expected_page_visual_fingerprint_match_to_v0": (
                    expected_visual_fingerprint_match
                ),
                "observed_page_visual_fingerprint_match_to_v0": (
                    observed_visual_fingerprint_match
                ),
                "page_visual_fingerprint_matches_oracle": (
                    observed_visual_fingerprint_match
                    == expected_visual_fingerprint_match
                ),
                "page_visual_dhash_distances": visual_perceptual_distances,
                "page_visual_dhash_best_distance": best_visual_distance,
                "page_visual_dhash_best_pages": best_visual_pages,
                "page_visual_dhash_interpretation": (
                    "Ranking observation only; no product threshold or "
                    "canonical match is declared."
                ),
                "canonical_state_written": False,
                "cross_version_is_proposal": version_id != base_version_id,
            }
        )

    stress_cases = [
        case_map[f"stress-measure-{index}"]
        for index in range(1, LIMITS["measured_runs"] + 1)
    ]
    stress_measurements = [
        {
            **parsed_observation(case),
            "peak_working_set_bytes": case["peak_working_set_bytes"],
            "working_set_samples": case["working_set_samples"],
        }
        for case in stress_cases
    ]

    encrypted_outcomes = {
        case_id: {
            "success": parsed_ok(case_map[case_id]),
            "exit_code": case_map[case_id]["exit_code"],
            "termination": case_map[case_id]["termination"],
            "error_type": (
                case_map[case_id].get("parsed") or {}
            ).get("error_type"),
        }
        for case_id in (
            "encrypted-no-password",
            "encrypted-wrong-password",
            "encrypted-correct-password",
        )
    }
    hostile_measurements = [
        {
            "id": case["id"],
            "classified": case["parsed"] is not None or case["termination"] != "exit",
            "success": parsed_ok(case),
            "exit_code": case["exit_code"],
            "termination": case["termination"],
            "error_type": (case.get("parsed") or {}).get("error_type"),
        }
        for case in cases
        if case["group"] == "hostile"
    ]
    canary_cases = [case for case in cases if case["group"] == "hostile_canary"]

    glyph_observation = parsed_observation(case_map["glyph-map"])
    reading_observation = parsed_observation(case_map["reading-order"])
    scan_observation = parsed_observation(case_map["scan-layers"])
    glyph_oracle = basic["expectations"]["glyph_mapping"]
    glyph_mapping_measurements: dict[str, Any] = {}
    for candidate, candidate_observation in glyph_observation.items():
        page_text = candidate_observation["pages"][0]["text"]["excerpt"]
        supported = []
        for codepoint in glyph_oracle["supported_codepoints"]:
            character = chr(int(codepoint.removeprefix("U+"), 16))
            supported.append(
                {
                    "codepoint": codepoint,
                    "observed": character in page_text,
                }
            )
        missing = []
        for expected_missing in glyph_oracle[
            "declared_missing_or_unmappable"
        ]:
            character = str(expected_missing["input_sequence"])
            missing.append(
                {
                    "codepoint": expected_missing["codepoint"],
                    "observed": character in page_text,
                    "classification": (
                        "unexpected_mapping"
                        if character in page_text
                        else "unmappable_observed"
                    ),
                }
            )
        glyph_mapping_measurements[candidate] = {
            "supported": supported,
            "declared_missing_or_unmappable": missing,
            "matches_fixture_oracle": all(
                item["observed"] for item in supported
            )
            and all(not item["observed"] for item in missing),
        }

    reading_oracle = basic["expectations"]["reading_order_oracle"]
    reading_order_measurements: dict[str, Any] = {}
    expected_draw_sequence = list(reading_oracle["draw_sequence"])
    for candidate, candidate_observation in reading_observation.items():
        page_text = candidate_observation["pages"][
            int(reading_oracle["page"])
        ]["text"]["excerpt"]
        expected_counts = {
            marker: expected_draw_sequence.count(marker)
            for marker in set(expected_draw_sequence)
        }
        observed_counts = {
            marker: page_text.count(marker)
            for marker in expected_counts
        }
        positioned_markers: list[tuple[int, str]] = []
        for marker in expected_counts:
            cursor = 0
            while True:
                position = page_text.find(marker, cursor)
                if position < 0:
                    break
                positioned_markers.append((position, marker))
                cursor = position + len(marker)
        positioned_markers.sort(key=lambda item: item[0])
        observed_sequence = [
            marker for _position, marker in positioned_markers
        ]
        reading_order_measurements[candidate] = {
            "all_markers_observed": all(
                observed_counts[marker] == expected_count
                for marker, expected_count in expected_counts.items()
            ),
            "expected_counts": expected_counts,
            "observed_counts": observed_counts,
            "observed_sequence": observed_sequence,
            "matches_pdf_draw_sequence": (
                observed_sequence == expected_draw_sequence
            ),
        }

    visual_fidelity_measurements = measure_basic_visual_oracle(
        fixture=basic,
        render_dir=ARTIFACT_DIR / "basic-repeat-1",
        scale=float(LIMITS["render_scale"]),
    )
    text_mapping = {
        "glyph_fixture": glyph_observation,
        "reading_order_fixture": reading_observation,
        "scan_layer_fixture": scan_observation,
        "glyph_mapping_oracle": glyph_mapping_measurements,
        "reading_order_observations": reading_order_measurements,
        "interpretation": (
            "Orders and codepoints are raw candidate observations. The spike does "
            "not declare a canonical reading order or infer missing Unicode."
        ),
    }

    preview_paths = [
        ARTIFACT_DIR / "basic-repeat-1" / "page-001.png",
        ARTIFACT_DIR / "basic-repeat-1" / "page-002.png",
        ARTIFACT_DIR / "boxes-rotation" / "page-002.png",
        ARTIFACT_DIR / "scan-layers" / "page-003.png",
        ARTIFACT_DIR / "scan-layers" / "page-004.png",
        highlight_path,
    ]
    contact_sheet = ARTIFACT_DIR / "contact-sheet.png"
    make_contact_sheet(preview_paths, contact_sheet)
    preview_artifacts_ready = (
        all(path.exists() for path in preview_paths)
        and contact_sheet.exists()
    )
    intermediate_artifacts_cleaned = cleanup_intermediate_artifacts()

    fixture_hashes_after = {
        entry["id"]: sha256_file(fixture_path(entry)) for entry in fixtures
    }
    source_unchanged = fixture_hashes_before == fixture_hashes_after
    all_cases_bounded = all(
        case["stdout"]["over_limit"] is False
        and case["stderr"]["over_limit"] is False
        and case["termination"] in {"exit", "timeout", "memory_limit"}
        for case in cases
    )
    candidate_resource_observations = [
        {
            "case_id": case["id"],
            "group": case["group"],
            "candidate": observation["candidate"],
            "page_count": observation.get("page_count"),
            "page_limit": (
                LIMITS["stress_fixture_pages"]
                if case["group"] == "large_document"
                else LIMITS["normal_fixture_pages"]
            ),
            "extracted_utf8_bytes": observation.get(
                "extracted_utf8_bytes"
            ),
            "extracted_output_byte_limit": LIMITS[
                "extracted_output_bytes_per_case"
            ],
        }
        for case in cases
        for observation in candidate_observations(case)
    ]
    measured_candidates = sorted(
        {
            str(item["candidate"])
            for item in candidate_resource_observations
        }
    )
    candidate_count_within_bound = (
        len(measured_candidates) == LIMITS["candidate_count"]
    )
    extracted_bytes_by_case: dict[str, int] = {}
    for item in candidate_resource_observations:
        case_id = str(item["case_id"])
        extracted_bytes_by_case[case_id] = (
            extracted_bytes_by_case.get(case_id, 0)
            + int(item["extracted_utf8_bytes"])
        )
    successful_page_counts_within_bounds = all(
        isinstance(item["page_count"], int)
        and 0 < item["page_count"] <= item["page_limit"]
        for item in candidate_resource_observations
    )
    successful_extraction_within_bounds = all(
        0 <= extracted_bytes <= LIMITS["extracted_output_bytes_per_case"]
        for extracted_bytes in extracted_bytes_by_case.values()
    )
    sanitizer_canaries = {
        "workspace_path": not leak_reasons(scrub(str(WORKSPACE.resolve()))),
        "json_escaped_home_path": not leak_reasons(
            scrub(json.dumps(str(Path.home().resolve())))
        ),
        "system_absolute_path": not leak_reasons(
            scrub(os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe"))
        ),
        "public_password": not leak_reasons(scrub(PUBLIC_PASSWORD)),
        "wrong_password": not leak_reasons(scrub(WRONG_PASSWORD)),
    }
    anchor_oracles_match = all(
        item["resolution_matches_oracle"]
        and item["target_page_matches_oracle"]
        and item["resolved_box_matches_oracle"]
        and item["page_text_fingerprint_matches_oracle"]
        and item["page_visual_fingerprint_matches_oracle"]
        for item in anchor_measurements
    )
    visual_anchor_measured = all(
        bool(item["page_visual_dhash_distances"])
        for item in anchor_measurements
    )
    no_anchor_false_positive = all(
        not (
            item["oracle_expected_resolution"] in {"not_found", "proposal_ambiguous"}
            and item["resolution"] == "proposal_unique"
        )
        for item in anchor_measurements
    )
    anchor_firewall_semantics = all(
        item["canonical_state_written"] is False
        and item["cross_version_is_proposal"]
        == (item["version"] != base_version_id)
        for item in anchor_measurements
    )
    search_matches = all(item["match"] for item in search_measurements)
    memory_measured = all(
        item["peak_working_set_bytes"] is not None
        and item["working_set_samples"] > 0
        for item in stress_measurements
    )
    encrypted_isolated = (
        not encrypted_outcomes["encrypted-no-password"]["success"]
        and not encrypted_outcomes["encrypted-wrong-password"]["success"]
        and encrypted_outcomes["encrypted-correct-password"]["success"]
    )
    hostile_isolated = (
        len(hostile_measurements) > 0
        and all(item["classified"] for item in hostile_measurements)
        and all(parsed_ok(case) for case in canary_cases)
        and case_map["forced-timeout"]["termination"] == "timeout"
    )
    versions_complete = all(lock_matches.values())
    pdfium_build_license_files = [
        item
        for item in packages["pypdfium2"].get(
            "installed_license_files", []
        )
        if "BUILD_LICENSES" in item["path"]
    ]
    page_boxes_match = all(
        item["media_box_matches"]
        and item["crop_box_matches"]
        and item["rotation_matches"]
        for item in page_box_measurements
    )
    visual_oracles_match = all(
        item["match"] for item in visual_fidelity_measurements
    )
    glyph_oracles_match = all(
        item["matches_fixture_oracle"]
        for item in glyph_mapping_measurements.values()
    )
    reading_markers_captured = all(
        item["all_markers_observed"]
        for item in reading_order_measurements.values()
    )
    overall_elapsed_seconds = time.perf_counter() - overall_started
    overall_within_deadline = (
        overall_elapsed_seconds <= LIMITS["overall_timeout_seconds"]
        and all(
            case["termination"] != "overall_timeout" for case in cases
        )
    )

    assertions = [
        assertion(
            "A01-tool-and-build-versions",
            versions_complete
            and bool(binary_inventory())
            and bool(pdfium_build_license_files)
            and candidate_count_within_bound,
            {
                "lock_matches": lock_matches,
                "binary_count": len(binary_inventory()),
                "pdfium_build_license_file_count": len(
                    pdfium_build_license_files
                ),
                "measured_candidates": measured_candidates,
                "candidate_limit": LIMITS["candidate_count"],
                "candidate_count_matches_limit": (
                    candidate_count_within_bound
                ),
            },
        ),
        assertion(
            "A02-fixture-generation-repeatable",
            parsed_ok(regeneration)
            and reproducibility["match"]
            and fixture_hashes_declared_correctly
            and all(item["within_bound"] for item in fixture_bounds.values()),
            {
                "regeneration_exit": regeneration["exit_code"],
                "hashes_match": reproducibility["match"],
                "declared_hashes_match_files": fixture_hashes_declared_correctly,
                "all_fixtures_within_byte_and_page_bounds": all(
                    item["within_bound"]
                    for item in fixture_bounds.values()
                ),
            },
        ),
        assertion(
            "A03-required-cases-captured",
            all(
                case["parsed"] is not None
                or case["termination"] != "exit"
                or case["group"] == "tool_probe"
                for case in cases
            ),
            {
                "case_count": len(cases),
                "uncaptured": [
                    case["id"]
                    for case in cases
                    if case["parsed"] is None
                    and case["termination"] == "exit"
                    and case["group"] != "tool_probe"
                ],
            },
        ),
        assertion(
            "A04-render-repeatability",
            repeatable,
            {"render_hash_runs": render_hash_runs},
        ),
        assertion(
            "A05-coordinate-roundtrip",
            max_roundtrip_error <= 1.0 and page_boxes_match,
            {
                "max_error_pt": max_roundtrip_error,
                "harness_tolerance_pt": 1.0,
                "page_boxes_and_rotation_match": page_boxes_match,
                "pages": page_box_measurements,
            },
        ),
        assertion(
            "A06-visual-fidelity-and-preview",
            preview_artifacts_ready and visual_oracles_match,
            {
                "contact_sheet": rel(contact_sheet),
                "preview_count": len(preview_paths),
                "previews_existed_before_cleanup": (
                    preview_artifacts_ready
                ),
                "color_regions": visual_fidelity_measurements,
            },
        ),
        assertion(
            "A07-text-mapping-captured",
            all(
                parsed_ok(case_map[item])
                for item in ("glyph-map", "reading-order", "scan-layers")
            )
            and glyph_oracles_match
            and reading_markers_captured,
            {
                "fixtures": ["glyph-map", "reading-order", "scan-layers"],
                "glyph_oracles_match": glyph_oracles_match,
                "reading_markers_captured": reading_markers_captured,
                "reading_order_is_not_canonicalized": True,
            },
        ),
        assertion(
            "A08-search-oracles",
            bool(search_measurements) and search_matches,
            search_measurements,
        ),
        assertion(
            "A09-same-version-anchor",
            next(
                item
                for item in anchor_measurements
                if item["version"] == base_version_id
            )["resolution"]
            == "exact_same_version",
            next(
                item
                for item in anchor_measurements
                if item["version"] == base_version_id
            ),
        ),
        assertion(
            "A10-highlight-geometry",
            highlight_iou >= 0.90 and max_roundtrip_error <= 1.0,
            {
                "captured_box": captured_box,
                "oracle_box": expected_box,
                "iou": highlight_iou,
                "harness_iou_tolerance": 0.90,
                "artifact": rel(highlight_path),
            },
        ),
        assertion(
            "A11-cross-version-anchor-oracles",
            anchor_oracles_match and visual_anchor_measured,
            {
                "versions": len(anchor_measurements),
                "all_resolution_page_box_and_fingerprint_oracles_match": (
                    anchor_oracles_match
                ),
                "oracle_mismatches": [
                    {
                        "version": item["version"],
                        "resolution": item[
                            "resolution_matches_oracle"
                        ],
                        "page": item[
                            "target_page_matches_oracle"
                        ],
                        "box": item[
                            "resolved_box_matches_oracle"
                        ],
                        "page_text_fingerprint": item[
                            "page_text_fingerprint_matches_oracle"
                        ],
                        "page_visual_fingerprint": item[
                            "page_visual_fingerprint_matches_oracle"
                        ],
                    }
                    for item in anchor_measurements
                    if not (
                        item["resolution_matches_oracle"]
                        and item["target_page_matches_oracle"]
                        and item["resolved_box_matches_oracle"]
                        and item[
                            "page_text_fingerprint_matches_oracle"
                        ]
                        and item[
                            "page_visual_fingerprint_matches_oracle"
                        ]
                    )
                ],
                "visual_dhash_ranking_captured": visual_anchor_measured,
            },
        ),
        assertion(
            "A12-anchor-degradation-preserved",
            no_anchor_false_positive and anchor_firewall_semantics,
            {
                "false_positive": not no_anchor_false_positive,
                "exact_version_is_not_cross_version_proposal": (
                    anchor_firewall_semantics
                ),
                "cross_version_results_are_proposals": (
                    anchor_firewall_semantics
                ),
                "canonical_state_written": False,
            },
        ),
        assertion(
            "A13-large-document-measured",
            len(stress_measurements) == 3 and memory_measured,
            {
                "measured_runs": len(stress_measurements),
                "working_set_method": "Windows GetProcessMemoryInfo sampled by parent",
                "memory_measured": memory_measured,
            },
        ),
        assertion(
            "A14-encrypted-cases-isolated",
            encrypted_isolated,
            encrypted_outcomes,
        ),
        assertion(
            "A15-hostile-cases-bounded-and-canary-clean",
            hostile_isolated,
            {
                "hostile_count": len(hostile_measurements),
                "canary_count": len(canary_cases),
                "forced_timeout": case_map["forced-timeout"]["termination"],
            },
        ),
        assertion(
            "A16-source-hashes-unchanged",
            source_unchanged
            and temporary_directory_cleaned
            and temporary_fixture_bytes <= LIMITS["temp_bytes"]
            and intermediate_artifacts_cleaned,
            {
                "fixture_hashes_unchanged": source_unchanged,
                "temporary_directory_cleaned": temporary_directory_cleaned,
                "temporary_fixture_bytes": temporary_fixture_bytes,
                "temporary_quota_bytes": LIMITS["temp_bytes"],
                "intermediate_artifacts_cleaned": (
                    intermediate_artifacts_cleaned
                ),
            },
        ),
        assertion(
            "A17-case-stream-and-overall-bounds",
            all_cases_bounded
            and overall_within_deadline
            and bool(candidate_resource_observations)
            and successful_page_counts_within_bounds
            and successful_extraction_within_bounds
            and all(sanitizer_canaries.values()),
            {
                "all_case_streams_within_1_mib": all_cases_bounded,
                "candidate_resource_observation_count": len(
                    candidate_resource_observations
                ),
                "successful_page_counts_within_bounds": (
                    successful_page_counts_within_bounds
                ),
                "successful_extraction_within_bounds": (
                    successful_extraction_within_bounds
                ),
                "maximum_combined_extracted_utf8_bytes": max(
                    extracted_bytes_by_case.values(),
                    default=0,
                ),
                "extracted_output_byte_limit": LIMITS[
                    "extracted_output_bytes_per_case"
                ],
                "sanitizer_canaries": sanitizer_canaries,
                "overall_elapsed_seconds": round(
                    overall_elapsed_seconds, 6
                ),
                "overall_timeout_seconds": LIMITS[
                    "overall_timeout_seconds"
                ],
                "overall_within_deadline": overall_within_deadline,
            },
        ),
    ]

    tool_inventory = {
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable": "<python>",
        },
        "packages": packages,
        "pypdfium_info": None,
        "pdfium_info": None,
        "native_binaries": binary_inventory(),
        "external_tools": external_tool_paths,
        "external_tool_probes": {
            case["id"]: {
                "exit_code": case["exit_code"],
                "termination": case["termination"],
                "stdout": case["stdout"],
                "stderr": case["stderr"],
            }
            for case in external_probe_cases
        },
        "candidate_boundary": {
            "renderer_and_primary_extractor": "pypdfium2/PDFium",
            "secondary_extractor": "pdfplumber/pdfminer.six",
            "structural_fixture_oracle": "pypdf",
            "fixture_generator": "ReportLab",
            "engine_selected_for_product": False,
        },
    }
    import pypdfium2

    tool_inventory["pypdfium_info"] = str(pypdfium2.PYPDFIUM_INFO)
    tool_inventory["pdfium_info"] = str(pypdfium2.PDFIUM_INFO)
    tool_inventory["external_tools"] = {
        key: (scrub(value) if value else None)
        for key, value in tool_inventory["external_tools"].items()
    }

    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "task_id": "SPIKE-PDF-001",
        "run": {
            "started_utc": cases[0]["started_utc"],
            "finished_utc": utc_now(),
            "duration_ms": round((time.perf_counter() - overall_started) * 1000.0, 3),
            "offline_mode_requested": True,
            "network_isolation_scope": {
                "worker_python_socket_audit_hook": True,
                "worker_os_native_network_sandbox": False,
                "generator_python_socket_audit_hook": False,
                "external_tool_probe_python_socket_audit_hook": False,
                "interpretation": (
                    "The flag rejects Python socket audit events in parser "
                    "workers. It is not an OS firewall and does not prove "
                    "native-library network isolation."
                ),
            },
            "host": {
                "system": platform.system(),
                "release": platform.release(),
                "version": platform.version(),
                "machine": platform.machine(),
                "processor": platform.processor(),
            },
            "command": [
                "<python>",
                rel(Path(__file__)),
                "--offline",
                "--output",
                rel(output_path),
            ],
        },
        "decision_firewall": {
            "original_pdf_is_canonical_blob": True,
            "parser_renderer_search_outputs_are_derived": True,
            "canonical_anchor_scope": "exact Document Version capture evidence only",
            "cross_version_mapping": "proposal only",
            "retarget_writes_revision": True,
            "document_supplied_code_execution_tested": False,
            "document_supplied_code_execution_authorized": False,
            "required_product_posture": (
                "PDF JavaScript, actions, and other document-supplied active "
                "content remain inert and unsupported. No lower-level "
                "contract may authorize their execution."
            ),
            "adr_006_approved": False,
            "adr_011_approved": False,
            "product_engine_selected": False,
            "anchor_dialect_fixed": False,
        },
        "limits": LIMITS,
        "tool_inventory": tool_inventory,
        "fixture_manifest": {
            "path": rel(manifest_path),
            "sha256": sha256_file(manifest_path),
            "fixture_count": len(fixtures),
            "fixture_hashes": fixture_hashes_after,
            "declared_hashes_match_files": fixture_hashes_declared_correctly,
            "bounds": fixture_bounds,
            "reproducibility": reproducibility,
        },
        "measurements": {
            "render_repeatability": {
                "repeatable": repeatable,
                "rgb_hash_runs": render_hash_runs,
            },
            "visual_fidelity": visual_fidelity_measurements,
            "extraction_comparison": extraction_comparison,
            "coordinate_roundtrip": {
                "max_error_pt": max_roundtrip_error,
                "samples": len(roundtrip_errors),
                "page_boxes_and_rotation": page_box_measurements,
            },
            "search": search_measurements,
            "text_mapping": text_mapping,
            "anchors": {
                "capture": {
                    "document_sha256": base_sha,
                    "page_index": base_page_index,
                    "char_index": base_hit["index"],
                    "char_count": base_hit["count"],
                    "quote": target_quote,
                    "prefix": target_prefix,
                    "suffix": target_suffix,
                    "page_text_sha256": base_page_text_sha,
                    "page_visual_sha256": base_page_visual_sha,
                    "page_visual_dhash64": base_page_visual_dhash,
                    "quad_union": captured_box,
                    "normalized_quad": [
                        round(captured_box[0] / base_page["width_pt"], 8),
                        round(captured_box[1] / base_page["height_pt"], 8),
                        round(captured_box[2] / base_page["width_pt"], 8),
                        round(captured_box[3] / base_page["height_pt"], 8),
                    ],
                },
                "highlight_iou_with_oracle": highlight_iou,
                "versions": anchor_measurements,
            },
            "large_document": stress_measurements,
            "encrypted": encrypted_outcomes,
            "hostile": hostile_measurements,
        },
        "artifacts": {
            "contact_sheet": {
                "path": rel(contact_sheet),
                "sha256": sha256_file(contact_sheet),
                "bytes": contact_sheet.stat().st_size,
            },
            "highlight": {
                "path": rel(highlight_path),
                "sha256": sha256_file(highlight_path),
                "bytes": highlight_path.stat().st_size,
            },
        },
        "cases": cases,
        "assertions": assertions,
    }

    required_failures = [
        item["id"]
        for item in assertions
        if item["required"] and item["status"] != "passed"
    ]
    result["summary"] = {
        "required_assertions": sum(1 for item in assertions if item["required"]),
        "passed_required_assertions": sum(
            1 for item in assertions if item["required"] and item["status"] == "passed"
        ),
        "failed_required_assertions": required_failures,
        "experiment_passed": not required_failures,
        "interpretation": (
            "Passing validates measurement completeness and harness bounds. It does "
            "not approve ADR-006, approve ADR-011, select a product engine, or make "
            "cross-version anchor proposals canonical."
        ),
    }

    result = scrub_tree(result)
    if not finite_tree(result):
        raise ValueError("result contains non-finite values")
    serialized = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    leaked_markers = leak_reasons(serialized)
    if leaked_markers:
        raise ValueError(
            "result contains an absolute path or password marker: "
            + ", ".join(leaked_markers)
        )
    encoded = serialized.encode("utf-8")
    if len(encoded) > LIMITS["result_json_bytes"]:
        raise ValueError("result JSON exceeds 16 MiB")
    output_path.write_bytes(encoded)
    print(
        json.dumps(
            {
                "status": "passed" if not required_failures else "failed",
                "output": rel(output_path),
                "sha256": sha256_file(output_path),
                "bytes": output_path.stat().st_size,
                "required_failures": required_failures,
            },
            ensure_ascii=False,
        )
    )
    return 0 if not required_failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
