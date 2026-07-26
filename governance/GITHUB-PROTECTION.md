# GitHub protection for `main`

**Status:** NOT CONFIRMED

This file records the required server-side settings. It is not evidence that they
are enabled. Keep `GITHUB-BRANCH-PROTECTION` in `governance/artifacts.yaml` as
`missing` until the settings below are visible on GitHub and the owner supplies
the confirmation record described below.

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
check.

## Staged activation

1. Open and merge the `BOOT-PILOT-001` pull request before strict required
   checks are enabled. All five exact check contexts must appear. Their green
   status on the current head is enforced by GitHub before the owner merges;
   it is not committed as self-referential evidence inside that same head.
2. Start `BOOT-PROTECT-001`. The owner enables the rules above and supplies the
   settings reference and confirmation date.
3. Open the protection-record PR under the enabled rules, update
   `governance/artifacts.yaml` to `available` and record the confirmation
   fields.
4. Let GitHub require all five checks on the current protection-record head,
   then merge manually. This green status is external closure data rather than
   a field that must be committed into the head it describes.

This order lets the first check contexts exist before they become required,
without treating a local convention as server-side protection.

## Confirmation record

Record the date, GitHub ruleset URL or screenshot reference, and pilot PR URL
both in `governance/artifacts.yaml` and `BOOT-PROTECT-001` evidence. Artifact
`available` proves the settings are visible; green checks on the current
protection-record head and manual merge prove task closure externally. Evidence
records the settings reference, confirmation date, PR URL and exact check names,
without claiming a committed snapshot proves its own final CI state. If the
repository plan does not support server-side protection for this private
repository, bootstrap remains blocked; do not replace this gate with a local
convention.
