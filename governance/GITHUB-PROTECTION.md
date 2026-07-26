# GitHub protection for `main`

**Status:** ENABLED — OWNER CONFIRMATION PENDING

This file records the required server-side settings. It is not evidence that they
are accepted by the owner. GitHub API readback confirms that the settings below
are enabled, but `GITHUB-BRANCH-PROTECTION` remains `missing` until the owner
explicitly approves this record and the confirming PR is evaluated under the
protection.

## Observed server state

- repository: `colibri-the-bird/Nabla`
- branch: `main`
- observed at: `2026-07-26T17:05:20Z`
- settings reference:
  `https://api.github.com/repos/colibri-the-bird/Nabla/branches/main/protection`
- settings page: `https://github.com/colibri-the-bird/Nabla/settings/branches`
- pilot PR: `https://github.com/colibri-the-bird/Nabla/pull/8`
- check provider: GitHub Actions (`app_id: 15368`)
- owner confirmation reference: pending

Authenticated API readback reported `main.protected: true`, strict status checks,
admin enforcement, required pull requests with zero approving reviews, linear
history, required conversation resolution, blocked force pushes and deletions,
and disabled auto-merge. The five app-pinned checks are:

1. `navigation-linux`
2. `navigation-windows`
3. `task-card-gate`
4. `scope-and-evidence-gate`
5. `spec-lock-and-traceability-gate`

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

The observed timestamp, settings reference, pilot PR URL and exact check names
are recorded above and in `governance/artifacts.yaml`. After explicit owner
approval, the artifact becomes `available` and the approval reference is added
to this record and `BOOT-PROTECT-001` evidence. Green checks on the current
protection-record head and manual merge prove task closure externally; committed
evidence does not claim to prove its own final CI state. If server-side
protection later becomes unavailable, bootstrap becomes blocked again; do not
replace this gate with a local convention.
