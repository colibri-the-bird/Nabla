# PDF renderer and anchor spike

- **Artifact:** `PDF-SPIKE-v1`
- **Task:** `SPIKE-PDF-001`
- **Status:** available (owner-approved)
- **Execution date:** 2026-07-27
- **Measurement context manifest:** `83080ffe04524aa412efd5a43ef7e2e5cde754ba29e5006ffdc5d904e0e07ddc`
- **Fixture manifest:** `feec58ffc96a04b6effbff00e421a806026f9b4e7eec6659e2e83ada5dd2701d`
- **Raw result:** `tests/spikes/pdf/results/windows-x86_64.json`
- **Raw result SHA-256:** `5a727c8cb608fab55d8965b0d86c77abf6b8d7e09ae577ab7118def88810684f`
- **Owner approval:** [PR #11 approval record](https://github.com/colibri-the-bird/Nabla/pull/11#issuecomment-5092782019)

## 1. Outcome

The measured Windows x86-64 candidate can render, extract, search, and capture
same-version highlight geometry within the experiment bounds. The experiment
passed all 17 required harness assertions.

The measurements do not select a production PDF engine and do not define a
canonical anchor dialect:

- the original PDF remains the canonical immutable blob;
- render, extraction, search, and page fingerprints remain derived data;
- exact Document Version capture evidence is the only exact anchor result;
- every cross-version result remains a proposal;
- ambiguity and missing targets remain explicit degradation;
- retargeting would create a revision and is not performed by this harness;
- ADR-006 and ADR-011 remain downstream decisions.

The strongest decision input is that text, page, and visual evidence have
different failure modes. A composite capture can preserve those observations,
but no one candidate is safe as an automatic canonical retarget:

- exact text plus bounded context found the controlled target where present;
- a page insertion preserved exact target-page text and RGB hashes at the new
  page index, while a geometry-only move preserved text but changed RGB;
- a 90-degree rotation preserved the quote, page, and box oracle but reordered
  raw extraction and changed both exact page fingerprints;
- 64-bit visual dHash ranked some changed pages usefully, but also collided
  after a target-text mutation and produced a wrong-page tie after rotation;
- extraction order differed materially between the two measured extractors.

## 2. Scope and platform boundary

Measured:

- Windows 11, build `10.0.22631`, AMD64;
- CPython 3.12.13;
- pypdfium2/PDFium rendering and primary extraction;
- pdfplumber/pdfminer.six secondary extraction;
- pypdf structural fixture construction;
- ReportLab deterministic fixture generation;
- one serial worker process at a time.

Not measured:

- Linux, macOS, Android, iOS, or mobile packaging;
- another functioning rasterizer on this host;
- cross-PDFium-version replay;
- OCR;
- digital-signature validation;
- production reader UI, ingestion, persistence, or canonical retarget writes.

All runtime observations and performance numbers in this report are therefore
Windows-host observations, not product limits or cross-platform claims.

## 3. Reproduction and evidence

Fixture generation:

```text
python tests/spikes/pdf/generate_fixtures.py --output-dir tests/spikes/pdf/fixtures
```

Canonical measurement:

```text
python tests/spikes/pdf/run_experiment.py --offline --output tests/spikes/pdf/results/windows-x86_64.json
```

The recorded run completed in 103.328 seconds. It generated or exercised:

- 18 deterministic PDF fixtures;
- 10 controlled anchor versions;
- 38 isolated cases;
- 1 warm-up and 3 measured large-document runs;
- 3 identical render repetitions;
- 4 hostile inputs plus a forced timeout;
- a valid canary after every hostile or forced-timeout case.

The generator reproduced the full semantic manifest, including fixture bytes,
anchor/search/visual oracles, dependency provenance, and determinism metadata.
The controlled anchor target page uses a version-neutral frame, so declared
one-change-at-a-time mutations are not contaminated by a hidden version label.
The harness also verified:

- source fixture hashes were unchanged;
- the temporary directory and intermediate render directories were removed;
- no stdout or stderr capture exceeded 1 MiB;
- the result stayed below 16 MiB;
- no absolute Windows path or test password leaked into the result;
- all serialized numbers were finite;
- no required case was uncaptured;
- the overall 20-minute deadline was not exceeded.

`--offline` rejects Python socket audit events in each parser worker. It is not
an OS firewall: fixture generation and external version probes do not run
under that hook, and this experiment does not prove native-library network
isolation.

See:

- `tests/spikes/pdf/README.md`;
- `tests/spikes/pdf/fixtures/manifest.json`;
- `tests/spikes/pdf/results/windows-x86_64.json`;
- `tests/spikes/pdf/artifacts/contact-sheet.png`;
- `tests/spikes/pdf/artifacts/anchor-v0-highlight.png`.

## 4. Candidate and licensing observations

| Candidate/tool | Exact observed version | Use in experiment | License evidence and constraint |
|---|---:|---|---|
| pypdfium2 | 5.11.0 | PDFium binding | Installed metadata declares BSD-3-Clause, Apache-2.0, and dependency licenses. The wheel contains 19 hashed license files, including 16 Windows x64 `BUILD_LICENSES` files. |
| PDFium | 151.0.7920.0 | Renderer and primary extractor | `pdfium.dll` is 7,216,128 bytes, SHA-256 `0aa3abb1aa20798094c1a5f2d8cdea45b24a6e12cdc6c774de261dd522dbdf81`. PDFium has BSD-style terms plus build-specific third-party obligations. |
| pdfplumber | 0.11.9 | Secondary extraction | Package metadata omitted a license field; the upstream repository license is MIT. |
| pdfminer.six | 20251230 | pdfplumber extraction engine | Installed metadata and upstream repository declare MIT. |
| pypdf | 6.10.0 | Structural oracle and encryption fixture | Installed metadata and upstream repository declare BSD-3-Clause. |
| ReportLab | 4.4.9 | Deterministic PDF generation | Installed metadata and ReportLab documentation identify the open-source toolkit as BSD. |
| Pillow | 12.2.0 | Deterministic raster fixture and QA images | Installed metadata declares MIT-CMU. |
| Poppler wrappers | no executable version | Availability probe only | `pdftoppm` and `pdfinfo` resolved to bundled wrapper paths, but both returned exit 3 with `The system cannot find the path specified.` No Poppler rendering claim was made. Current upstream headers use GPL-2.0-or-later terms; an exact distributed build would need separate license review. |

Primary references:

- [pypdfium2 licensing and build-specific dependency notice](https://pypdfium2.readthedocs.io/en/stable/readme.html#licensing);
- [pypdfium2 PDFium thread-safety constraint](https://pypdfium2.readthedocs.io/en/stable/python_api.html#incompatibility-with-threading);
- [PDFium root license](https://pdfium.googlesource.com/pdfium/+/refs/heads/main/LICENSE);
- [pdfplumber MIT license](https://github.com/jsvine/pdfplumber/blob/stable/LICENSE.txt);
- [pdfminer.six license](https://github.com/pdfminer/pdfminer.six/blob/master/LICENSE);
- [pypdf license](https://github.com/py-pdf/pypdf/blob/main/LICENSE);
- [ReportLab open-source licensing](https://docs.reportlab.com/developerfaqs/#licensing);
- [Poppler project](https://poppler.freedesktop.org/);
- [Poppler C++ header license example](https://poppler.freedesktop.org/api/cpp/poppler-document_8h_source.html).

The fixture font is ReportLab's packaged `Vera.ttf`. The generator does not
copy the font file, records its hash, embeds a subset in deterministic fixture
PDFs, and records the packaged Bitstream Vera license file through installed
license inventory. This is fixture provenance, not approval for a production
font bundle.

Licensing conclusion: a PDFium-based option remains technically viable for
ADR-011 evaluation, but any selected build must pin and ship its exact license
set. This report is engineering evidence, not legal approval.

## 5. Rendering fidelity and page geometry

At 144 DPI, all four representative pages produced identical RGB hashes across
three independent serial renders.

Six independent interior-color probes matched their fixture oracles exactly:

| Probe | Expected RGB | Observed RGB |
|---|---:|---:|
| blue vector rectangle | 47, 111, 237 | 47, 111, 237 |
| amber vector circle | 242, 177, 52 | 242, 177, 52 |
| green vector region | 47, 133, 90 | 47, 133, 90 |
| purple vector region | 124, 58, 237 | 124, 58, 237 |
| scan-only red raster banner | 180, 35, 24 | 180, 35, 24 |
| hidden-layer green raster banner | 4, 120, 87 | 4, 120, 87 |

The controlled box fixture matched both declared MediaBox/CropBox pairs and
page rotations of 0 and 90 degrees. Sixteen PDF-to-bitmap-to-PDF corner
round-trips had a measured maximum error of 0.0 pt. The experiment tolerance
of 1.0 pt validates this harness only; it is not a product threshold.

Visual inspection of the final contact sheet found no clipping, overlap, blank
render, incorrect rotation, or misplaced highlight.

## 6. Text layer, glyph mapping, reading order, and search

Both measured extractors matched the controlled font oracle:

- mapped and observed: U+00E9, U+03A9, U+20AC;
- explicitly unmappable with the fixture's Vera cmap: U+0301, U+0416,
  U+1F642;
- no missing codepoint was silently reported as the requested Unicode value.

The scan-only page rendered visible text but extracted zero occurrences. The
visually equivalent hidden-text-layer page extracted its invisible needle once.
OCR was not invoked.

Extractor output was not interchangeable:

| Page | Normalized PDFium/pdfplumber similarity | Observation |
|---:|---:|---|
| 0 | 0.936170 | mostly similar text with mapping/layout differences |
| 1 | 0.035827 | materially different two-column reading order |
| 2 | 1.000000 | both correctly extracted no scan-only text |
| 3 | 1.000000 | both extracted the hidden text layer |

On the two-column page, PDFium returned PDF drawing order (left column, then
right column). pdfplumber returned geometry-oriented row order (left/right
interleaved). The spike records both and does not declare either canonical.

All 12 exact search oracles matched counts and pages, with raw character range
and geometry backmaps recorded. Important degraded behavior was explicit:

- NFC `Café` matched; the decomposed sequence with missing U+0301 did not;
- U+03A9 matched; missing U+0416 did not;
- a same-line hyphenated token matched;
- a token split across drawn lines did not;
- a repeated token returned two occurrences on the expected page;
- scan-only pixels did not become searchable text;
- invisible text did become searchable.

## 7. Same-version capture and highlight

The exact capture stored:

- document SHA-256;
- page index;
- raw character index and count;
- exact quote plus bounded prefix and suffix;
- page text SHA-256;
- exact RGB page SHA-256;
- 64-bit visual dHash;
- PDF-space union quad and normalized quad.

On the same Document Version:

- the exact quote occurred once;
- both context sides matched;
- text and visual page hashes matched;
- page-to-bitmap geometry replayed deterministically;
- highlight quad IoU against the independent drawing oracle was `0.993196`;
- no canonical state was written.

The 0.90 IoU and 1.0 pt round-trip tolerances are controlled-fixture harness
checks only.

## 8. Cross-version anchor behavior

| Version | Controlled change | Text result | Visual dHash best distance/page |
|---|---|---|---|
| V0 | baseline | `exact_same_version` | 0 / page 1 |
| V1 | text inserted before target | `proposal_unique`, quote plus context | 2 / page 1 |
| V2 | page inserted before target | `proposal_unique`, quote plus context | 0 / page 2 |
| V3 | target quote mutated | `not_found` | 0 / page 1 |
| V4 | duplicate quote with different context | 2 quote hits, 1 context hit, `proposal_unique` | 2 / page 1 |
| V5 | prefix mutated | unique quote with context degradation, `proposal_unique` | 0 / page 1 |
| V6 | suffix mutated | unique quote with context degradation, `proposal_unique` | 0 / page 1 |
| V7 | target geometry moved | `proposal_unique`, quote plus context | 7 / page 1 |
| V8 | target page rotated 90 degrees | unique quote with context degradation, `proposal_unique` | 9 / pages 0 and 2 tie |
| V9 | target block removed | `not_found` | 4 / page 1 |

Exact page text matched V0, V2, and V7. Exact RGB matched V0 and V2. In
particular, V2 preserved the unchanged target page at its shifted index, V7
preserved raw text while moving geometry, and V8 preserved quote/page/box
resolution while rotation reordered raw extraction and changed its text hash.

The perceptual ranking is useful evidence but unsafe as canonical retargeting:

- V2 correctly found a visually unchanged page after page insertion;
- V3 had distance 0 even though the target quote changed;
- V5 and V6 had distance 0 despite context mutation;
- V8 did not rank the rotated target page first and tied two other pages;
- V9 still ranked the former target page best after the target was removed.

No dHash threshold is proposed. The observations show why any future visual
fallback needs ambiguity policy, confidence calibration, independent evidence,
and owner-visible proposal review under ADR-006.

## 9. Large-document behavior

The stress fixture contains 128 pages and 408,344 extracted characters.
Generation was outside the measured interval. Each measured run opened the
document, extracted every page, and rendered pages 0, 64, and 127 at 144 DPI.

| Run | Open ms | Full extraction ms | Three renders ms | Wall ms | Peak child working set |
|---:|---:|---:|---:|---:|---:|
| 1 | 1.216 | 322.682 | 117.404 | 441.303 | 55.000 MiB |
| 2 | 0.987 | 285.522 | 124.009 | 410.519 | 55.074 MiB |
| 3 | 1.192 | 313.415 | 122.814 | 437.421 | 51.984 MiB |

The parent sampled the Windows child working set with
`GetProcessMemoryInfo`. These figures characterize one warm host and exact
build only. They do not establish a product memory or latency budget.

## 10. Encryption, malformed PDFs, and cleanup

Encrypted fixture:

- no password: isolated `PdfiumError`, exit 2;
- wrong password: isolated `PdfiumError`, exit 2;
- fixed public sentinel password: successful render/extraction, exit 0;
- the sentinel was passed through an environment variable and redacted from
  commands and raw result.

Hostile inputs:

- invalid header: isolated rejection;
- truncated tail: isolated rejection;
- corrupt xref: PDFium recovered and completed;
- 829,440,000-pixel extreme page estimate: rejected by the 20,000,000-pixel
  preflight limit before raster allocation;
- forced delay: killed by the parent timeout;
- a fresh valid canary succeeded after every hostile case and the forced
  timeout.

Each native-parser case ran in its own process. This matches the measured
failure-domain need and the upstream PDFium thread-safety warning, but the
final production process and sandbox boundary remains an ADR-011 decision.

## 11. Finite experiment limits

| Limit | Value |
|---|---:|
| measured library candidates | 2 (pypdfium2 and pdfplumber; only PDFium renders) |
| concurrency / retries | 1 / 0 |
| render | 144 DPI, RGB, 20,000,000 pixels/page |
| normal fixture | 16 MiB, 64 pages |
| stress fixture | 96 MiB, 512 pages |
| extracted output | 16 MiB/case |
| stdout / stderr | 1 MiB each/case |
| result JSON | 16 MiB |
| temporary data | 512 MiB |
| normal / hostile / stress timeout | 30 / 10 / 180 seconds |
| overall timeout | 20 minutes |
| child working set ceiling | 1.5 GiB |
| retries | none |
| network | Python socket audit events rejected in parser workers; no OS-native sandbox measured |

These bounds make the experiment reproducible and failure-bounded. They are not
release limits and do not authorize production ingestion.

## 12. Inputs for downstream ADRs

ADR-006 must still decide:

- selector and capture dialect;
- coordinate basis and rotation/crop normalization;
- exact-text, context, page, and visual fallback ordering;
- ambiguity, missing-target, and confidence policy;
- proposal review and retarget revision semantics;
- any engine-version migration evidence.

ADR-011 must still decide:

- renderer/parser and exact version pin;
- build and license distribution model;
- process/sandbox boundary and resource enforcement;
- verification that PDF JavaScript, actions, and all other document-supplied
  active content remain inert and unsupported under I6;
- API and lifecycle boundary;
- update, rollback, and security-patch policy;
- password and encryption feature policy;
- platform-specific packaging and verification.

The spike supplies measured input to those decisions. It approves neither ADR.

## 13. Measured limitations

- Only one functioning renderer build was available.
- Poppler wrappers were present but unusable, so no cross-renderer fidelity
  comparison was possible.
- Only one Windows x86-64 host was measured.
- No engine-upgrade replay was measured.
- PDF JavaScript, actions, and other active content were not included in the
  corpus. Their execution remains unconditionally prohibited by I6; this
  spike grants no exception.
- The worker Python socket audit hook is not an OS firewall and does not prove
  native-library network isolation.
- The fixture corpus is deterministic and representative, not a claim of PDF
  conformance coverage.
- The stress fixture is text-heavy; image-heavy and adversarial compression
  curves remain outside this task.
- No OCR, form, annotation mutation, signature validation, or production
  persistence was exercised.
- Perceptual dHash demonstrated collisions and wrong-page ties and must not be
  treated as exact identity.

These limitations are part of the outcome, not hidden failures.
