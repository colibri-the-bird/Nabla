# Nabla Specification Navigation v0.1

**Статус:** проект к утверждению  
**Дата:** 2026-07-13  
**Роль:** ненормативный маршрутизатор нормативного контекста  
**Не переопределяет:** `CONSTITUTION.md`, `ARCHITECTURE.md`, ADR, contracts,
module specifications, Data Catalog или DDL

---

# 0. Назначение

Спецификации Nabla намеренно подробны. Их полнота защищает данные и архитектуру,
но полная загрузка всех документов в контекст каждого агента ухудшает работу:

- вытесняет исходный код, тесты и результаты команд;
- затрудняет поиск реально применимых требований;
- повышает вероятность, что агент запомнит summary вместо нормативной
  формулировки;
- заставляет повторно читать десятки тысяч слов для локального изменения.

Настоящий документ определяет progressive-disclosure navigation layer:

1. короткий `AGENTS.md` задаёт неизменяемый порядок работы;
2. `ROADMAP.md` содержит task cards и является главным маршрутизатором;
3. generated `spec-index.json` перечисляет документы, sections и context packs;
4. `tools/spec_slice.py` извлекает только точные нормативные sections;
5. impact tags расширяют контекст, когда изменение пересекает границы;
6. validators доказывают, что selector не устарел и обязательное требование не
   потеряно.

Navigation layer не является второй архитектурой. Он хранит адреса, зависимости
и правила выбора, но не копирует нормативное содержание.

---

# 1. Основное решение

## 1.1 Три уровня входа

### `AGENTS.md`

Короткая постоянная инструкция. Она содержит только:

- иерархию источников истины;
- запрет реализации без active Roadmap task;
- порядок загрузки context pack;
- обязательные stop conditions;
- команды проверки;
- формат evidence при завершении.

`AGENTS.md` не содержит пересказ архитектуры, списки полей или module contracts.

### `ROADMAP.md`

Каждая исполнимая задача имеет task card с:

- одним проверяемым outcome;
- границей scope и non-goals;
- точными section selectors;
- impact tags;
- зависимостями и blocking decisions;
- затрагиваемыми contract IDs;
- acceptance tests и required evidence.

Roadmap является главным маршрутизатором контекста, но не нормативным источником
семантики продукта.

### Generated index и slicer

Index строится из headings и вручную проверяемой карты dependencies/context
packs. Slicer находит section по стабильному адресу и включает heading со всеми
его дочерними подразделами до следующего heading того же или более высокого
уровня.

## 1.2 Почему summaries недостаточно

Summary MAY помогать выбрать section, но MUST NOT использоваться для реализации
контракта. В task context включается точный нормативный текст выбранного section.

При расхождении selector description и нормативного текста действует
нормативный текст; расхождение считается navigation defect.

---

# 2. Stable section addressing

## 2.1 Document IDs

| ID | Canonical file |
|---|---|
| `CON` | `CONSTITUTION.md` |
| `ARCH` | `ARCHITECTURE.md` |
| `DATA` | `DATA-CLASSIFICATION.md` |
| `CAP` | `CAPABILITY-CONTRACT.md` |
| `MOD` | `MODULE-MANIFEST.md` |
| `LOOP` | `LOOP-SPEC.md` |
| `KNOW` | `KNOWLEDGE-MODULE.md` |
| `DOC` | `DOCUMENT-MODULE.md` |
| `BACKUP` | `BACKUP-RECOVERY.md` |
| `ROADMAP` | `ROADMAP.md` |

Новые документы получают уникальный короткий ID. ID не переиспользуется после
retirement.

## 2.2 Selector syntax

Нормативный selector имеет вид:

```text
DOC_ID:section_key
```

Примеры:

```text
CON:I10
ARCH:11.2
CAP:11.4
KNOW:23
DOC:11.3
```

`section_key` берётся из явного номера heading (`7`, `7.2`, `I13`). Heading title
проверяется index-ом, но не входит в identity selector.

Special selectors:

- `DOC_ID:meta` — title и metadata до первого numbered top-level section;
- `DOC_ID:full` — весь файл; разрешён только с явным обоснованием;
- `DOC_ID:7+children` эквивалентен обычному `DOC_ID:7` и MAY отображаться UI для
  ясности, но canonical stored form остаётся `DOC_ID:7`.

Line numbers запрещены как durable selector: они меняются от редакторских
правок.

## 2.3 Stability rules

После утверждения document version:

1. существующий `section_key` MUST NOT менять смысл молча;
2. новый материал вставляется как новый child key (`11.3`, `11.3.1`) без
   перенумерации unrelated sections;
3. перемещение требования обновляет все task/context refs атомарно;
4. удалённый selector остаётся redirect только на время declared deprecation;
5. major document rewrite MAY перенумеровать sections, но требует generated
   migration map и invalidation всех affected task cards;
6. duplicate section keys внутри одного документа запрещены.

## 2.4 Slice integrity

Каждый slice включает:

- canonical filename, document version/status и content hash;
- selector и полный heading title;
- точный section body без paraphrase;
- список автоматически добавленных prerequisite selectors;
- предупреждение, если document status не approved;
- source boundary между документами.

Slicer не удаляет MUST/MUST NOT, tables, examples или acceptance conditions
внутри выбранного section.

---

# 3. Task card context contract

## 3.1 Required shape

```yaml
task_id: V1-DOC-ANCHOR-001
outcome: string
scope:
  include: [string]
  exclude: [string]

context:
  baseline: [ContextPackRef]
  required: [SectionSelector]
  conditional:
    - when: TriggerExpression
      add: [SectionSelector | ContextPackRef]
  impact_tags: [ImpactTag]
  full_document_reads: []

contracts:
  reads: [ContractRef]
  writes: [ContractRef]
  changes: [ContractRef]

dependencies:
  tasks: [TaskId]
  decisions: [ADRRef | SpikeRef]

acceptance:
  tests: [TestRef]
  evidence: [EvidenceRequirement]
  invariants: [InvariantId]
```

Production task без `context`, `scope`, `acceptance` или `invariants` invalid.

## 3.2 Required vs conditional

- `required` читается до изменения кода или schema.
- `conditional` добавляется сразу после срабатывания trigger.
- Агент MUST NOT продолжать на старом slice после расширения impact scope.
- Неактивная ветвь не загружается «на всякий случай».

Пример: задача reader UI не загружает purge contract. Если в ходе работы она
начинает менять canonical anchor, trigger `canonical-write` добавляет Command,
Data Classification, revision, export и loop sections.

## 3.3 Full-document reads

Полный документ допустим только для:

- изменения самого cross-cutting contract;
- architecture/conformance review;
- major migration;
- генерации нового зависимого specification;
- расследования противоречия, границы которого ещё неизвестны.

Task card записывает причину. Обычная implementation task не использует
`full_document_reads`.

---

# 4. Impact tags

Impact tag не заменяет judgment. Он задаёт минимальное расширение контекста.

| Tag | Когда срабатывает | Минимальные sources |
|---|---|---|
| `canonical-write` | Новый/изменённый persistent domain write | `CON:I1`, `CON:I10`, `ARCH:7`, `DATA:2`, `CAP:10`, `CAP:11` |
| `immutable-fact` | `CF`, correction, observation | `CON:I2`, `DATA:4.1`, `CAP:11.9`, `LOOP:8`, `LOOP:10` |
| `revisioned-entity` | `CE`, heads, conflicts, undo | `CON:I3`, `ARCH:10.3`, `ARCH:10.4`, `CAP:11.6`, `CAP:20` |
| `relation` | Новый/изменённый `CR` или endpoint | `ARCH:10.5`, `DATA:4.3`, `MOD:17`, `LOOP:10` |
| `blob` | Original bytes, adoption, presence, GC | `ARCH:11`, `DATA:4.4`, `MOD:18`, `MOD:19` |
| `derived` | Parser, index, projection, cache, model | `CON:I4`, `ARCH:9`, `CAP:14`, `DATA:4.6` |
| `workflow` | Long operation/external effect/OT state | `CON:I10`, `ARCH:9`, `CAP:18`, `CAP:21` |
| `import` | Untrusted input or batch adoption | `CON:I1`, `CON:I14`, `ARCH:18`, relevant module import sections |
| `export` | Portable artifact or exporter | `CON:I16`, `ARCH:19`, `DATA:9`, `CAP:17`, `MOD:19` |
| `backup-recovery` | Backup, restore, maintenance read | `ARCH:19`, `DATA:10`, `MOD:19`, future `BACKUP` pack |
| `sensitive` | P2–P4, redaction, outbound, secret-like content | `CON:4.2`, `ARCH:18`, `DATA:6`, `DATA:12`, `CAP:9` |
| `ai-boundary` | AI read/proposal/tool/workflow | `CON:I13`, `ARCH:17`, `DATA:12`, applicable capability AI sections |
| `module-contract` | Manifest, dependency, activation, authority | `CON:I6`, `MOD:4`, `MOD:5`, `MOD:8`, `MOD:9`, `MOD:13` |
| `loop-coverage` | Новый field/producer/consumer/outcome | `CON:I7`, `CON:I8`, `LOOP:4`, `LOOP:6`, `LOOP:7`, `LOOP:10` |
| `offline-sync-ready` | Syncable ID/revision/blob semantics | `CON:I12`, `ARCH:10`, `ARCH:16`, `MOD:18` |
| `purge` | Physical destruction or cascade | `CON:I11`, `ARCH:18.6`, `DATA:11`, relevant module purge section |
| `failure-domain` | Parser/job/module/provider isolation | `CON:I15`, `ARCH:20`, `CAP:24`, relevant module reliability section |

Generated index expands tag entries with module-specific selectors. Missing
applicable module selector является validation error, а не разрешением читать
только generic contract.

---

# 5. Context packs

## 5.1 Pack properties

Context pack содержит только selectors и dependency metadata:

```yaml
pack_id: document-anchor-write
version: 1
extends: [canonical-write, revisioned-entity, relation, sensitive]
selectors:
  - DATA:16.2
  - DOC:10
  - DOC:11
  - DOC:12
  - DOC:25
  - DOC:33
triggers:
  changes_export_shape: [export]
```

Pack description MAY кратко объяснять область применения, но не пересказывает
требования.

## 5.2 Initial packs

До появления Roadmap поддерживаются как минимум:

- `spec-authoring`;
- `knowledge-note-core`;
- `knowledge-import`;
- `document-import`;
- `document-reader`;
- `document-anchor-write`;
- `module-activation`;
- `portable-export`;
- `backup-restore` после создания `BACKUP-RECOVERY.md`.

Roadmap task SHOULD ссылаться на pack и добавлять узкие task-specific selectors,
а не копировать большой общий список.

## 5.3 Pack versioning

Изменение selectors, которое расширяет или сужает обязательный контекст,
повышает pack version. Active task pin-ит exact pack version или пересобирается
при старте.

Pack hash вычисляется из normalized selectors/dependencies, но не заменяет hashes
нормативных документов.

---

# 6. Agent execution protocol

## 6.1 Start

Агент обязан:

1. открыть корневой `AGENTS.md`;
2. выбрать ровно одну active Roadmap task;
3. проверить её dependencies/blockers;
4. получить slice по pinned packs/selectors;
5. прочитать scope exclusions и acceptance tests;
6. перечислить предполагаемые impact tags до первой mutation.

## 6.2 During work

При обнаружении нового затронутого concept агент:

1. останавливает изменение этого участка;
2. добавляет impact tag/conditional context;
3. пересобирает slice;
4. проверяет, не изменились ли scope, contracts и required tests;
5. продолжает только после closure.

## 6.3 Completion

Evidence содержит:

- task ID;
- фактически использованные selectors и document hashes;
- изменённые contract/catalog/schema IDs;
- сработавшие impact tags;
- tests/commands и результаты;
- unresolved decisions;
- подтверждение отсутствия изменения outside scope.

Фраза «реализовано по архитектуре» без selector/test evidence недостаточна.

## 6.4 Stop conditions

Агент прекращает спорную реализацию, если:

- selectors не разрешаются или указывают на incompatible version;
- два нормативных sections противоречат друг другу;
- persistent field не имеет class/owner/writer/loop-or-purpose;
- capability/manifest reference отсутствует;
- требуется неутверждённый ADR в blocking point;
- task требует расширения authority, external effect или purge вне scope;
- acceptance test невозможно сформулировать из active contract.

Он создаёт specification defect/ADR request, а не выбирает удобную семантику
молча.

---

# 7. Context budget policy

## 7.1 Budget goals

Для обычной implementation task:

- routing metadata и summaries: до 1,500 слов;
- baseline + normative slices: целевой максимум 12,000 слов;
- warning threshold: 16,000 слов;
- не менее половины полезного контекста SHOULD оставаться под код, tests,
  command output и reasoning.

Это policy по умолчанию, а не обещание одинакового token count для всех models.
Если корректный task slice превышает threshold, task сначала делится по contract
boundary. Требования не удаляются ради бюджета.

## 7.2 Deduplication

Slicer:

- объединяет повторяющиеся selectors;
- не включает parent section второй раз, если он уже полностью выбран;
- включает metadata документа один раз;
- сортирует sections в порядке исходного файла;
- сообщает word/character estimate до запуска агента.

## 7.3 Cached context

Host MAY кэшировать slices по:

```text
task_id + pack versions + document hashes + selectors
```

Изменение любого normative hash инвалидирует cache. Модельная память или старый
chat context не считаются доказательством актуальности.

---

# 8. Generated index

## 8.1 Source and generated fields

Вручную поддерживаются:

- document ID → canonical path;
- authority rank;
- dependency edges;
- context packs и impact-tag expansions;
- redirects/deprecations.

Автоматически извлекаются:

- title/version/status/date;
- headings и section ranges;
- word/character counts;
- content hashes;
- outbound document references;
- duplicate keys и unresolved selectors.

Generated values MUST NOT редактироваться как независимая истина.

## 8.2 Validation

`spec-index validate` или эквивалентная команда проверяет:

1. canonical file существует;
2. heading parse deterministic;
3. section keys unique;
4. каждый selector/redirect/pack разрешается;
5. dependency graph acyclic там, где cycle запрещён;
6. document references существуют либо declared `planned`;
7. approved document не зависит нормативно от draft lower-level contract без
   explicit compatibility note;
8. task card не использует `full` без reason;
9. context budget рассчитан;
10. changed normative section перечисляет affected packs/tasks.

## 8.3 Security

Index/slicer:

- читает только repository files;
- не исполняет Markdown/code blocks;
- не следует symlinks за project root;
- не загружает network content;
- не принимает shell fragments из task card;
- экранирует filenames и selectors;
- имеет finite file/count/output limits.

---

# 9. Relationship with Roadmap and AGENTS

## 9.1 What belongs in Roadmap

Roadmap владеет:

- ordering tasks;
- current status/dependencies;
- task-specific context selection;
- acceptance/evidence routing;
- milestone/gate mapping.

## 9.2 What belongs in AGENTS

AGENTS владеет только execution protocol entrypoint и commands. Он ссылается на
Roadmap task и этот navigation contract, но не повторяет их tables.

## 9.3 What stays in specifications

Only normative specifications own:

- semantics;
- schemas/contracts;
- MUST/MUST NOT;
- data classification;
- authority;
- loops/outcomes;
- export/recovery guarantees.

Если изменение требует поправить одинаковый смысл одновременно в summary и
specification, summary слишком подробен и должен быть сокращён до selector.

---

# 10. Rollout order

Navigation layer вводится без задержки нормативной последовательности:

1. утвердить selector/addressing contract;
2. создать generated index и read-only slicer;
3. проверить текущие документы на unique keys/references;
4. при создании `ROADMAP.md` дать каждой task context contract;
5. после Roadmap создать короткий root `AGENTS.md`;
6. включить selector/impact validation в CI до production implementation;
7. не создавать вручную отдельные summaries каждого документа.

`DOCUMENT-MODULE.md`, `BACKUP-RECOVERY.md`, ADR и DDL продолжают нормативную
последовательность параллельно; navigation artifacts остаются support layer.

---

# 11. Acceptance criteria

Navigation v0.1 готова к утверждению, если:

1. Roadmap остаётся главным task/context router;
2. AGENTS остаётся коротким entrypoint;
3. нормативные тексты не дублируются;
4. selectors не зависят от line numbers;
5. section stability/versioning определены;
6. task card имеет required/conditional context и impact tags;
7. cross-cutting requirements добавляются автоматически по tags;
8. full-document read является исключением с причиной;
9. slicer возвращает exact text, metadata и hashes;
10. stale/unresolved selectors блокируют task;
11. budget не достигается удалением требований;
12. completion evidence перечисляет реально использованный context;
13. index generated fields не становятся parallel source of truth;
14. security model запрещает execution/network/path escape;
15. rollout не блокирует создание следующих нормативных документов.

