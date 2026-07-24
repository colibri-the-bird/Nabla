## Task

- TASK-ID: `BOOT-...`
- Outcome:
- Evidence: `roadmap/evidence/BOOT-....yaml`

## Scope

- [ ] PR changes exactly one task card.
- [ ] Branch is `task/<TASK-ID>-<slug>`.
- [ ] Changed paths fit `scope.paths`.
- [ ] Spec/ADR and implementation changes are not mixed.

## Verification

- [ ] `python tools/nabla_nav.py prepare <TASK-ID>`
- [ ] `python tools/nabla_nav.py evidence <TASK-ID>`
- [ ] `python tools/nabla_nav.py validate`
- [ ] Evidence contains the current PR URL and successful commands.
- [ ] There are no unresolved decisions.

## Owner merge

- [ ] All five required checks are successful and current.
- [ ] Conversations are resolved.
- [ ] I performed the final manual merge.
