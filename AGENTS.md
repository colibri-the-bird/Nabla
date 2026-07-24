# Nabla Codex Entry Point v0.1

**Статус:** активная инструкция репозитория
**Версия:** 0.1

Эта инструкция действует для всего репозитория. Она маршрутизирует работу, но не
переопределяет нормативные specifications.

# 0. Source hierarchy

При конфликте действует порядок:

1. `CONSTITUTION.md`;
2. `ARCHITECTURE.md`;
3. принятые ADR;
4. data/capability/module/loop/protocol specifications;
5. module specifications, Data Catalog, schemas и DDL;
6. task card;
7. код и тесты.

Нельзя выбирать удобную семантику между противоречащими источниками.

# 1. Mandatory task identity

Mutation разрешена только при наличии одного явного `TASK-ID` в prompt.

Если `TASK-ID` отсутствует:

- разрешены исследование и `python tools/nabla_nav.py list-ready`;
- запрещены изменения файлов, dependency state и внешних систем;
- запросите у владельца конкретный task ID.

Один Codex run выполняет одну task card. Ветка имеет вид
`task/<TASK-ID>-<slug>`, PR title — `[<TASK-ID>] <outcome>`.

# 2. Start protocol

До первой mutation:

```text
python tools/nabla_nav.py validate
python tools/nabla_nav.py prepare <TASK-ID>
```

Прочитайте только:

1. `roadmap/tasks/<TASK-ID>.yaml`;
2. `.nabla/context/<TASK-ID>/manifest.json`;
3. `.nabla/context/<TASK-ID>/context.md`;
4. код и тесты внутри `scope.paths.include`.

Не читайте полные specifications «на всякий случай». `DOC:full` допустим только
если task card содержит причину.

# 3. During work

- Соблюдайте include/exclude scope и path patterns.
- Не добавляйте production dependency без отдельного утверждённого решения.
- Не смешивайте normative spec/ADR и implementation в одном PR.
- Не меняйте Конституцию, release gate или acceptance tests для удобства.
- Не изменяйте чужую module schema, authority, network/outbound flow, purge,
  recovery path или runtime code execution вне явного scope.
- При новом impact concept остановите затронутое изменение, добавьте conditional
  context/impact tag отдельным изменением и повторите `prepare` с нужным
  `--trigger`.

Generated `.nabla/context` не коммитится и не является источником истины.

# 4. Stop conditions

Остановите спорную mutation и зарегистрируйте defect/ADR need, если:

- selector, pack version или context hash устарел;
- dependencies или artifacts заблокированы;
- применимые нормативные sections противоречат друг другу;
- implementation зависит от draft specification;
- persistent field не имеет class/owner/writer/loop-or-purpose;
- capability/manifest/contract reference отсутствует;
- требуется authority, external effect или purge вне scope;
- acceptance test невозможно вывести из active contract.

# 5. Completion

Запустите task-specific tests и:

```text
python tools/nabla_nav.py check-scope <TASK-ID> --base origin/main
python tools/nabla_nav.py evidence <TASK-ID>
python tools/nabla_nav.py validate
```

Evidence должен перечислять context manifest hash, selectors/document hashes,
impact tags, changed paths/contracts, команды с exit codes, unresolved decisions
и PR URL. Card переводится в `completed`, когда outcome и локальные acceptance
tests завершены и evidence готов для PR gate. Task считается закрытой только
после зелёного CI и ручного merge владельцем.
