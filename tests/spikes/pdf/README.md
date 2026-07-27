# SPIKE-PDF-001 experiment

This directory contains a bounded measurement harness. It does not implement
document ingestion, select a production PDF engine, or define a canonical
anchor dialect.

## Environment

Use Python 3.12 and install the spike-local lock into an isolated environment:

```powershell
py -3.12 -m venv .venv-spike-pdf
.\.venv-spike-pdf\Scripts\python.exe -m pip install -r tests/spikes/pdf/requirements.lock.txt
```

The dependency lock is evidence for this spike only. It does not add a Nabla
production dependency.

## Reproduce

Generate the deterministic fixture corpus:

```powershell
python tests/spikes/pdf/generate_fixtures.py --output-dir tests/spikes/pdf/fixtures
```

Run the canonical Windows x86-64 measurement after dependencies are available
locally:

```powershell
python tests/spikes/pdf/run_experiment.py --offline --output tests/spikes/pdf/results/windows-x86_64.json
```

The run has no retries and uses one isolated worker process at a time.
`--offline` installs a Python audit hook in every native-parser worker and
rejects Python socket audit events there. It is not an OS firewall: the
fixture generator and external version probes do not run under that hook, and
the experiment does not prove native-library network isolation. Password
cases pass a fixed public test sentinel by environment variable; command and
result capture redact it.

The command returns nonzero when required measurement capture, bounds,
determinism, isolation, or an independent fixture oracle fails. A malformed
PDF being rejected is an observation, not by itself a harness failure.

## Outputs

- `fixtures/manifest.json` records fixture hashes and independent expectations.
- `results/windows-x86_64.json` records raw commands, versions, license
  metadata, timings, memory samples, anchor outcomes, failure classifications,
  assertion links, and bounded stdout/stderr capture.
- `artifacts/contact-sheet.png` and `artifacts/anchor-v0-highlight.png` support
  visual inspection of render and highlight geometry.

Generated observations apply only to the recorded host and exact dependency
builds. Cross-version anchor matches remain proposals. Retargeting would be a
separate revision; this harness never writes canonical document state.
