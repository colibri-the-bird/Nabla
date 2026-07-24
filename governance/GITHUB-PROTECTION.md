# GitHub protection for `main`

**Status:** NOT CONFIRMED

This file records the required server-side settings. It is not evidence that they
are enabled. Keep `GITHUB-BRANCH-PROTECTION` in `governance/artifacts.yaml` as
`missing` until the settings below are visible on GitHub and a pilot PR passes.

## Required rules

Configure a ruleset or protected branch rule for `main`:

- require a pull request before merging;
- require branches to be up to date before merging;
- require linear history;
- require all conversations to be resolved;
- block force pushes;
- block branch deletion;
- set required approving reviews to zero because the repository currently uses
  one GitHub account;
- leave the final merge as an explicit owner action.

Require these exact, unique status checks:

1. `navigation-linux`
2. `navigation-windows`
3. `task-card-gate`
4. `scope-and-evidence-gate`
5. `spec-lock-and-traceability-gate`

The workflow has no path filters, so every pull request reports every required
check. Enable strict required checks only after all five names have appeared on
the first pilot pull request.

## Confirmation record

Record the date, GitHub ruleset URL or screenshot reference, and successful
pilot PR URL in the `BOOT-PILOT-001` evidence. If the repository plan does not
support server-side protection for this private repository, bootstrap remains
blocked; do not replace this gate with a local convention.
