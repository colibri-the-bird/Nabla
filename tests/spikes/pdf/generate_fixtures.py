#!/usr/bin/env python3
"""Generate deterministic PDF spike fixtures and their independent oracles."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from io import BytesIO
from pathlib import Path
from typing import Any

import PIL
import pypdf
import reportlab
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


SCHEMA_VERSION = 1
SEED = 20260727
FIXED_PDF_DATE = "D:20000101000000Z"
FONT_NAME = "NablaVera"
FONT_PACKAGE_PATH = "reportlab/fonts/Vera.ttf"
LETTER_WIDTH = float(letter[0])
LETTER_HEIGHT = float(letter[1])
TARGET_QUOTE = "The amber compass points to Nabla."
TARGET_PREFIX = "Context before: archive lantern."
TARGET_SUFFIX = "Context after: granite harbor."
TARGET_FONT_SIZE = 13.0
TARGET_X = 96.0
TARGET_BASELINE_Y = 480.0
EXTREME_PAGE_POINTS = 14400.0
ENCRYPTED_PASSWORD = "nabla-spike-public"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _font_path() -> Path:
    path = Path(reportlab.__file__).resolve().parent / "fonts" / "Vera.ttf"
    if not path.is_file():
        raise FileNotFoundError(
            f"Bundled ReportLab font is unavailable at {FONT_PACKAGE_PATH}"
        )
    return path


def _register_font() -> Path:
    path = _font_path()
    if FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(FONT_NAME, str(path)))
    return path


def _new_canvas(
    buffer: BytesIO,
    *,
    title: str,
    pagesize: tuple[float, float] = letter,
) -> canvas.Canvas:
    document = canvas.Canvas(
        buffer,
        pagesize=pagesize,
        invariant=1,
        pageCompression=1,
        pdfVersion=(1, 7),
    )
    document.setTitle(title)
    document.setAuthor("Nabla SPIKE-PDF-001")
    document.setSubject("Deterministic PDF portability fixture")
    document.setCreator("tests/spikes/pdf/generate_fixtures.py")
    document.setKeywords("Nabla, SPIKE-PDF-001, deterministic fixture")
    return document


def _fixed_writer_metadata(writer: PdfWriter, title: str) -> None:
    writer.add_metadata(
        {
            "/Title": title,
            "/Author": "Nabla SPIKE-PDF-001",
            "/Subject": "Deterministic PDF portability fixture",
            "/Creator": "tests/spikes/pdf/generate_fixtures.py",
            "/CreationDate": FIXED_PDF_DATE,
            "/ModDate": FIXED_PDF_DATE,
        }
    )


def _writer_bytes(writer: PdfWriter) -> bytes:
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _draw_page_frame(
    document: canvas.Canvas,
    *,
    page_label: str,
    width: float = LETTER_WIDTH,
    height: float = LETTER_HEIGHT,
) -> None:
    document.saveState()
    document.setStrokeColor(colors.HexColor("#B6BDC8"))
    document.setLineWidth(0.75)
    document.rect(36, 36, width - 72, height - 72, stroke=1, fill=0)
    document.setFillColor(colors.HexColor("#4B5563"))
    document.setFont(FONT_NAME, 8)
    document.drawString(48, 48, page_label)
    document.restoreState()


def _checkerboard_image() -> Image.Image:
    image = Image.new("RGB", (32, 32), (245, 247, 250))
    drawing = ImageDraw.Draw(image)
    for row in range(4):
        for column in range(4):
            if (row + column) % 2 == 0:
                fill = (41, 98, 255)
            else:
                fill = (255, 196, 61)
            drawing.rectangle(
                (column * 8, row * 8, column * 8 + 7, row * 8 + 7),
                fill=fill,
            )
    return image


def _raster_text_page(
    *,
    heading: str,
    marker: str,
    accent_rgb: tuple[int, int, int],
) -> Image.Image:
    image = Image.new(
        "RGB",
        (int(LETTER_WIDTH), int(LETTER_HEIGHT)),
        (255, 255, 255),
    )
    drawing = ImageDraw.Draw(image)
    heading_font = ImageFont.truetype(str(_font_path()), 26)
    body_font = ImageFont.truetype(str(_font_path()), 18)
    drawing.rectangle((0, 0, int(LETTER_WIDTH), 60), fill=accent_rgb)
    drawing.text((54, 84), heading, font=heading_font, fill=(17, 24, 39))
    drawing.text((54, 142), marker, font=body_font, fill=(17, 24, 39))
    drawing.text(
        (54, 188),
        "This visible text is raster pixels.",
        font=body_font,
        fill=(75, 85, 99),
    )
    return image


def _generate_basic_pdf() -> bytes:
    buffer = BytesIO()
    document = _new_canvas(buffer, title="Nabla basic fidelity fixture")

    _draw_page_frame(document, page_label="basic page 1 of 4")
    document.setFillColor(colors.HexColor("#111827"))
    document.setFont(FONT_NAME, 20)
    document.drawString(72, 720, "Nabla PDF fidelity fixture")
    document.setFont(FONT_NAME, 10)
    document.drawString(72, 694, "NABLA-SEARCH-ALPHA")
    document.drawString(
        72,
        674,
        (
            "Mapped glyphs: Caf\u00e9 | Greek U+03A9 [\u03a9] | "
            "Euro U+20AC [\u20ac]"
        ),
    )
    document.drawString(
        72,
        654,
        "Missing probe: combining U+0301 [Cafe\u0301] | Cyrillic U+0416 [\u0416]",
    )
    document.drawString(
        72,
        634,
        "Missing probe: emoji U+1F642 [\U0001f642]",
    )
    document.drawString(72, 614, "Spacing map: AV AVA ffi office 0123456789")

    document.setStrokeColor(colors.HexColor("#173A74"))
    document.setFillColor(colors.HexColor("#2F6FED"))
    document.setLineWidth(2)
    document.rect(72, 400, 180, 72, stroke=1, fill=1)

    document.setStrokeColor(colors.HexColor("#9A5E00"))
    document.setFillColor(colors.HexColor("#F2B134"))
    document.circle(330, 436, 36, stroke=1, fill=1)

    document.setStrokeColor(colors.HexColor("#B42318"))
    document.setLineWidth(3)
    document.line(72, 360, 360, 360)
    document.line(72, 350, 360, 330)

    document.drawImage(
        ImageReader(_checkerboard_image()),
        396,
        388,
        width=96,
        height=96,
        preserveAspectRatio=True,
        mask=None,
    )

    document.setFillColor(colors.HexColor("#111827"))
    document.setFont(FONT_NAME, 9)
    document.drawString(72, 305, "Vector rectangle, circle, lines, and raster grid.")
    document.showPage()

    _draw_page_frame(document, page_label="basic page 2 of 4")
    document.setFillColor(colors.HexColor("#111827"))
    document.setFont(FONT_NAME, 18)
    document.drawString(72, 720, "Text order and repeated search")
    document.setFont(FONT_NAME, 10)

    left_lines = (
        "LEFT-COLUMN-01: first extraction line.",
        "LEFT-COLUMN-02: second extraction line.",
        "REPEATED-SEARCH-PHRASE",
        "LEFT-COLUMN-04: final extraction line.",
    )
    right_lines = (
        "RIGHT-COLUMN-01: independent reading order.",
        "RIGHT-COLUMN-02: stable ASCII punctuation.",
        "REPEATED-SEARCH-PHRASE",
        "RIGHT-COLUMN-04: final extraction line.",
    )
    for index, line in enumerate(left_lines):
        document.drawString(72, 670 - index * 24, line)
    for index, line in enumerate(right_lines):
        document.drawString(326, 670 - index * 24, line)

    document.drawString(72, 540, "CaseSensitiveNeedle")
    document.drawString(72, 516, "casesensitiveneedle")
    document.drawString(326, 540, "HYPHENATED-SEARCH-TERM")
    document.drawString(326, 516, "CROSS-LINE-HYPHEN-")
    document.drawString(326, 492, "CONTINUATION")

    document.setFillColor(colors.HexColor("#2F855A"))
    document.rect(72, 390, 204, 72, stroke=0, fill=1)
    document.setFillColor(colors.HexColor("#7C3AED"))
    document.rect(326, 390, 204, 72, stroke=0, fill=1)
    document.setFillColor(colors.white)
    document.setFont(FONT_NAME, 10)
    document.drawString(90, 422, "GREEN-VECTOR-REGION")
    document.drawString(344, 422, "PURPLE-VECTOR-REGION")
    document.showPage()

    scan_only_image = _raster_text_page(
        heading="SCAN-ONLY-PAGE",
        marker="SCAN-ONLY-IMAGE-TEXT",
        accent_rgb=(180, 35, 24),
    )
    document.drawImage(
        ImageReader(scan_only_image),
        0,
        0,
        width=LETTER_WIDTH,
        height=LETTER_HEIGHT,
        preserveAspectRatio=False,
        mask=None,
    )
    document.showPage()

    hidden_layer_image = _raster_text_page(
        heading="HIDDEN-TEXT-LAYER-PAGE",
        marker="HIDDEN-TEXT-LAYER-NEEDLE",
        accent_rgb=(4, 120, 87),
    )
    document.drawImage(
        ImageReader(hidden_layer_image),
        0,
        0,
        width=LETTER_WIDTH,
        height=LETTER_HEIGHT,
        preserveAspectRatio=False,
        mask=None,
    )
    hidden_text = document.beginText()
    hidden_text.setTextOrigin(54, LETTER_HEIGHT - 160)
    hidden_text.setFont(FONT_NAME, 18)
    hidden_text.setTextRenderMode(3)
    hidden_text.textLine("HIDDEN-TEXT-LAYER-NEEDLE")
    document.drawText(hidden_text)
    document.showPage()

    document.save()
    return buffer.getvalue()


def _generate_boxes_rotation_pdf() -> bytes:
    buffer = BytesIO()
    document = _new_canvas(buffer, title="Nabla page boxes and rotation source")

    _draw_page_frame(document, page_label="boxes page 1 of 2")
    document.setFillColor(colors.HexColor("#111827"))
    document.setFont(FONT_NAME, 18)
    document.drawString(72, 700, "BOXES-PAGE-ZERO")
    document.setFont(FONT_NAME, 10)
    document.drawString(72, 672, "Media, crop, bleed, trim, and art boxes differ.")
    document.setFillColor(colors.HexColor("#0E7490"))
    document.rect(90, 330, 180, 120, stroke=0, fill=1)
    document.setFillColor(colors.white)
    document.drawString(112, 384, "CYAN-BOX-REGION")
    document.showPage()

    _draw_page_frame(document, page_label="boxes page 2 of 2")
    document.setFillColor(colors.HexColor("#111827"))
    document.setFont(FONT_NAME, 18)
    document.drawString(72, 700, "ROTATED-PAGE-ONE")
    document.setFont(FONT_NAME, 10)
    document.drawString(72, 672, "The page dictionary applies 90 degree rotation.")
    document.setFillColor(colors.HexColor("#C2410C"))
    document.rect(90, 330, 180, 120, stroke=0, fill=1)
    document.setFillColor(colors.white)
    document.drawString(112, 384, "ORANGE-BOX-REGION")
    document.showPage()

    document.save()

    reader = PdfReader(BytesIO(buffer.getvalue()))
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)

    first = writer.pages[0]
    first.mediabox = RectangleObject([0, 0, 612, 792])
    first.cropbox = RectangleObject([36, 54, 576, 738])
    first.bleedbox = RectangleObject([40, 58, 572, 734])
    first.trimbox = RectangleObject([45, 63, 567, 729])
    first.artbox = RectangleObject([54, 72, 558, 720])

    second = writer.pages[1]
    second.mediabox = RectangleObject([0, 0, 612, 792])
    second.cropbox = RectangleObject([72, 36, 540, 756])
    second.bleedbox = RectangleObject([76, 40, 536, 752])
    second.trimbox = RectangleObject([81, 45, 531, 747])
    second.artbox = RectangleObject([90, 54, 522, 738])
    second.rotate(90)

    _fixed_writer_metadata(writer, "Nabla page boxes and rotation fixture")
    return _writer_bytes(writer)


def _target_box(baseline_y: float) -> list[float]:
    left = TARGET_X
    bottom = baseline_y + pdfmetrics.getDescent(FONT_NAME, TARGET_FONT_SIZE)
    right = left + pdfmetrics.stringWidth(
        TARGET_QUOTE, FONT_NAME, TARGET_FONT_SIZE
    )
    top = baseline_y + pdfmetrics.getAscent(FONT_NAME, TARGET_FONT_SIZE)
    return [round(value, 4) for value in (left, bottom, right, top)]


def _draw_anchor_opening_page(document: canvas.Canvas) -> None:
    _draw_page_frame(document, page_label="anchor opening page")
    document.setFillColor(colors.HexColor("#111827"))
    document.setFont(FONT_NAME, 18)
    document.drawString(72, 704, "ANCHOR-DOCUMENT-OPENING")
    document.setFont(FONT_NAME, 10)
    document.drawString(72, 672, "Opening material remains fixed in every version.")
    document.drawString(72, 648, "Reference marker: OPENING-MARKER-001")
    document.showPage()


def _draw_anchor_inserted_page(document: canvas.Canvas) -> None:
    _draw_page_frame(document, page_label="anchor inserted page")
    document.setFillColor(colors.HexColor("#111827"))
    document.setFont(FONT_NAME, 18)
    document.drawString(72, 704, "ANCHOR-INSERTED-PAGE")
    document.setFont(FONT_NAME, 10)
    document.drawString(72, 672, "V2 adds only this page before the target page.")
    document.showPage()


def _draw_anchor_target_page(
    document: canvas.Canvas, version: str
) -> dict[str, Any]:
    # Keep the page frame version-neutral.  Otherwise every controlled version
    # would contain an undeclared second text/visual mutation in addition to
    # the change described by its oracle.
    _draw_page_frame(document, page_label="anchor target page")
    document.setFillColor(colors.HexColor("#111827"))
    document.setFont(FONT_NAME, 18)
    document.drawString(72, 704, "ANCHOR-TARGET-PAGE")
    document.setFont(FONT_NAME, 10)
    document.drawString(72, 672, "Fixed marker before controlled content.")

    if version == "v1":
        document.drawString(
            72,
            630,
            "V1-INSERTED-TEXT shifts extraction offsets without moving the target.",
        )

    if version == "v4":
        document.drawString(96, 606, "Other context before: slate station.")
        document.setFont(FONT_NAME, TARGET_FONT_SIZE)
        document.drawString(96, 584, TARGET_QUOTE)
        document.setFont(FONT_NAME, 10)
        document.drawString(96, 564, "Other context after: copper meadow.")

    prefix = TARGET_PREFIX
    suffix = TARGET_SUFFIX
    quote = TARGET_QUOTE
    baseline_y = TARGET_BASELINE_Y

    if version == "v3":
        quote = "The amber compass points past Nabla."
    elif version == "v5":
        prefix = "Context before: altered lantern."
    elif version == "v6":
        suffix = "Context after: altered harbor."
    elif version == "v7":
        baseline_y = 330.0

    if version != "v9":
        document.setFillColor(colors.HexColor("#4A2500"))
        document.setFont(FONT_NAME, 10)
        document.drawString(TARGET_X, baseline_y + 24, prefix)
        document.setFillColor(colors.HexColor("#B45309"))
        document.setFont(FONT_NAME, TARGET_FONT_SIZE)
        document.drawString(TARGET_X, baseline_y, quote)
        document.setFillColor(colors.HexColor("#4A2500"))
        document.setFont(FONT_NAME, 10)
        document.drawString(TARGET_X, baseline_y - 22, suffix)
    else:
        document.setFillColor(colors.HexColor("#6B7280"))
        document.setFont(FONT_NAME, 10)
        document.drawString(
            TARGET_X,
            TARGET_BASELINE_Y,
            "V9 removes the target block and leaves this inert placeholder.",
        )

    document.setStrokeColor(colors.HexColor("#CBD5E1"))
    document.setLineWidth(0.75)
    document.line(72, 248, 540, 248)
    document.setFillColor(colors.HexColor("#111827"))
    document.setFont(FONT_NAME, 10)
    document.drawString(72, 224, "Fixed marker after controlled content.")
    document.showPage()

    return {
        "rendered_quote": None if version == "v9" else quote,
        "rendered_prefix": None if version == "v9" else prefix,
        "rendered_suffix": None if version == "v9" else suffix,
        "rendered_box": None if version == "v9" else _target_box(baseline_y),
    }


def _draw_anchor_closing_page(document: canvas.Canvas) -> None:
    _draw_page_frame(document, page_label="anchor closing page")
    document.setFillColor(colors.HexColor("#111827"))
    document.setFont(FONT_NAME, 18)
    document.drawString(72, 704, "ANCHOR-DOCUMENT-CLOSING")
    document.setFont(FONT_NAME, 10)
    document.drawString(72, 672, "Closing material remains fixed in every version.")
    document.drawString(72, 648, "Reference marker: CLOSING-MARKER-001")
    document.showPage()


def _generate_anchor_pdf(version: str) -> tuple[bytes, dict[str, Any]]:
    if version not in {f"v{index}" for index in range(10)}:
        raise ValueError(f"Unknown anchor version: {version}")

    buffer = BytesIO()
    document = _new_canvas(
        buffer, title="Nabla controlled anchor fixture"
    )
    _draw_anchor_opening_page(document)
    if version == "v2":
        _draw_anchor_inserted_page(document)
    rendered = _draw_anchor_target_page(document, version)
    _draw_anchor_closing_page(document)
    document.save()
    pdf_bytes = buffer.getvalue()

    target_page = 2 if version == "v2" else 1
    page_rotation = 0
    if version == "v8":
        reader = PdfReader(BytesIO(pdf_bytes))
        writer = PdfWriter()
        writer.clone_document_from_reader(reader)
        writer.pages[target_page].rotate(90)
        _fixed_writer_metadata(
            writer, "Nabla controlled anchor fixture"
        )
        pdf_bytes = _writer_bytes(writer)
        page_rotation = 90

    changes = {
        "v0": "baseline",
        "v1": "insert_text_before_target_same_page",
        "v2": "insert_page_before_target_page",
        "v3": "mutate_target_quote",
        "v4": "duplicate_target_quote_with_different_context",
        "v5": "mutate_target_prefix",
        "v6": "mutate_target_suffix",
        "v7": "move_target_geometry_same_page",
        "v8": "rotate_target_page_90_degrees",
        "v9": "remove_target_block",
    }
    expected_resolutions = {
        "v0": "exact",
        "v1": "unique_quote",
        "v2": "unique_quote",
        "v3": "unresolved",
        "v4": "context_disambiguated",
        "v5": "unique_quote",
        "v6": "unique_quote",
        "v7": "unique_quote",
        "v8": "unique_quote",
        "v9": "unresolved",
    }
    base_occurrences = 0 if version in {"v3", "v9"} else 2 if version == "v4" else 1
    canonical_target_page = None if version in {"v3", "v9"} else target_page
    canonical_box = None if version in {"v3", "v9"} else rendered["rendered_box"]
    expected_page_text_fingerprint_match = version in {
        "v0",
        "v2",
        "v7",
    }
    expected_page_visual_fingerprint_match = version in {"v0", "v2"}
    text_fingerprint_rationale = {
        "v0": "baseline_exact_page",
        "v1": "inserted_text_changes_raw_page_text",
        "v2": "inserted_page_leaves_target_page_text_unchanged",
        "v3": "target_quote_mutation_changes_raw_page_text",
        "v4": "duplicate_quote_changes_raw_page_text",
        "v5": "prefix_mutation_changes_raw_page_text",
        "v6": "suffix_mutation_changes_raw_page_text",
        "v7": "geometry_only_move_preserves_raw_page_text_order",
        "v8": "rotation_changes_candidate_raw_extraction_order",
        "v9": "target_removal_changes_raw_page_text",
    }[version]

    oracle = {
        "controlled_change": changes[version],
        "expected_resolution": expected_resolutions[version],
        "target_page": canonical_target_page,
        "expected_box": canonical_box,
        "rendered_target_page": target_page,
        "rendered_box": rendered["rendered_box"],
        "rendered_quote": rendered["rendered_quote"],
        "rendered_prefix": rendered["rendered_prefix"],
        "rendered_suffix": rendered["rendered_suffix"],
        "base_quote_occurrences": base_occurrences,
        "expected_page_text_fingerprint_match_to_v0": (
            expected_page_text_fingerprint_match
        ),
        "page_text_fingerprint_oracle_rationale": (
            text_fingerprint_rationale
        ),
        "expected_page_visual_fingerprint_match_to_v0": (
            expected_page_visual_fingerprint_match
        ),
        "page_count": 4 if version == "v2" else 3,
        "target_page_rotation_degrees": page_rotation,
    }
    return pdf_bytes, oracle


def _generate_stress_pdf() -> bytes:
    buffer = BytesIO()
    document = _new_canvas(buffer, title="Nabla 128 page bounded stress fixture")
    for page_index in range(128):
        page_number = page_index + 1
        _draw_page_frame(
            document,
            page_label=f"stress page {page_number:03d} of 128",
        )
        document.setFillColor(colors.HexColor("#111827"))
        document.setFont(FONT_NAME, 13)
        document.drawString(54, 744, f"STRESS-PAGE-{page_number:03d}")
        document.setFont(FONT_NAME, 8)
        for line_index in range(42):
            document.drawString(
                54,
                716 - line_index * 14,
                (
                    f"Page {page_number:03d} line {line_index + 1:02d}: "
                    "bounded extraction payload 0123456789 ABCDEFGHIJKLMNOP."
                ),
            )
        if page_number % 16 == 0:
            document.setFillColor(colors.HexColor("#9A3412"))
            document.setFont(FONT_NAME, 9)
            document.drawString(
                54,
                92,
                f"STRESS-NEEDLE-{page_number:03d}",
            )
        document.showPage()
    document.save()
    return buffer.getvalue()


def _generate_extreme_page_pdf() -> bytes:
    buffer = BytesIO()
    document = _new_canvas(
        buffer,
        title="Nabla extreme page dimension fixture",
        pagesize=(EXTREME_PAGE_POINTS, EXTREME_PAGE_POINTS),
    )
    _draw_page_frame(
        document,
        page_label="extreme page 1 of 1",
        width=EXTREME_PAGE_POINTS,
        height=EXTREME_PAGE_POINTS,
    )
    document.setFillColor(colors.HexColor("#111827"))
    document.setFont(FONT_NAME, 72)
    document.drawString(720, 13680, "EXTREME-PAGE-14400-POINTS")
    document.setFont(FONT_NAME, 36)
    document.drawString(720, 13560, "Preflight dimensions before raster allocation.")
    document.showPage()
    document.save()
    return buffer.getvalue()


def _generate_encrypted_pdf(source: bytes) -> bytes:
    reader = PdfReader(BytesIO(source))
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    _fixed_writer_metadata(writer, "Nabla encrypted basic fixture")
    # ReportLab's cloned text-form file ID is incompatible with pypdf's RC4
    # hash input. Regeneration derives a deterministic byte-form ID from the
    # already deterministic writer structure.
    writer._ID = None
    writer.encrypt(
        ENCRYPTED_PASSWORD,
        owner_password=ENCRYPTED_PASSWORD,
        algorithm="RC4-128",
    )
    return _writer_bytes(writer)


def _generate_invalid_header() -> bytes:
    generator = random.Random(SEED)
    random_bytes = bytes(generator.randrange(0, 256) for _ in range(1000))
    return b"NOT-A-PDF\n" + random_bytes


def _generate_truncated_pdf(source: bytes) -> tuple[bytes, int]:
    removed = min(1024, max(256, len(source) // 16))
    if len(source) <= removed:
        raise ValueError("Source PDF is too short for deterministic truncation")
    return source[:-removed], removed


def _generate_corrupt_xref_pdf(source: bytes) -> bytes:
    match = re.search(br"startxref\s+(\d+)\s+%%EOF", source)
    if match is None:
        raise ValueError("Source PDF has no startxref trailer")
    corrupted = bytearray(source)
    corrupted[match.start(1) : match.end(1)] = b"0" * len(match.group(1))
    xref_index = source.rfind(b"\nxref\n")
    if xref_index >= 0:
        corrupted[xref_index + 1 : xref_index + 5] = b"xrez"
    return bytes(corrupted)


def _pdf_expectations(
    *,
    page_count: int,
    text_search: list[dict[str, Any]],
    visual_pages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    expectations: dict[str, Any] = {
        "valid_pdf": True,
        "page_count": page_count,
        "text_search": text_search,
    }
    if visual_pages is not None:
        expectations["visual_oracle"] = {
            "coordinate_space": "unrotated_pdf_user_space_points",
            "pages": visual_pages,
        }
    return expectations


def _fixture_entry(
    *,
    fixture_id: str,
    relative_path: str,
    data: bytes,
    kind: str,
    expectations: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": fixture_id,
        "path": relative_path,
        "sha256": _sha256_bytes(data),
        "bytes": len(data),
        "kind": kind,
        "expectations": expectations,
    }


def _write_fixture(
    output_dir: Path,
    *,
    fixture_id: str,
    filename: str,
    data: bytes,
    kind: str,
    expectations: dict[str, Any],
) -> dict[str, Any]:
    relative_path = filename
    destination = output_dir / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    if destination.read_bytes() != data:
        raise OSError(f"Fixture verification failed after writing {relative_path}")
    return _fixture_entry(
        fixture_id=fixture_id,
        relative_path=relative_path,
        data=data,
        kind=kind,
        expectations=expectations,
    )


def _assert_page_count(pdf_bytes: bytes, expected: int) -> None:
    reader = PdfReader(BytesIO(pdf_bytes), strict=True)
    actual = len(reader.pages)
    if actual != expected:
        raise AssertionError(f"Expected {expected} pages, found {actual}")


def _assert_search_counts(
    pdf_bytes: bytes, expected_counts: dict[str, int]
) -> None:
    reader = PdfReader(BytesIO(pdf_bytes))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    for needle, expected_count in expected_counts.items():
        actual_count = text.count(needle)
        if actual_count != expected_count:
            raise AssertionError(
                f"{needle!r}: expected {expected_count}, found {actual_count}"
            )


def _basic_visual_pages() -> list[dict[str, Any]]:
    return [
        {
            "page_index": 0,
            "media_box": [0.0, 0.0, LETTER_WIDTH, LETTER_HEIGHT],
            "crop_box": [0.0, 0.0, LETTER_WIDTH, LETTER_HEIGHT],
            "rotation_degrees": 0,
            "color_regions": [
                {
                    "id": "blue_rectangle_interior",
                    "box": [100.0, 420.0, 120.0, 440.0],
                    "expected_rgb": [47, 111, 237],
                    "channel_tolerance": 4,
                },
                {
                    "id": "amber_circle_center",
                    "box": [325.0, 431.0, 335.0, 441.0],
                    "expected_rgb": [242, 177, 52],
                    "channel_tolerance": 4,
                },
            ],
        },
        {
            "page_index": 1,
            "media_box": [0.0, 0.0, LETTER_WIDTH, LETTER_HEIGHT],
            "crop_box": [0.0, 0.0, LETTER_WIDTH, LETTER_HEIGHT],
            "rotation_degrees": 0,
            "color_regions": [
                {
                    "id": "green_rectangle_interior",
                    "box": [80.0, 438.0, 88.0, 446.0],
                    "expected_rgb": [47, 133, 90],
                    "channel_tolerance": 4,
                },
                {
                    "id": "purple_rectangle_interior",
                    "box": [334.0, 438.0, 342.0, 446.0],
                    "expected_rgb": [124, 58, 237],
                    "channel_tolerance": 4,
                },
            ],
        },
        {
            "page_index": 2,
            "media_box": [0.0, 0.0, LETTER_WIDTH, LETTER_HEIGHT],
            "crop_box": [0.0, 0.0, LETTER_WIDTH, LETTER_HEIGHT],
            "rotation_degrees": 0,
            "color_regions": [
                {
                    "id": "scan_only_red_banner",
                    "box": [10.0, 742.0, 20.0, 752.0],
                    "expected_rgb": [180, 35, 24],
                    "channel_tolerance": 4,
                }
            ],
        },
        {
            "page_index": 3,
            "media_box": [0.0, 0.0, LETTER_WIDTH, LETTER_HEIGHT],
            "crop_box": [0.0, 0.0, LETTER_WIDTH, LETTER_HEIGHT],
            "rotation_degrees": 0,
            "color_regions": [
                {
                    "id": "hidden_layer_green_banner",
                    "box": [10.0, 742.0, 20.0, 752.0],
                    "expected_rgb": [4, 120, 87],
                    "channel_tolerance": 4,
                }
            ],
        },
    ]


def _boxes_visual_pages() -> list[dict[str, Any]]:
    return [
        {
            "page_index": 0,
            "media_box": [0.0, 0.0, 612.0, 792.0],
            "crop_box": [36.0, 54.0, 576.0, 738.0],
            "bleed_box": [40.0, 58.0, 572.0, 734.0],
            "trim_box": [45.0, 63.0, 567.0, 729.0],
            "art_box": [54.0, 72.0, 558.0, 720.0],
            "rotation_degrees": 0,
            "color_regions": [
                {
                    "id": "cyan_rectangle_interior",
                    "box": [100.0, 340.0, 110.0, 350.0],
                    "expected_rgb": [14, 116, 144],
                    "channel_tolerance": 4,
                }
            ],
        },
        {
            "page_index": 1,
            "media_box": [0.0, 0.0, 612.0, 792.0],
            "crop_box": [72.0, 36.0, 540.0, 756.0],
            "bleed_box": [76.0, 40.0, 536.0, 752.0],
            "trim_box": [81.0, 45.0, 531.0, 747.0],
            "art_box": [90.0, 54.0, 522.0, 738.0],
            "rotation_degrees": 90,
            "color_regions": [
                {
                    "id": "orange_rectangle_interior",
                    "box": [100.0, 340.0, 110.0, 350.0],
                    "expected_rgb": [194, 65, 12],
                    "channel_tolerance": 4,
                }
            ],
        },
    ]


def _search_oracle() -> list[dict[str, Any]]:
    return [
        {
            "fixture_id": "basic",
            "text": "NABLA-SEARCH-ALPHA",
            "expected_count": 1,
            "expected_pages": [0],
            "match_mode": "exact",
            "case": "upper",
        },
        {
            "fixture_id": "basic",
            "text": "CaseSensitiveNeedle",
            "expected_count": 1,
            "expected_pages": [1],
            "match_mode": "exact",
            "case": "mixed",
        },
        {
            "fixture_id": "basic",
            "text": "casesensitiveneedle",
            "expected_count": 1,
            "expected_pages": [1],
            "match_mode": "exact",
            "case": "lower",
        },
        {
            "fixture_id": "basic",
            "text": "Caf\u00e9",
            "expected_count": 1,
            "expected_pages": [0],
            "match_mode": "exact",
            "normalization": "NFC",
        },
        {
            "fixture_id": "basic",
            "text": "Cafe\u0301",
            "expected_count": 0,
            "expected_pages": [],
            "source_occurrences": 1,
            "match_mode": "exact",
            "normalization": "decomposed_sequence",
            "expected_mapping": "combining_mark_not_in_vera_cmap",
        },
        {
            "fixture_id": "basic",
            "text": "\u03a9",
            "expected_count": 1,
            "expected_pages": [0],
            "source_occurrences": 1,
            "match_mode": "exact",
            "expected_mapping": "mapped",
        },
        {
            "fixture_id": "basic",
            "text": "\u0416",
            "expected_count": 0,
            "expected_pages": [],
            "source_occurrences": 1,
            "match_mode": "exact",
            "expected_mapping": "cyrillic_codepoint_not_in_vera_cmap",
        },
        {
            "fixture_id": "basic",
            "text": "HYPHENATED-SEARCH-TERM",
            "expected_count": 1,
            "expected_pages": [1],
            "match_mode": "exact",
            "hyphenation": "same_line",
        },
        {
            "fixture_id": "basic",
            "text": "CROSS-LINE-HYPHEN-CONTINUATION",
            "expected_count": 0,
            "expected_pages": [],
            "match_mode": "exact",
            "hyphenation": "split_across_drawn_lines",
        },
        {
            "fixture_id": "basic",
            "text": "REPEATED-SEARCH-PHRASE",
            "expected_count": 2,
            "expected_pages": [1],
            "match_mode": "exact",
            "repeated": True,
        },
        {
            "fixture_id": "basic",
            "text": "SCAN-ONLY-IMAGE-TEXT",
            "expected_count": 0,
            "expected_pages": [],
            "visible_pages": [2],
            "match_mode": "exact_extracted_text",
            "layer": "raster_only",
        },
        {
            "fixture_id": "basic",
            "text": "HIDDEN-TEXT-LAYER-NEEDLE",
            "expected_count": 1,
            "expected_pages": [3],
            "visible_pages": [3],
            "match_mode": "exact_extracted_text",
            "layer": "invisible_text_over_raster",
        },
    ]


def generate(output_dir: Path) -> dict[str, Any]:
    font_path = _register_font()
    output_dir.mkdir(parents=True, exist_ok=True)

    fixtures: list[dict[str, Any]] = []
    anchor_versions: list[dict[str, Any]] = []

    basic_pdf = _generate_basic_pdf()
    _assert_page_count(basic_pdf, 4)
    _assert_search_counts(
        basic_pdf,
        {
            "NABLA-SEARCH-ALPHA": 1,
            "REPEATED-SEARCH-PHRASE": 2,
            "CaseSensitiveNeedle": 1,
            "casesensitiveneedle": 1,
            "Caf\u00e9": 1,
            "Cafe\u0301": 0,
            "HYPHENATED-SEARCH-TERM": 1,
            "CROSS-LINE-HYPHEN-CONTINUATION": 0,
            "SCAN-ONLY-IMAGE-TEXT": 0,
            "HIDDEN-TEXT-LAYER-NEEDLE": 1,
            "\u03a9": 1,
            "\u0416": 0,
        },
    )
    fixtures.append(
        _write_fixture(
            output_dir,
            fixture_id="basic",
            filename="basic.pdf",
            data=basic_pdf,
            kind="fidelity_text_vector_raster",
            expectations=_pdf_expectations(
                page_count=4,
                text_search=_search_oracle(),
                visual_pages=_basic_visual_pages(),
            )
            | {
                "embedded_font": FONT_NAME,
                "contains_vector_graphics": True,
                "contains_raster_image": True,
                "glyph_sequences": [
                    "Caf\u00e9",
                    "Cafe\u0301",
                    "\u03a9",
                    "\u0416",
                    "\u20ac",
                ],
                "glyph_mapping": {
                    "supported_codepoints": [
                        "U+00E9",
                        "U+03A9",
                        "U+20AC",
                    ],
                    "declared_missing_or_unmappable": [
                        {
                            "codepoint": "U+0301",
                            "input_sequence": "\u0301",
                            "expected_font_mapping": ".notdef",
                            "assertion_policy": "record_observed_glyph_and_text_mapping",
                        },
                        {
                            "codepoint": "U+0416",
                            "input_sequence": "\u0416",
                            "script": "Cyrillic",
                            "expected_font_mapping": ".notdef",
                            "assertion_policy": "record_observed_glyph_and_text_mapping",
                        },
                        {
                            "codepoint": "U+1F642",
                            "input_sequence": "\U0001f642",
                            "expected_font_mapping": ".notdef_or_renderer_fallback",
                            "assertion_policy": "record_observed_glyph_and_text_mapping",
                        }
                    ],
                },
                "reading_order_oracle": {
                    "page": 1,
                    "draw_sequence": [
                        "LEFT-COLUMN-01",
                        "LEFT-COLUMN-02",
                        "REPEATED-SEARCH-PHRASE",
                        "LEFT-COLUMN-04",
                        "RIGHT-COLUMN-01",
                        "RIGHT-COLUMN-02",
                        "REPEATED-SEARCH-PHRASE",
                        "RIGHT-COLUMN-04",
                    ],
                    "columns": {
                        "left_x": 72.0,
                        "right_x": 326.0,
                    },
                },
                "text_layer_oracle": [
                    {
                        "page": 2,
                        "kind": "raster_only",
                        "visible_text": "SCAN-ONLY-IMAGE-TEXT",
                        "expected_extracted_count": 0,
                    },
                    {
                        "page": 3,
                        "kind": "invisible_text_over_raster",
                        "visible_text": "HIDDEN-TEXT-LAYER-NEEDLE",
                        "expected_extracted_count": 1,
                    },
                ],
            },
        )
    )

    boxes_pdf = _generate_boxes_rotation_pdf()
    _assert_page_count(boxes_pdf, 2)
    _assert_search_counts(
        boxes_pdf,
        {"BOXES-PAGE-ZERO": 1, "ROTATED-PAGE-ONE": 1},
    )
    fixtures.append(
        _write_fixture(
            output_dir,
            fixture_id="boxes-rotation",
            filename="boxes-rotation.pdf",
            data=boxes_pdf,
            kind="page_boxes_rotation",
            expectations=_pdf_expectations(
                page_count=2,
                text_search=[
                    {
                        "needle": "BOXES-PAGE-ZERO",
                        "expected_occurrences": 1,
                        "pages": [0],
                    },
                    {
                        "needle": "ROTATED-PAGE-ONE",
                        "expected_occurrences": 1,
                        "pages": [1],
                    },
                ],
                visual_pages=_boxes_visual_pages(),
            ),
        )
    )

    controlled_order = [f"v{index}" for index in range(10)]
    for version in controlled_order:
        anchor_pdf, oracle = _generate_anchor_pdf(version)
        _assert_page_count(anchor_pdf, oracle["page_count"])
        _assert_search_counts(
            anchor_pdf, {TARGET_QUOTE: oracle["base_quote_occurrences"]}
        )
        fixture_id = f"anchor-{version}"
        entry = _write_fixture(
            output_dir,
            fixture_id=fixture_id,
            filename=f"{fixture_id}.pdf",
            data=anchor_pdf,
            kind="controlled_anchor_version",
            expectations={
                "valid_pdf": True,
                "page_count": oracle["page_count"],
                "base_quote_occurrences": oracle["base_quote_occurrences"],
                "controlled_change": oracle["controlled_change"],
            },
        )
        fixtures.append(entry)
        anchor_versions.append(
            {
                "id": fixture_id,
                "fixture_id": fixture_id,
                "path": entry["path"],
                "sha256": entry["sha256"],
                "bytes": entry["bytes"],
                **oracle,
            }
        )

    stress_pdf = _generate_stress_pdf()
    _assert_page_count(stress_pdf, 128)
    _assert_search_counts(stress_pdf, {"STRESS-NEEDLE-": 8})
    fixtures.append(
        _write_fixture(
            output_dir,
            fixture_id="stress-128",
            filename="stress-128.pdf",
            data=stress_pdf,
            kind="bounded_large_document",
            expectations=_pdf_expectations(
                page_count=128,
                text_search=[
                    {
                        "needle": "STRESS-NEEDLE-",
                        "expected_occurrences": 8,
                        "pages": [15, 31, 47, 63, 79, 95, 111, 127],
                    }
                ],
            )
            | {
                "lines_per_page": 42,
                "bounded_page_count": 128,
            },
        )
    )

    encrypted_pdf = _generate_encrypted_pdf(basic_pdf)
    encrypted_reader = PdfReader(BytesIO(encrypted_pdf))
    if not encrypted_reader.is_encrypted:
        raise AssertionError("Encrypted fixture is not marked encrypted")
    if encrypted_reader.decrypt(ENCRYPTED_PASSWORD) == 0:
        raise AssertionError("Encrypted fixture did not accept the sentinel password")
    if len(encrypted_reader.pages) != 4:
        raise AssertionError("Encrypted fixture did not preserve all source pages")
    fixtures.append(
        _write_fixture(
            output_dir,
            fixture_id="encrypted-basic",
            filename="encrypted-basic.pdf",
            data=encrypted_pdf,
            kind="encrypted_pdf",
            expectations={
                "valid_pdf": True,
                "encrypted": True,
                "page_count_after_decrypt": 4,
                "algorithm": "RC4-128",
                "password_env": "NABLA_PDF_PASSWORD",
                "password_sha256": _sha256_bytes(
                    ENCRYPTED_PASSWORD.encode("utf-8")
                ),
                "password_is_public_test_sentinel": True,
                "source_fixture_id": "basic",
                "without_password": "locked",
            },
        )
    )

    invalid_header = _generate_invalid_header()
    fixtures.append(
        _write_fixture(
            output_dir,
            fixture_id="malformed-invalid-header",
            filename="malformed-invalid-header.pdf",
            data=invalid_header,
            kind="malformed_invalid_header",
            expectations={
                "valid_pdf": False,
                "fault_class": "invalid_header",
                "candidate_outcome": "measure_rejection",
                "must_remain_in_worker_failure_domain": True,
            },
        )
    )

    truncated_pdf, removed_bytes = _generate_truncated_pdf(basic_pdf)
    fixtures.append(
        _write_fixture(
            output_dir,
            fixture_id="malformed-truncated",
            filename="malformed-truncated.pdf",
            data=truncated_pdf,
            kind="malformed_truncated",
            expectations={
                "valid_pdf": False,
                "fault_class": "truncated_tail",
                "source_fixture_id": "basic",
                "source_sha256": _sha256_bytes(basic_pdf),
                "removed_tail_bytes": removed_bytes,
                "candidate_outcome": "measure_rejection_or_recovery",
                "must_remain_in_worker_failure_domain": True,
            },
        )
    )

    corrupt_xref_pdf = _generate_corrupt_xref_pdf(basic_pdf)
    fixtures.append(
        _write_fixture(
            output_dir,
            fixture_id="malformed-corrupt-xref",
            filename="malformed-corrupt-xref.pdf",
            data=corrupt_xref_pdf,
            kind="malformed_corrupt_xref",
            expectations={
                "valid_pdf": False,
                "fault_class": "corrupt_xref",
                "source_fixture_id": "basic",
                "source_sha256": _sha256_bytes(basic_pdf),
                "candidate_outcome": "measure_rejection_or_recovery",
                "must_remain_in_worker_failure_domain": True,
            },
        )
    )

    extreme_pdf = _generate_extreme_page_pdf()
    _assert_page_count(extreme_pdf, 1)
    fixtures.append(
        _write_fixture(
            output_dir,
            fixture_id="extreme-page",
            filename="extreme-page.pdf",
            data=extreme_pdf,
            kind="extreme_page_dimensions",
            expectations={
                "valid_pdf": True,
                "page_count": 1,
                "media_box": [
                    0.0,
                    0.0,
                    EXTREME_PAGE_POINTS,
                    EXTREME_PAGE_POINTS,
                ],
                "preflight_dimensions_before_render": True,
                "candidate_outcome": "measure_bounded_rejection_or_scaled_render",
                "must_remain_in_worker_failure_domain": True,
            },
        )
    )

    fixtures.sort(key=lambda entry: entry["id"])
    anchor_versions.sort(key=lambda entry: entry["id"])
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generator": "tests/spikes/pdf/generate_fixtures.py",
        "dependencies": {
            "python": "3.12+",
            "reportlab": reportlab.Version,
            "pypdf": pypdf.__version__,
            "pillow": PIL.__version__,
        },
        "determinism": {
            "seed": SEED,
            "reportlab_invariant": True,
            "fixed_pdf_date": FIXED_PDF_DATE,
            "json_sort_keys": True,
            "font": {
                "registered_name": FONT_NAME,
                "package_relative_path": FONT_PACKAGE_PATH,
                "sha256": _sha256_bytes(font_path.read_bytes()),
                "copied_to_fixtures": False,
            },
        },
        "anchor_target": {
            "quote": TARGET_QUOTE,
            "prefix": TARGET_PREFIX,
            "suffix": TARGET_SUFFIX,
            "base_version": "anchor-v0",
            "target_page": 1,
            "expected_box": _target_box(TARGET_BASELINE_Y),
            "coordinate_space": "unrotated_pdf_user_space_points",
        },
        "search_oracle": _search_oracle(),
        "fixtures": fixtures,
        "anchor_versions": anchor_versions,
    }
    manifest_bytes = (
        json.dumps(
            manifest,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_bytes(manifest_bytes)
    return manifest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate deterministic SPIKE-PDF-001 fixtures."
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Directory that will receive manifest.json and PDF fixtures.",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    output_dir = arguments.output_dir.resolve()
    manifest = generate(output_dir)
    summary = {
        "status": "ok",
        "output_dir": str(output_dir),
        "fixture_count": len(manifest["fixtures"]),
        "anchor_version_count": len(manifest["anchor_versions"]),
        "manifest": str(output_dir / "manifest.json"),
    }
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
