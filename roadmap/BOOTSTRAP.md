# Nabla Agent Bootstrap v0.1

**Статус:** активный ненормативный router
**Версия:** 0.1
**Дата:** 2026-07-24
**Основание:** `SPEC-NAVIGATION.md` v0.2

---

# 0. Назначение

Этот router управляет только созданием agent navigation, governance и CI до
появления production `ROADMAP.md`. Он не разрешает реализацию приложения и не
переопределяет нормативные specifications.

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
| `BOOT-PILOT-001` | Tooling pilot прошёл полный workflow | `BOOT-CI-001` |

# 2. Production gate

Production task остаётся заблокированной, пока одновременно не выполнены:

1. применимые normative specifications утверждены;
2. обязательные ADR/spikes закрыты;
3. `BACKUP-RECOVERY.md` получен или создан заново утверждённым spec PR;
4. portability artifacts получены или заменены новым утверждённым spike;
5. v1 DDL готов;
6. создан production `ROADMAP.md`;
7. server-side protection `main` включает required checks.

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

# 5. Завершение bootstrap

Agent infrastructure считается готовой после `BOOT-PILOT-001`. Это не снимает
production gate из раздела 2.
