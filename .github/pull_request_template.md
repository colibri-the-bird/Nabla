## Task

- TASK-ID: `<TASK-ID>`
- Outcome:
- Evidence: `roadmap/evidence/<TASK-ID>.yaml`

## Scope

- [ ] PR changes exactly one task card.
- [ ] Branch is `task/<TASK-ID>-<slug>`.
- [ ] Changed paths fit `scope.paths`.
- [ ] Spec/ADR and implementation changes are not mixed.

## Verification

- [ ] `python tools/nabla_nav.py prepare <TASK-ID>`
- [ ] `python tools/nabla_nav.py check-scope <TASK-ID> --base origin/main`
- [ ] `python tools/nabla_nav.py evidence <TASK-ID>`
- [ ] `python tools/nabla_nav.py validate`
- [ ] `python tools/nabla_nav.py check-lock`
- [ ] Evidence maps every declared acceptance test and proof requirement.
- [ ] Evidence contains the current PR URL and explicit owner approval when required.
- [ ] There are no unresolved decisions.

## Owner merge

- [ ] All repository-required checks are successful on the current head.
- [ ] Conversations are resolved.
- [ ] The owner will perform the final manual merge; `completed` alone does not claim merge.
