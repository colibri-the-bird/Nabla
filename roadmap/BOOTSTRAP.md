# Nabla Pre-development Bootstrap v0.2

**Статус:** активный ненормативный router
**Версия:** 0.2
**Дата:** 2026-07-26
**Основание:** `SPEC-NAVIGATION.md` v0.3

---

# 0. Назначение

Этот router управляет последовательной подготовкой репозитория до первой
implementation-задачи: agent navigation, governance, CI, измерительные spikes,
ADR, закрытие нормативного baseline, Data Catalog, contracts, DDL и production
`ROADMAP.md`. Он не разрешает реализацию приложения, не заменяет нормативные
specifications и не позволяет перескакивать через owner checkpoints.

# 1. Последовательность

Bootstrap выполняется последовательно:

| Task ID | Outcome | Depends on |
|---|---|---|
| `BOOT-NAV-001` | Navigation v0.2 готова к утверждению | — |
| `BOOT-SLICE-001` | Selector/slicer детерминирован и протестирован | `BOOT-NAV-001` |
| `BOOT-CARDS-001` | Task cards, evidence и context CLI работают | `BOOT-SLICE-001` |
| `BOOT-TRACE-001` | Spec lock, decisions и traceability проверяются | `BOOT-CARDS-001` |
| `BOOT-AGENTS-001` | Корневой `AGENTS.md` направляет Codex | `BOOT-TRACE-001` |
| `BOOT-CI-001` | GitHub checks блокируют несогласованные PR | `BOOT-AGENTS-001` |
| `BOOT-REPAIR-001` | Bootstrap lifecycle и evidence приведены к v2; создан полный DAG | `BOOT-CI-001` |
| `BOOT-PILOT-001` | Tooling pilot проходит пять CI contexts до strict protection | `BOOT-REPAIR-001` |
| `BOOT-PROTECT-001` | Protection `main` подтверждён отдельным protected-head PR | `BOOT-PILOT-001` |
| `SPIKE-CORE-PORTABILITY-001` | Измерена portability/runtime boundary | `BOOT-PROTECT-001` |
| `SPIKE-PDF-001` | Измерены PDF rendering и stable anchors | `SPIKE-CORE-PORTABILITY-001` |
| `SPIKE-BACKUP-RESTORE-001` | Измерены backup/restore/corruption paths | `SPIKE-PDF-001` |
| `SPIKE-REVISION-REPLAY-001` | Измерены identity/revision/outbox/replay paths | `SPIKE-BACKUP-RESTORE-001` |
| `ADR-RUNTIME-BOUNDARY-001` | Приняты ADR-001 и ADR-010 | `SPIKE-REVISION-REPLAY-001` |
| `ADR-MODULE-TRUST-001` | Принят ADR-007 | `ADR-RUNTIME-BOUNDARY-001` |
| `ADR-QUERY-DSL-001` | Принят ADR-003 | `ADR-MODULE-TRUST-001` |
| `ADR-REVISION-IDENTITY-001` | Приняты ADR-002, ADR-004, ADR-009 и ADR-012 | `ADR-QUERY-DSL-001` |
| `ADR-DOCUMENT-ENGINE-001` | Приняты ADR-006 и ADR-011 | `ADR-REVISION-IDENTITY-001` |
| `ADR-RETENTION-CRYPTO-001` | Приняты ADR-005 и ADR-008 | `ADR-DOCUMENT-ENGINE-001` |
| `AUDIT-ADR-GATE-001` | Проверены все 12 ADR; owner checkpoint 1 | `ADR-RETENTION-CRYPTO-001` |
| `SPEC-BASELINE-001` | Закрыты дыры и согласованы существующие normative specs | `AUDIT-ADR-GATE-001` |
| `SPEC-BACKUP-RECOVERY-001` | Создан и утверждён `BACKUP-RECOVERY.md` | `SPEC-BASELINE-001` |
| `SPEC-DATA-CATALOG-V1-001` | Утверждён Data Catalog v1 | `SPEC-BACKUP-RECOVERY-001` |
| `SPEC-CONTRACTS-CORE-V1-001` | Материализованы Kernel/Platform contracts | `SPEC-DATA-CATALOG-V1-001` |
| `SPEC-CONTRACTS-CONTENT-V1-001` | Материализованы Knowledge/Documents contracts | `SPEC-CONTRACTS-CORE-V1-001` |
| `SPEC-DDL-CORE-V1-001` | Готовы и проверены core DDL/migrations | `SPEC-CONTRACTS-CONTENT-V1-001` |
| `SPEC-DDL-CONTENT-V1-001` | Готовы и проверены content DDL/migrations | `SPEC-DDL-CORE-V1-001` |
| `AUDIT-FOUNDATION-CONFORMANCE-001` | Проверена сквозная согласованность; owner checkpoint 2 | `SPEC-DDL-CONTENT-V1-001` |
| `PREP-ROADMAP-PROD-001` | Созданы production roadmap и blocked scaffold card | `AUDIT-FOUNDATION-CONFORMANCE-001` |
| `AUDIT-SCAFFOLD-READINESS-001` | Финальный owner start gate активирует scaffold | `PREP-ROADMAP-PROD-001` |

В каждый момент ready может быть не более одной карточки. Завершаемая карточка
имеет право активировать только своего непосредственного successor; все более
поздние карточки остаются `blocked`.

## 1.1 Owner checkpoints

1. `AUDIT-ADR-GATE-001`: владелец проверяет ключевые технологические решения и
   последствия до изменения normative baseline.
2. `AUDIT-FOUNDATION-CONFORMANCE-001`: владелец проверяет сквозную связь
   specifications → catalog → contracts → DDL до составления production roadmap.
3. `AUDIT-SCAFFOLD-READINESS-001`: владелец отдельно разрешает начало разработки
   после проверки roadmap и первой implementation card.

На checkpoint можно вернуть затронутые карточки в работу и скорректировать
будущую часть DAG. Пройденные нормативные решения не переписываются молча:
изменение оформляется новым ADR/spec task с явным supersession.

# 2. Production gate

Production task остаётся заблокированной, пока одновременно не выполнены:

1. `main` защищён; required checks являются внешним merge gate для каждого
   актуального PR head;
2. четыре обязательных measured spikes доступны;
3. все двенадцать ADR приняты и прошли cross-consistency audit;
4. применимые normative specifications согласованы и утверждены;
5. `BACKUP-RECOVERY.md` создан из approved sources и measured evidence;
6. Data Catalog v1 не содержит полей без class/owner/writer/purpose;
7. machine-readable core/content contracts валидны;
8. v1 core/content DDL и migrations проходят isolated tests;
9. foundation conformance checkpoint утверждён владельцем;
10. создан production `ROADMAP.md` и проверена первая implementation card;
11. владелец явно прошёл `AUDIT-SCAFFOLD-READINESS-001`.

# 3. Branch и PR

Каждая task использует:

```text
branch: task/<TASK-ID>-<slug>
PR title: [<TASK-ID>] <outcome>
```

Нормативный и implementation diff нельзя смешивать. Владелец проекта выполняет
финальный merge вручную после зелёных checks.

# 4. Контекст

Codex получает `TASK-ID` в prompt и выполняет:

```text
python tools/nabla_nav.py prepare <TASK-ID>
```

Generated bundle сохраняется в `.nabla/context/<TASK-ID>/`, не коммитится и не
становится источником истины.

# 5. Завершение bootstrap и подготовки

Agent infrastructure считается готовой после `BOOT-PROTECT-001`. Полная
предразработочная подготовка считается готовой только после
`AUDIT-SCAFFOLD-READINESS-001`; до этого implementation card не может иметь
состояние `ready`. Валидатор дополнительно требует, чтобы ready implementation
card напрямую зависела от завершённого `AUDIT-SCAFFOLD-READINESS-001`.
