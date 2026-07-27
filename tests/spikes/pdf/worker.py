#!/usr/bin/env python3
"""Isolated PDF probe worker for SPIKE-PDF-001.

The parent harness starts one worker per native-library case. This module does
not choose a product engine or an anchor dialect; it only returns bounded raw
observations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import time
import traceback
from typing import Any


MAX_TEXT_CHARS = 250_000
MAX_STORED_CHARS = 8_192
MAX_STORED_BOXES = 2_048


class OfflineViolation(RuntimeError):
    """Raised if a worker attempts network access."""


def _block_network(event: str, _args: tuple[Any, ...]) -> None:
    if event in {
        "socket.__new__",
        "socket.bind",
        "socket.connect",
        "socket.connect_ex",
        "socket.getaddrinfo",
        "socket.gethostbyname",
    }:
        raise OfflineViolation(f"network audit event blocked: {event}")


def enable_offline_mode() -> None:
    sys.addaudithook(_block_network)
    socket.setdefaulttimeout(0.01)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8", errors="replace"))


def finite_number(value: float) -> float:
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError("non-finite numeric observation")
    return round(float(value), 6)


def scrub_text(value: str) -> str:
    replacements = {
        str(Path.cwd().resolve()): "<workspace>",
        str(Path.home().resolve()): "<home>",
    }
    result = value
    for original, replacement in replacements.items():
        result = result.replace(original, replacement)
        result = result.replace(original.replace("\\", "/"), replacement)
    return result[:4096]


def normalize_box(box: tuple[float, float, float, float]) -> list[float]:
    return [finite_number(v) for v in box]


def bounded_text(value: str) -> dict[str, Any]:
    encoded = value.encode("utf-8", errors="replace")
    return {
        "char_count": len(value),
        "utf8_bytes": len(encoded),
        "sha256": sha256_bytes(encoded),
        "excerpt": value[:MAX_STORED_CHARS],
        "truncated": len(value) > MAX_STORED_CHARS,
        "codepoints_excerpt": [f"U+{ord(char):04X}" for char in value[:512]],
    }


def difference_hash_64(image: Any) -> str:
    from PIL import Image

    small = image.convert("L").resize(
        (9, 8),
        Image.Resampling.LANCZOS,
    )
    pixels = list(small.get_flattened_data())
    value = 0
    for row in range(8):
        offset = row * 9
        for column in range(8):
            value <<= 1
            if pixels[offset + column] > pixels[offset + column + 1]:
                value |= 1
    return f"{value:016x}"


def render_page(
    page: Any,
    page_index: int,
    scale: float,
    max_pixels: int,
    render_dir: Path | None,
) -> dict[str, Any]:
    width_pt, height_pt = page.get_size()
    expected_width = max(1, round(width_pt * scale))
    expected_height = max(1, round(height_pt * scale))
    expected_pixels = expected_width * expected_height
    if expected_pixels > max_pixels:
        return {
            "status": "limit_rejected",
            "limit": "max_pixels",
            "estimated_pixels": expected_pixels,
            "max_pixels": max_pixels,
        }

    started = time.perf_counter()
    bitmap = page.render(scale=scale)
    image = bitmap.to_pil().convert("RGB")
    duration_ms = (time.perf_counter() - started) * 1000.0
    raw_rgb = image.tobytes()
    observation: dict[str, Any] = {
        "status": "rendered",
        "width_px": image.width,
        "height_px": image.height,
        "rgb_sha256": sha256_bytes(raw_rgb),
        "dhash64": difference_hash_64(image),
        "rgb_bytes": len(raw_rgb),
        "duration_ms": finite_number(duration_ms),
    }

    converter = bitmap.get_posconv(page)
    roundtrips: list[dict[str, Any]] = []
    media_box = page.get_mediabox()
    crop_box = page.get_cropbox()
    for label, box in (("media", media_box), ("crop", crop_box)):
        left, bottom, right, top = box
        for corner, point in (
            ("bottom_left", (left, bottom)),
            ("bottom_right", (right, bottom)),
            ("top_right", (right, top)),
            ("top_left", (left, top)),
        ):
            bitmap_point = converter.to_bitmap(*point)
            page_point = converter.to_page(*bitmap_point)
            error = max(
                abs(point[0] - page_point[0]),
                abs(point[1] - page_point[1]),
            )
            roundtrips.append(
                {
                    "box": label,
                    "corner": corner,
                    "page": [finite_number(point[0]), finite_number(point[1])],
                    "bitmap": [int(bitmap_point[0]), int(bitmap_point[1])],
                    "page_roundtrip": [
                        finite_number(page_point[0]),
                        finite_number(page_point[1]),
                    ],
                    "max_error_pt": finite_number(error),
                }
            )
    observation["coordinate_roundtrips"] = roundtrips

    if render_dir is not None:
        render_dir.mkdir(parents=True, exist_ok=True)
        output_path = render_dir / f"page-{page_index + 1:03d}.png"
        image.save(output_path, format="PNG", optimize=False)
        observation["png"] = output_path.name
        observation["png_sha256"] = sha256_bytes(output_path.read_bytes())
        observation["png_bytes"] = output_path.stat().st_size

    return observation


def inspect_pdfium(
    input_path: Path,
    password: str | None,
    page_indexes: list[int] | None,
    queries: list[str],
    scale: float,
    max_pixels: int,
    max_pages: int,
    max_extracted_bytes: int,
    render_dir: Path | None,
    render_enabled: bool,
) -> dict[str, Any]:
    import pypdfium2 as pdfium

    started = time.perf_counter()
    document = pdfium.PdfDocument(input_path, password=password)
    open_ms = (time.perf_counter() - started) * 1000.0
    page_count = len(document)
    if page_count > max_pages:
        document.close()
        raise ValueError(
            f"page count limit exceeded: {page_count} > {max_pages}"
        )
    selected = page_indexes if page_indexes is not None else list(range(page_count))
    if any(index < 0 or index >= page_count for index in selected):
        raise ValueError("requested page index outside document")

    pages: list[dict[str, Any]] = []
    extracted_utf8_bytes = 0
    for page_index in selected:
        page = document[page_index]
        text_page = page.get_textpage()
        count = text_page.count_chars()
        if count > MAX_TEXT_CHARS:
            raise ValueError(f"text output limit exceeded: {count} chars")
        text = text_page.get_text_range(0, count)
        extracted_utf8_bytes += len(text.encode("utf-8", errors="replace"))
        if extracted_utf8_bytes > max_extracted_bytes:
            raise ValueError(
                "extracted UTF-8 byte limit exceeded: "
                f"{extracted_utf8_bytes} > {max_extracted_bytes}"
            )

        char_boxes: list[dict[str, Any]] = []
        for char_index in range(min(count, MAX_STORED_BOXES)):
            try:
                box = normalize_box(text_page.get_charbox(char_index, loose=True))
            except Exception as exc:  # PDFium may reject control pseudo-characters.
                char_boxes.append(
                    {
                        "index": char_index,
                        "error": scrub_text(f"{type(exc).__name__}: {exc}"),
                    }
                )
                continue
            char_boxes.append(
                {
                    "index": char_index,
                    "text": text_page.get_text_range(char_index, 1),
                    "box": box,
                }
            )

        searches: dict[str, list[dict[str, int]]] = {}
        for query in queries:
            hits: list[dict[str, int]] = []
            searcher = text_page.search(query, match_case=True)
            while True:
                hit = searcher.get_next()
                if hit is None:
                    break
                index, hit_count = hit
                hits.append({"index": int(index), "count": int(hit_count)})
                if len(hits) >= 256:
                    break
            searches[query] = hits

        width, height = page.get_size()
        page_observation: dict[str, Any] = {
            "index": page_index,
            "width_pt": finite_number(width),
            "height_pt": finite_number(height),
            "rotation_degrees": int(page.get_rotation()),
            "media_box": normalize_box(page.get_mediabox()),
            "crop_box": normalize_box(page.get_cropbox()),
            "text": bounded_text(text),
            "char_boxes": char_boxes,
            "char_boxes_truncated": count > MAX_STORED_BOXES,
            "searches": searches,
        }
        if render_enabled:
            page_observation["render"] = render_page(
                page=page,
                page_index=page_index,
                scale=scale,
                max_pixels=max_pixels,
                render_dir=render_dir,
            )
        pages.append(page_observation)
        text_page.close()
        page.close()

    document.close()
    return {
        "candidate": "pypdfium2",
        "open_ms": finite_number(open_ms),
        "page_count": page_count,
        "extracted_utf8_bytes": extracted_utf8_bytes,
        "pages": pages,
    }


def inspect_pdfplumber(
    input_path: Path,
    password: str | None,
    page_indexes: list[int] | None,
    max_pages: int,
    max_extracted_bytes: int,
) -> dict[str, Any]:
    import pdfplumber

    started = time.perf_counter()
    with pdfplumber.open(input_path, password=password or "") as document:
        open_ms = (time.perf_counter() - started) * 1000.0
        page_count = len(document.pages)
        if page_count > max_pages:
            raise ValueError(
                f"page count limit exceeded: {page_count} > {max_pages}"
            )
        selected = page_indexes if page_indexes is not None else list(range(page_count))
        pages: list[dict[str, Any]] = []
        extracted_utf8_bytes = 0
        for page_index in selected:
            if page_index < 0 or page_index >= page_count:
                raise ValueError("requested page index outside document")
            page = document.pages[page_index]
            text = page.extract_text(layout=False) or ""
            if len(text) > MAX_TEXT_CHARS:
                raise ValueError(f"text output limit exceeded: {len(text)} chars")
            extracted_utf8_bytes += len(
                text.encode("utf-8", errors="replace")
            )
            if extracted_utf8_bytes > max_extracted_bytes:
                raise ValueError(
                    "extracted UTF-8 byte limit exceeded: "
                    f"{extracted_utf8_bytes} > {max_extracted_bytes}"
                )
            chars = [
                {
                    "text": str(char.get("text", "")),
                    "x0": finite_number(float(char["x0"])),
                    "top": finite_number(float(char["top"])),
                    "x1": finite_number(float(char["x1"])),
                    "bottom": finite_number(float(char["bottom"])),
                }
                for char in page.chars[:MAX_STORED_BOXES]
            ]
            pages.append(
                {
                    "index": page_index,
                    "width_pt": finite_number(float(page.width)),
                    "height_pt": finite_number(float(page.height)),
                    "text": bounded_text(text),
                    "chars": chars,
                    "chars_truncated": len(page.chars) > MAX_STORED_BOXES,
                }
            )
    return {
        "candidate": "pdfplumber",
        "open_ms": finite_number(open_ms),
        "page_count": page_count,
        "extracted_utf8_bytes": extracted_utf8_bytes,
        "pages": pages,
    }


def stress_pdfium(
    input_path: Path,
    password: str | None,
    scale: float,
    max_pixels: int,
    max_pages: int,
    max_extracted_bytes: int,
) -> dict[str, Any]:
    import pypdfium2 as pdfium

    wall_started = time.perf_counter()
    cpu_started = time.process_time()
    document = pdfium.PdfDocument(input_path, password=password)
    opened_at = time.perf_counter()
    page_count = len(document)
    if page_count > max_pages:
        document.close()
        raise ValueError(
            f"page count limit exceeded: {page_count} > {max_pages}"
        )
    text_hash = hashlib.sha256()
    total_chars = 0
    total_utf8_bytes = 0
    for page_index in range(page_count):
        page = document[page_index]
        text_page = page.get_textpage()
        count = text_page.count_chars()
        text = text_page.get_text_range(0, count)
        encoded = text.encode("utf-8", errors="replace")
        total_chars += len(text)
        total_utf8_bytes += len(encoded)
        if total_utf8_bytes > max_extracted_bytes:
            raise ValueError(
                "extracted UTF-8 byte limit exceeded: "
                f"{total_utf8_bytes} > {max_extracted_bytes}"
            )
        text_hash.update(encoded)
        text_page.close()
        page.close()
    extracted_at = time.perf_counter()

    render_indexes = sorted({0, page_count // 2, page_count - 1})
    renders: list[dict[str, Any]] = []
    for page_index in render_indexes:
        page = document[page_index]
        renders.append(
            {
                "page_index": page_index,
                **render_page(
                    page=page,
                    page_index=page_index,
                    scale=scale,
                    max_pixels=max_pixels,
                    render_dir=None,
                ),
            }
        )
        page.close()
    document.close()
    ended = time.perf_counter()
    return {
        "candidate": "pypdfium2",
        "page_count": page_count,
        "open_ms": finite_number((opened_at - wall_started) * 1000.0),
        "extract_ms": finite_number((extracted_at - opened_at) * 1000.0),
        "render_sample_ms": finite_number((ended - extracted_at) * 1000.0),
        "wall_ms": finite_number((ended - wall_started) * 1000.0),
        "cpu_ms": finite_number((time.process_time() - cpu_started) * 1000.0),
        "total_chars": total_chars,
        "extracted_utf8_bytes": total_utf8_bytes,
        "text_sha256": text_hash.hexdigest(),
        "renders": renders,
    }


def parse_page_indexes(raw_value: str | None) -> list[int] | None:
    if raw_value is None:
        return None
    if not raw_value:
        return []
    indexes = [int(value) for value in raw_value.split(",")]
    if len(indexes) > 512:
        raise ValueError("page selection exceeds 512 pages")
    return indexes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=("inspect", "stress"), required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--pages")
    parser.add_argument("--query", action="append", default=[])
    parser.add_argument("--render-dir", type=Path)
    parser.add_argument("--render-scale", type=float, default=2.0)
    parser.add_argument("--max-pixels", type=int, default=20_000_000)
    parser.add_argument("--max-pages", type=int, required=True)
    parser.add_argument("--max-extracted-bytes", type=int, required=True)
    parser.add_argument("--with-pdfplumber", action="store_true")
    parser.add_argument("--no-render", action="store_true")
    parser.add_argument("--password-env", default="")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--delay-ms", type=int, default=0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.offline:
        enable_offline_mode()
    if args.render_scale <= 0 or args.render_scale > 8:
        raise ValueError("render scale outside (0, 8]")
    if args.max_pixels <= 0 or args.max_pixels > 20_000_000:
        raise ValueError("max-pixels outside (0, 20000000]")
    if args.max_pages <= 0 or args.max_pages > 512:
        raise ValueError("max-pages outside (0, 512]")
    if (
        args.max_extracted_bytes <= 0
        or args.max_extracted_bytes > 16 * 1024 * 1024
    ):
        raise ValueError("max-extracted-bytes outside (0, 16777216]")
    if args.delay_ms < 0 or args.delay_ms > 2_000:
        raise ValueError("delay-ms outside [0, 2000]")
    if args.delay_ms:
        time.sleep(args.delay_ms / 1000.0)
    input_path = args.input.resolve(strict=True)
    password = os.environ.get(args.password_env) if args.password_env else None
    page_indexes = parse_page_indexes(args.pages)

    if args.action == "stress":
        result = stress_pdfium(
            input_path=input_path,
            password=password,
            scale=args.render_scale,
            max_pixels=args.max_pixels,
            max_pages=args.max_pages,
            max_extracted_bytes=args.max_extracted_bytes,
        )
    else:
        result = {
            "pdfium": inspect_pdfium(
                input_path=input_path,
                password=password,
                page_indexes=page_indexes,
                queries=args.query,
                scale=args.render_scale,
                max_pixels=args.max_pixels,
                max_pages=args.max_pages,
                max_extracted_bytes=args.max_extracted_bytes,
                render_dir=args.render_dir,
                render_enabled=not args.no_render,
            )
        }
        if args.with_pdfplumber:
            result["pdfplumber"] = inspect_pdfplumber(
                input_path=input_path,
                password=password,
                page_indexes=page_indexes,
                max_pages=args.max_pages,
                max_extracted_bytes=args.max_extracted_bytes,
            )
        combined_extracted_bytes = sum(
            int(candidate["extracted_utf8_bytes"])
            for candidate in result.values()
        )
        if combined_extracted_bytes > args.max_extracted_bytes:
            raise ValueError(
                "combined extracted UTF-8 byte limit exceeded: "
                f"{combined_extracted_bytes} > {args.max_extracted_bytes}"
            )
    print(json.dumps({"status": "ok", "observation": result}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as exc:
        failure = {
            "status": "error",
            "error_type": type(exc).__name__,
            "message": scrub_text(str(exc)),
            "traceback_sha256": sha256_text(traceback.format_exc()),
        }
        print(json.dumps(failure, ensure_ascii=True))
        raise SystemExit(2)
