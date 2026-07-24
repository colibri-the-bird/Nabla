# Nabla Loop Specification v0.1

**Статус:** проект к утверждению  
**Дата:** 2026-07-12  
**Нормативная основа:** `CONSTITUTION.md` v0.1, `ARCHITECTURE.md` v0.1, `DATA-CLASSIFICATION.md` v0.1, `CAPABILITY-CONTRACT.md` v0.1, `MODULE-MANIFEST.md` v0.1  
**Следующий зависимый документ:** `KNOWLEDGE-MODULE.md`

---

# 0. Назначение

Loop связывает собираемые или создаваемые предметные данные с реальным потребителем, решением, действием и проверяемым пользовательским outcome.

Настоящий документ определяет:

- first-class `LoopDescriptor` для domain/value loops;
- first-class `TechnicalPurposeDescriptor` для служебных данных и mechanisms;
- producer → data → consumer → decision/action → outcome closure;
- связь loops с Data Catalog fields, capabilities, workflows, processors и UI;
- правила field coverage;
- collection cost, privacy burden и proportionality;
- review, pause, deprecation и retirement;
- runtime `LoopConfiguration` и Loop Registry;
- AI proposals и запрет создания полномочий через loop;
- validators, conformance и acceptance tests.

Цель документа — технически исключить:

- сбор данных «на всякий случай»;
- capability без реального normative consumer;
- metric/dashboard без решения, которое они поддерживают;
- бесконечное накопление наблюдений без review/sunset;
- служебные поля, прикрытые фиктивным domain loop;
- domain data, прикрытые расплывчатым «нужно системе»;
- телеметрию, собираемую только ради доказательства полезности другой телеметрии;
- AI-generated loop, который расширяет permissions, schemas или outbound policy;
- удаление historical data при pause/retirement loop.

## 0.1 Нормативность

MUST, MUST NOT, SHOULD и MAY используются в смысле `CONSTITUTION.md`.

При конфликте действуют Constitution, Architecture, Data Classification, Capability Contract и Module Manifest. Loop не переопределяет data class, sensitivity, permission, retention, capability effect или module ownership.

## 0.2 Не-цели

Документ не определяет:

- UI конкретного dashboard;
- математическую модель обучения/памяти;
- конкретные product metrics;
- расписание пользователя;
- generic workflow execution engine;
- произвольный visual-programming runtime;
- causal inference из корреляций;
- automatic optimization objective для ИИ;
- поля Knowledge/Documents entities;
- обязательную телеметрию использования UI.

Loop описывает проверяемый value/feedback contract, а не исполняемую программу.

---

# 1. Основные инварианты

1. Каждый persistent subject field покрыт минимум одним exact active `LoopRef` либо допустимым inherited-loop binding.
2. Каждый service field покрыт exact `TechnicalPurposeRef`.
3. Один field имеет ровно один primary coverage mode: `loop`, `inherited_loop` или `technical_purpose`.
4. Loop имеет минимум одного реального producer, normative consumer и outcome.
5. Consumer существует в текущем или явно заявленном release path; гипотетический «будущий AI/analytics» недостаточен.
6. UI display, cache, index или export сами по себе не доказывают practical consumption.
7. Consumer приводит к явному decision, action, artifact use или outcome evaluation.
8. Loop не исполняет code, не выдаёт permissions и не создаёт capability.
9. Все Command/Query/Workflow refs разрешаются через active Registries и сохраняют собственные policies.
10. Collection frequency, manual burden, storage, compute, privacy и external cost конечны и объявлены.
11. Raw observation не подменяется derived metric, recommendation или confidence.
12. Loop имеет review policy и условия pause/retirement.
13. Pause/retirement останавливает новую exclusive collection, но не удаляет canonical history.
14. Technical purpose содержит protected invariant, consumer, failure consequence, cost и retention.
15. Loop/technical-purpose descriptor конкретной version immutable и hash-covered.
16. Runtime configuration меняется новой `CE` revision, а validation result остаётся `DD`.
17. AI proposal не действует до обычного Apply Command и не расширяет authority.
18. Invalid required loop/coverage блокирует module activation или exclusive producer capability fail-closed.

---

# 2. Понятия и границы

## 2.1 Loop Descriptor

Immutable revision view contract, описывающий purpose, graph roles, data bindings, outcomes, costs, review и conformance loop.

Descriptor имеет два допустимых origins:

- `built_in` — exact baseline artifact из Module Manifest;
- `runtime_definition` — current immutable revision user/system-owned `LoopDefinition CE`, созданная через approved module extension point.

Изменение runtime definition создаёт новую `CE` revision и новый descriptor hash; in-place mutation запрещена. Runtime definition использует только уже зарегистрированные schemas, fields, capabilities и workflows и не добавляет executable code.

## 2.2 Loop Configuration

Runtime `CE`, связывающая exact Loop Descriptor с scope, enablement, cadence, budgets и пользовательскими policy overrides.

## 2.3 Loop Instance

Effective pairing конкретной descriptor version и current configuration revision в одной Registry generation.

## 2.4 Producer

Capability, workflow, import или promoted observation, создающие declared canonical/derived data node loop.

## 2.5 Consumer

Реальный UI, user decision surface, Query, processor, workflow или module, использующий data для declared purpose и ведущий к outcome/action.

## 2.6 Decision

Явный выбор пользователя или registered policy между bounded alternatives, включая `no_action`.

## 2.7 Action

Declared Command/Workflow либо проверяемое использование artifact. Recommendation или draft не является action до принятия.

## 2.8 Outcome

Проверяемая полезность для пользователя/domain: доступ/использование artifact, поддержанное решение, завершённый workflow result или наблюдаемое изменение.

## 2.9 Feedback

Путь от action/use к outcome evidence, следующей observation, revision или review decision.

## 2.10 Technical Purpose

Structured justification service data/mechanism через integrity, security, recovery, transport, idempotency, migration, observability или bounded performance outcome.

## 2.11 Loop и Workflow

Workflow исполняет конечный state machine и владеет durable `OT` transitions.

Loop:

- не исполняет stages;
- не является scheduler;
- не вызывает capabilities самостоятельно;
- описывает, почему producers/consumers/actions существуют и как их value path замыкается;
- MAY ссылаться на Workflow как producer/action/outcome path.

Workflow без domain loop MAY иметь Technical Purpose. Loop без executable Workflow допустим, например artifact create–retrieve–revise.

## 2.12 Loop и metric

Metric является `CE` definition + `DD` values и может быть consumer/decision input внутри loop.

Metric не является loop, если не определены:

- решение, которое он поддерживает;
- actor;
- action/no-action semantics;
- outcome/review;
- стоимость и failure behavior.

---

# 3. Identity, ownership и version

## 3.1 Loop ID

```text
<owner-namespace>.<domain-or-resource>.<purpose>
```

Примеры:

```text
knowledge.note.edit_retrieval
documents.reading.resume
learning.review.feedback
analytics.objective.progress_decision
```

Правила:

- 3–6 lowercase dot-separated segments;
- segment соответствует `[a-z][a-z0-9_-]*`;
- ID начинается с owner module namespace;
- ID не содержит version, platform, UI wording или model name;
- rename создаёт новый loop и coverage migration;
- ID уникален во всём Loop Registry.

## 3.2 Technical Purpose ID

```text
<owner-namespace>.technical.<mechanism>
```

Kernel использует reserved namespace:

```text
kernel.technical.command_idempotency
kernel.technical.transactional_outbox
kernel.technical.migration_recovery
```

## 3.3 Identity

```text
(descriptor_id, semantic_version, contract_hash)
```

Одинаковые ID/version MUST иметь одинаковый hash.

## 3.4 Ownership

- Domain Loop Descriptor owned одним module.
- Technical Purpose owned module либо Kernel component.
- Runtime Loop Configuration owned тем же module policy surface, но пользователь является actor revisions.
- Shared ownership запрещён.
- Cross-module loop имеет одного coordinating owner и exact public dependencies participants.
- Loop ownership не передаёт ownership data/capabilities других modules.

---

# 4. Loop Descriptor

## 4.1 Common schema

```yaml
loop_id: LoopId
version: SemVer
contract_hash: Hash
owner_module: ModuleId
status: experimental | active | deprecated | disabled
origin: built_in | runtime_definition
definition_revision: RevisionRef | null
kind: artifact_use | observation_feedback | decision_action

summary: LocalizedTextRef
purpose: PurposeDeclaration
beneficiaries: [BeneficiaryDeclaration]
subject_scope: [SubjectDeclaration]

outcomes: [OutcomeDeclaration]
stages: [LoopStageDeclaration]
edges: [LoopEdgeDeclaration]
data_bindings: [LoopDataBinding]
producers: [ProducerDeclaration]
consumers: [LoopConsumerDeclaration]
decisions: [DecisionDeclaration]
actions: [ActionDeclaration]
feedback: FeedbackDeclaration

availability: LoopAvailabilityDeclaration
collection_cost: CollectionCostDeclaration
review: LoopReviewPolicy
configuration_schema: SchemaRef

acceptance_tests: [TestRef]
compatibility: CompatibilityDeclaration
deprecation: LoopDeprecationDeclaration | null
```

Каждый список присутствует явно. Unknown field отклоняется по умолчанию.

Для `built_in` значение `definition_revision` равно `null`, а exact descriptor входит в module artifact bundle. Для `runtime_definition` revision обязательна, owner module предоставляет approved extension point/schema, а Registry hash-ит normalized revision content.

## 4.2 Purpose declaration

```yaml
purpose:
  statement: string
  user_or_domain_need: string
  decision_or_use_enabled: string
  excluded_uses: [string]
  success_without_telemetry: AcceptanceEvidenceRef | null
```

Purpose является конкретным. Недопустимы без уточнения:

- «улучшить опыт»;
- «для аналитики»;
- «может пригодиться»;
- «для AI»;
- «общая персонализация»;
- «собирать больше данных».

## 4.3 Beneficiary

Beneficiary:

```yaml
beneficiary_id: string
kind: user | user_goal | domain_integrity
benefit: string
```

`module`, `dashboard`, `model` или `provider` не являются конечным beneficiary без связи с user/domain outcome.

## 4.4 Subject scope

Subject declaration ограничивает:

- entity/catalog types;
- container scope;
- time/grain;
- included/excluded populations;
- missing/not-applicable semantics;
- sensitivity ceiling;
- cross-module dependencies.

Scope не создаёт DataScope permission. Он должен быть subset effective capability/data policies.

---

# 5. Loop kinds и closure profiles

## 5.1 `artifact_use`

Используется для notes, documents, annotations, templates, layouts и других user-authored artifacts.

Минимальный closure:

```text
create/import/revise
→ canonical artifact
→ retrieve/navigate/read/use consumer
→ user/domain use
→ revise/archive/link/export decision
```

Требуется:

- явный producer Command/import;
- canonical artifact binding;
- минимум один normative retrieval/use consumer;
- action/use surface;
- revision/archive/follow-up path;
- acceptance evidence, что artifact остаётся accessible и useful без обязательной hidden usage telemetry.

Просто хранение или индексирование не замыкает loop.

## 5.2 `observation_feedback`

Используется для learning attempts, review observations, reading checkpoints, health/finance observations и progress signals.

Минимальный closure:

```text
observation
→ interpretation/projection
→ decision/recommendation
→ accepted action or explicit no_action
→ later observation/review
```

Требуется:

- raw `CF` observation semantics;
- versioned interpretation/model;
- uncertainty/freshness;
- decision actor;
- action/no-action options;
- feedback cadence или explicit terminal review;
- запрет объявления causality только из correlation.

## 5.3 `decision_action`

Используется для explicit objective, import/export/AI proposal application, plan execution и других domain decisions.

Минимальный closure:

```text
intent/context
→ decision
→ Command/Workflow
→ domain result/status
→ review/follow-up
```

Требуется:

- bounded alternatives;
- authority/confirmation path;
- idempotent action;
- typed terminal outcome;
- compensation/undo/irreversibility visibility;
- follow-up decision либо declared terminal completion.

## 5.4 Запрещённые pseudo-kinds

Не являются самостоятельными loop kinds:

- dashboard;
- metric;
- cache/index;
- logging;
- audit;
- backup;
- generic AI context;
- «data lake»;
- future analytics.

Они включаются в существующий domain loop либо получают Technical Purpose.

---

# 6. Graph model

## 6.1 Node kinds

```text
producer
canonical_data
derived_data
consumer
decision
action
outcome
review
```

## 6.2 Edge kinds

```text
produces
derives
reads
informs
selects
executes
evaluates
updates
retires
```

Edge declaration:

```yaml
edge_id: string
from: LoopNodeRef
to: LoopNodeRef
kind: produces | derives | reads | informs | selects | executes | evaluates | updates | retires
condition: DeclarativeCondition | always
maximum_lag: duration | not_applicable
failure_behavior: FailureBehavior
```

`condition` использует schema-bound declarative predicates и не исполняет code.

## 6.3 Closure rules

Validator доказывает:

1. Каждый subject canonical data node достижим от producer.
2. Каждый subject node имеет путь к required consumer.
3. Required consumer имеет путь к decision, action/use или outcome.
4. Action имеет путь к outcome/review либо declared terminal completion.
5. Outcome имеет evidence path.
6. Derived node имеет canonical inputs, definition/model version и freshness.
7. Нет orphan producer output.
8. Нет sink consumer, который только копирует данные без use.
9. Optional path не является единственным closure proof.
10. Failure path не превращается в hidden silent success.

## 6.4 Cycles

Feedback edge MAY образовывать semantic cycle. Loop graph не является runtime execution graph, поэтому cycle не запускает рекурсию.

Workflow/capability dependency cycles остаются запрещены своими contracts.

## 6.5 Fan-in и fan-out

Несколько producers/consumers допустимы, если:

- ownership и source provenance сохраняются;
- duplicate observations не создаются;
- sensitivity вычисляется по effective inputs;
- cost учитывает все paths;
- primary outcome не становится неоднозначным.

---

# 7. Outcomes и evidence

## 7.1 Outcome declaration

```yaml
outcome_id: string
statement: string
kind: artifact_access_use | decision_support | workflow_result | observed_change
beneficiary_ref: BeneficiaryRef
decision_supported: DecisionRef | null
evidence_mode: acceptance_test | existing_query | explicit_review | canonical_observation
evidence_refs: [CapabilityOrTestRef]
success_semantics: string
failure_semantics: string
uncertainty_semantics: string
minimum_usefulness: string
```

## 7.2 Outcome vs proxy

Количество records, clicks, streak, model score или dashboard visits не считаются outcome автоматически.

Proxy допустим, если:

- связь с outcome объяснена;
- limitations/uncertainty объявлены;
- proxy не заменяет raw evidence;
- decision не опирается на него вне validated scope;
- смена formula не переписывает observations.

## 7.3 Evidence without telemetry

Artifact-use loop MAY доказывать полезность через:

- end-to-end create/export/retrieve/revise tests;
- user-requested review;
- explicit user action;
- существующие canonical records.

Loop MUST NOT создавать hidden read/click telemetry только для доказательства собственного существования.

## 7.4 Missing и uncertainty

Outcome contract различает:

- success;
- failure;
- unknown;
- insufficient data;
- not_applicable;
- stale evidence.

`unknown` не интерпретируется как failure или zero.

## 7.5 Causality

Observation feedback loop не заявляет причинный effect intervention без отдельного экспериментального/causal design.

UI и model output используют формулировки association/recommendation, соответствующие evidence.

---

# 8. Producers и collection

## 8.1 Producer declaration

```yaml
producer_id: string
kind: command | workflow_result | import | system_observation | promoted_processor_result
source_ref: CapabilityOrWorkflowRef
output_catalog_refs: [CatalogTypeOrFieldRef]
collection_mode: explicit_user | user_action_side_effect | scheduled | device_observation | external_import
trigger: TriggerDeclaration
frequency_bound: FrequencyBound
batch_bound: int
consent_or_notice: ConsentNoticePolicy
paused_behavior: reject | omit_optional_fields | queue_bounded
failure_behavior: FailureBehavior
```

## 8.2 Producer validation

Validator проверяет:

- declared capability writes совпадают с output catalog refs;
- class/writer корректны;
- syncable effect имеет outbox;
- observation semantics/version/provenance определены;
- automatic trigger bounded;
- producer доступен только при effective active loop/configuration;
- collection не продолжается бесконечно при unavailable required consumer.

## 8.3 Explicit user input

User explicitly creating a note/document/annotation является достаточным collection intent для заявленного artifact-use loop, но не разрешает собирать unrelated telemetry или sensitive context.

## 8.4 Side-effect fields

Command MAY создавать subject field как side effect только если:

- field необходим declared loop;
- отображён в preview/UX, когда значим;
- не выводится скрыто из unrelated input;
- имеет provenance;
- cost/sensitivity учтены.

## 8.5 Processor promotion

Processor напрямую пишет только `DD/OR`. Невоспроизводимый или historical output становится subject data только через declared promotion Command и producer entry.

## 8.6 Sampling и throttling

Loop предпочитает минимальную достаточную granularity.

Например reading position использует:

- live cursor `DL`;
- meaningful checkpoint `CF`;
- latest resume `DD`;

а не canonical fact каждого pixel movement.

## 8.7 Consumer outage

Если required consumer unavailable:

- explicit user artifact creation MAY продолжаться, если artifact сам остаётся independently useful и exportable;
- automatic observation collection MUST pause либо иметь finite queue/window;
- high-sensitivity automatic collection MUST fail closed согласно review/policy;
- existing canonical data остаются читаемыми/exportable.

---

# 9. Consumers, decisions и actions

## 9.1 Loop Consumer declaration

```yaml
consumer_id: string
kind: user_surface | query | processor | workflow | module
consumer_ref: CapabilityOrRendererRef
input_catalog_refs: [CatalogTypeOrFieldRef]
purpose: string
output_ref: DecisionOrOutcomeRef
required: boolean
availability_requirement: AvailabilityRequirement
maximum_lag: duration | not_applicable
failure_behavior: FailureBehavior
```

`consumer_id` MUST соответствовать common `ConsumerDeclaration` referenced capability либо exact module integration contract.

## 9.2 Real consumer test

Consumer считается реальным, если:

- implementation/binding существует в declared release path;
- data действительно читаются declared Query/processor;
- output используется decision/action/use/outcome node;
- acceptance test проходит end-to-end;
- unavailable state явно обрабатывается.

Не считаются достаточными:

- запись в таблицу;
- индексирование;
- отображение raw count без решения;
- export «когда-нибудь»;
- generic AI context eligibility;
- потенциальный будущий module.

## 9.3 Decision declaration

```yaml
decision_id: string
actor: user | registered_policy
input_refs: [LoopNodeRef]
options: [DecisionOption]
default_behavior: no_default | SafeDefaultRef
confidence_required: boolean
freshness_requirement: FreshnessRequirement
explanation: ExplanationPolicy
```

Options конечны и включают `no_action`, когда действие не обязательно.

## 9.4 Action declaration

```yaml
action_id: string
kind: command | workflow | artifact_use | no_action
target_ref: CapabilityOrWorkflowRef | null
permission_scope: DataScopeRef | null
confirmation: ConfirmationPolicy
undo: UndoDeclaration | null
result_node: LoopNodeRef
```

Loop не ослабляет Command/Workflow permission, confirmation, idempotency или undo semantics.

Для `kind: no_action` target, permission и undo равны `null`; отсутствие effect не маскируется как reversible Command.

## 9.5 Recommendation vs action

Recommendation, plan или AI draft является `DD/CE proposal`. Action появляется только после:

- user/policy decision;
- schema/permission validation;
- required confirmation;
- Command/Workflow acceptance.

## 9.6 Human consumer

Фраза «пользователь посмотрит» недостаточна. Descriptor указывает конкретную Query/Widget/Form/navigation surface и decision/use, который она поддерживает.

---

# 10. Data Catalog field coverage

## 10.1 Catalog coverage fields

Каждый persistent field содержит:

```yaml
coverage_mode: loop | inherited_loop | technical_purpose
primary_loop_ref: LoopRef | null
loop_refs: [LoopRef]
technical_purpose_ref: TechnicalPurposeRef | null
consumers: [ConsumerRef]
```

Rules:

- `loop`: non-empty `loop_refs`, `primary_loop_ref` входит в список, technical ref `null`;
- `inherited_loop`: inheritance source explicit, resolved loop set non-empty, technical ref `null`;
- `technical_purpose`: loop refs empty, technical ref non-null;
- неизвестный/missing mode блокирует activation.

## 10.2 Loop Data Binding

```yaml
binding_id: string
catalog_ref: CatalogTypeOrFieldRef
field_paths: [FieldPath]
coverage: direct | inherited
role: subject_state | observation | decision_context | action_parameter | outcome_evidence | artifact_content
required: boolean
producer_refs: [ProducerRef]
consumer_refs: [LoopConsumerRef]
retention_dependency: RetentionDependencyDeclaration
```

## 10.3 Symmetric reference validation

Coverage действительна только если:

1. Catalog field ссылается на Loop Descriptor.
2. Loop Descriptor содержит обратный exact binding.
3. Owner/dependency разрешены.
4. Producer действительно пишет field.
5. Consumer действительно читает field либо declared projection.
6. Field role совместим с data class.
7. Sensitivity не ослаблена.

Односторонняя ссылка считается spec drift.

## 10.4 Direct coverage

Используется, если field имеет собственную domain semantics или отдельного consumer:

- note body/title;
- learning raw score;
- confidence/quality;
- annotation anchor;
- relation type/endpoints;
- reading checkpoint;
- decision status.

## 10.5 Inherited loop coverage

Допустимо только когда field:

- является structural subfield одного semantic value;
- не имеет самостоятельного lifecycle/consumer;
- наследует owner/class/sensitivity/retention;
- входит в exact schema expansion;
- не является secret, audit, operational или derived metadata отдельного назначения.

Inheritance source и expanded fields материализуются validator. Wildcard без schema expansion запрещён.

## 10.6 Multiple loops

Field MAY обслуживать несколько loops, если:

- один `primary_loop_ref` отвечает за collection justification/review;
- secondary loops реально потребляют уже существующие данные;
- secondary loop не расширяет collection silently;
- cost не учитывается как бесплатный;
- retirement primary loop либо назначает новый primary, либо останавливает exclusive collection.

## 10.7 Record/type coverage

Type-level loop default не освобождает fields от validation. Validator разворачивает type policy до каждого persistent field и фиксирует coverage matrix.

## 10.8 Data classes

- `CF`: producer, consumer и loop обязательны для domain observation.
- `CE`: каждое user/domain field loop-covered; revision mechanics technical fields используют Technical Purpose.
- `CR`: relation meaning покрыта domain loop; indexes — Technical Purpose или related loop-derived consumer.
- `CB`: original bytes покрыты artifact-use loop; hash/path/presence fields имеют technical coverage по своему class.
- `CA`: обычно Technical Purpose; отдельный domain evidence loop возможен только с реальным user consumer.
- `DD`: связывается с loop consumer/decision или Technical Purpose rebuild mechanism.
- `OT/OR/DL/SE`: обычно Technical Purpose, кроме device-local user preference, явно участвующего domain loop.

---

# 11. Technical Purpose Descriptor

## 11.1 Schema

```yaml
technical_purpose_id: TechnicalPurposeId
version: SemVer
contract_hash: Hash
owner: OwnerRef
status: experimental | active | deprecated | disabled
category: integrity | security | recovery | transport | idempotency | migration | observability | bounded_performance | platform_state

statement: string
protected_invariant: string
catalog_refs: [CatalogTypeOrFieldRef]
producer_refs: [CapabilityOrServiceRef]
consumer_refs: [CapabilityOrServiceRef]
failure_consequence: string

retention: RetentionPolicyRef
collection_cost: CollectionCostDeclaration
content_minimization: ContentMinimizationPolicy
reset_or_recovery: ResetOrRecoveryDeclaration
review: TechnicalPurposeReviewPolicy

acceptance_tests: [TestRef]
compatibility: CompatibilityDeclaration
deprecation: DeprecationDeclaration | null
```

## 11.2 Valid categories

### Integrity

Checksums, revision parentage, schema hashes, command receipts required to prove correctness.

### Security

Authentication state, pairing/revocation evidence, security-read audit; raw secrets remain `SE` and never justified as ordinary field.

### Recovery

Backup manifests, restore checkpoints, migration evidence, corruption findings.

### Transport/idempotency

Outbox, inbox, deduplication, sequence, provider effect reconciliation.

### Observability

Minimized health/lag/error state with real operator/user recovery consumer.

### Bounded performance

Rebuildable cache/index/lease with measured benefit, finite retention и safe reset.

### Platform state

Window geometry, local path/presence, platform notification state.

## 11.3 Invalid justifications

Недостаточны:

- «нужно backend»;
- «для debug» без consumer/retention;
- «может ускорить» без measurement;
- «для будущей совместимости» без concrete invariant;
- «для AI»;
- «стандартное поле»;
- «удобно хранить».

## 11.4 Domain-data prohibition

Technical Purpose MUST NOT использоваться для:

- пользовательского content;
- learning/health/finance observations;
- behavioral telemetry;
- model target/features с domain meaning;
- arbitrary full request/response bodies;
- поля, которое реально поддерживает domain decision.

Такое значение требует Loop Descriptor.

## 11.5 Content minimization

Technical data хранит IDs, hashes, sizes, safe codes и bounded metadata вместо raw content, если protected invariant достигается без content.

## 11.6 Retention

Retention выводится из failure/replay/recovery window и не равна автоматически сроку жизни всех canonical data.

Long-term retention требует отдельного evidence/integrity justification и review.

## 11.7 Reset/recovery

- `DD/OR/DL` purpose указывает safe reset/rebuild.
- `OT` purpose указывает terminal/cleanup proof.
- `CA` purpose указывает retention/privacy/purge interaction.
- `SE` purpose указывает rotation/revocation/re-auth.

---

# 12. Collection cost и proportionality

## 12.1 Cost declaration

```yaml
collection_cost:
  manual_burden: CostEstimate
  attention_burden: CostEstimate
  storage: CostEstimate
  compute: CostEstimate
  memory: CostEstimate
  network: CostEstimate
  monetary: CostEstimate
  energy: CostEstimate
  privacy_exposure: PrivacyCostEstimate
  frequency: FrequencyBound
  aggregate_budget: BudgetDeclaration
  measurement_method: MeasurementRef | explicit_zero
  exceed_behavior: warn | throttle | pause_collection | require_review
  minimization_strategy: string
```

## 12.2 Finite estimates

Каждая dimension имеет:

- unit;
- per-item/session/time-window basis;
- expected value/range;
- hard или policy maximum;
- uncertainty;
- measurement/spike reference.

`unknown` разрешён до spike только с conservative bound и blocking decision date.

## 12.3 Manual и attention burden

User input cost включает:

- число обязательных fields;
- expected completion time;
- interruption frequency;
- confirmation fatigue;
- review burden;
- correction cost.

Loop не требует точности, которую user не может устойчиво предоставлять.

## 12.4 Privacy cost

Privacy cost учитывает:

- sensitivity;
- granularity;
- frequency;
- linkability;
- retention;
- sync scope;
- backup/export exposure;
- cloud AI eligibility;
- inference risk derived outputs.

Encryption снижает risk, но не semantic privacy cost до zero.

## 12.5 Proportionality test

Loop проходит proportionality, если:

1. Outcome конкретен.
2. Минимальный dataset достаточен для consumer/decision.
3. Более дешёвая granularity рассмотрена.
4. Automatic collection ограничена.
5. Sensitivity оправдана outcome.
6. Retention не длиннее необходимого.
7. Cost exceed имеет behavior.
8. User может pause/inspect/export применимые data.

## 12.6 Cost telemetry recursion

Измерение cost/usage само требует Technical Purpose или domain loop. Нельзя бесконечно добавлять telemetry для оценки telemetry.

Предпочитаются:

- local aggregate `DD/OR`;
- sampling;
- bounded diagnostics;
- explicit user review;
- benchmark/spike вне production data.

## 12.7 Value threshold

Loop Descriptor объявляет minimum useful outcome. Если он систематически недостижим либо cost превышает budget, review MUST рассмотреть throttle, redesign, pause или retirement.

---

# 13. Sensitivity, provenance и data quality

## 13.1 Policy inheritance

Loop не понижает sensitivity. Effective policy вычисляется Data Classification/Capability Contract по records, fields, containers, operation и destination.

## 13.2 Sensitive loops

Для `P3` observation feedback loop обязательны:

- explicit scope/notice;
- selected devices/sync policy;
- local-only AI default;
- protected backup warning/policy;
- enhanced review;
- no hidden automatic expansion;
- field-level export semantics.

`P4` не является ordinary loop data; credential handling использует Technical Purpose + Secret Service.

## 13.3 Provenance

Loop data binding сохраняет:

- producer/origin;
- schema/semantic version;
- source refs;
- transformation/model version;
- decision/action causation refs;
- correction/revision lineage;
- coverage loop version.

## 13.4 Raw, confidence и uncertainty

Raw result, self-confidence, grading confidence, quality, coverage и model uncertainty имеют отдельные Catalog fields/bindings.

Loop graph MAY consume их совместно, но не сливает в одно source-of-truth value.

## 13.5 Missing data

Producer/consumer contracts определяют missing, unknown, not_applicable и stale. Imputation является versioned `DD`, а не silent canonical value.

## 13.6 Declassification

Loop не объявляет output менее sensitive только из-за aggregation/redaction. Approved declassification остаётся отдельным workflow/evidence.

---

# 14. Review, pause и retirement

## 14.1 Loop Review Policy

```yaml
review:
  owner: OwnerRef
  review_interval: duration
  initial_review_due: DurationFromActivation
  evidence_refs: [CapabilityOrTestRef]
  triggers: [ReviewTrigger]
  decisions: [keep | revise | pause | retire | split | merge]
  overdue_behavior: warn | pause_automatic_collection | disable_exclusive_producers
  high_sensitivity_behavior: pause_automatic_collection | disable_exclusive_producers
  receipt_policy: AuditPolicyRef
```

Review interval конечен. «Периодически» без bound недопустимо.

## 14.2 Review triggers

Минимальные triggers:

- required consumer removed/disabled;
- outcome semantics changed;
- collection cost exceeded;
- sensitivity/outbound policy changed;
- model/processor major replaced;
- platform availability changed;
- field coverage drift;
- user request;
- module/loop deprecation;
- repeated stale/unavailable state;
- no declared evidence path remains.

## 14.3 Review records

- Review decision/configuration change — новая `CE` revision.
- Completion/scope/evidence receipt — minimized `CA`.
- Самостоятельная user/domain usefulness observation — `CF` только при отдельном consumer; не обязательная telemetry.
- Current validation/review-due projection — `DD`.

## 14.4 Pause

Pause:

- запрещает automatic producers exclusive loop;
- explicit producer behavior следует declaration;
- не удаляет existing canonical data;
- не ломает export/read;
- сохраняет descriptor/configuration/review evidence;
- показывает affected fields/capabilities;
- требует нового validation перед resume.

## 14.5 Retirement

Retirement plan содержит:

- replacement loop refs либо reason no replacement;
- field coverage reassignment;
- producer disable/migration;
- consumer migration;
- configuration deprecation;
- retention/export behavior existing data;
- persisted layout/form references;
- tests.

Retirement не запускает purge.

## 14.6 Split/merge

Split/merge создаёт новые descriptor IDs/versions и explicit mapping:

- old data bindings;
- new primary loop ownership;
- consumers/actions;
- configuration migration;
- historical provenance.

History не переписывается новым loop ID.

---

# 15. Runtime configuration и state

## 15.1 Loop Configuration `CE`

```yaml
loop_configuration_id: GlobalEntityId
loop_ref: LoopRef
scope: LoopScope
status: active | paused
parameters: SchemaBoundedValue
cadence: CadenceDeclaration
cost_budget_overrides: StricterBudgetOverrides
review_overrides: StricterReviewOverrides
created_origin: Origin
revision: RevisionRef
```

Overrides могут только сужать collection, cost, outbound и review intervals без отдельного declassification/authority workflow.

## 15.2 Default configuration

Module MAY поставить packaged default configuration template. Active runtime configuration создаётся explicit initialization/migration Command как `CE`, имеет provenance и доступна export.

Package default не является скрытым mutable runtime truth.

Module MAY разрешить runtime-created Loop Definitions через отдельную typed Command и manifest-declared extension point. Такая definition:

- является `CE` со stable ID и immutable revisions;
- выбирает coordinating owner module;
- использует exact registered refs;
- не может служить единственным оправданием baseline production fields/capabilities до validation/activation;
- MAY стать primary coverage только через explicit Catalog coverage/configuration revision;
- сохраняется в export/backup;
- при disable owner module становится inactive, но definition/history не удаляются.

## 15.3 Validation result `DD`

```yaml
loop_ref: LoopRef
configuration_revision: RevisionRef
registry_generation: RegistryGeneration
validator_version: string
status: valid | degraded | invalid | review_due
coverage_summary: CoverageSummary
cost_summary: CostSummary
availability_summary: AvailabilitySummary
errors: [LoopValidationError]
built_at: timestamp
```

Validation result удаляем/rebuildable и не заменяет Descriptor/Configuration.

## 15.4 Effective status

```text
descriptor status
∩ module activation
∩ dependencies
∩ configuration status
∩ consumer availability
∩ review policy
∩ data/security policy
```

Possible effective states:

```text
active
degraded
paused
review_due
invalid
deprecated
retired
```

## 15.5 Configuration changes

Apply выполняется Command с:

- expected revision;
- preview affected producers/fields/consumers;
- policy/permission validation;
- cost delta;
- review date;
- audit receipt;
- no hidden data deletion.

---

# 16. Loop Registry и validation

## 16.1 Registry responsibilities

Loop Registry:

- разрешает descriptors/configurations;
- строит graph и reverse field coverage;
- связывает producers/consumers/actions;
- проверяет outcomes/cost/review;
- вычисляет effective status;
- публикует immutable generation projection;
- предоставляет filtered diagnostics;
- не исполняет loop stages.

## 16.2 Activation pipeline

1. Resolve exact descriptor/hash.
2. Validate owner/module membership.
3. Resolve configuration schema/current revision.
4. Resolve Data Catalog bindings symmetrically.
5. Resolve producer writes.
6. Resolve consumer reads/ConsumerDeclarations.
7. Resolve decision/action refs.
8. Prove kind-specific closure.
9. Validate outcome evidence.
10. Validate cost/review policies.
11. Validate availability/degradation.
12. Validate permissions/sensitivity without widening.
13. Build coverage matrix.
14. Publish with module Registry generation atomically.

## 16.3 Validation errors

Stable codes include:

```text
LOOP_UNRESOLVED_REF
LOOP_OWNER_MISMATCH
LOOP_ORPHAN_FIELD
LOOP_NO_PRODUCER
LOOP_NO_REQUIRED_CONSUMER
LOOP_NO_DECISION_OR_USE
LOOP_NO_OUTCOME
LOOP_NO_EVIDENCE_PATH
LOOP_UNBOUNDED_COLLECTION
LOOP_COST_UNDEFINED
LOOP_REVIEW_UNDEFINED
LOOP_COVERAGE_MISMATCH
LOOP_PERMISSION_WIDENING
LOOP_SENSITIVITY_CONFLICT
LOOP_AVAILABILITY_BROKEN
TECHNICAL_PURPOSE_INCOMPLETE
TECHNICAL_PURPOSE_DOMAIN_MISUSE
```

## 16.4 Failure scope

- Invalid required module loop blocks module activation.
- Invalid optional integration loop blocks only integration.
- Invalid runtime configuration pauses exclusive automatic collection and reports recovery.
- Existing canonical data/read/export remain available through safe paths.
- Validator failure не переписывает configuration.

## 16.5 Coverage matrix

Generated matrix содержит для каждого field:

- class/owner;
- coverage mode;
- primary/secondary loop refs или technical-purpose ref;
- producers;
- consumers;
- collection mode/cost;
- review state;
- effective availability;
- conformance tests.

Matrix является `DD` и сравнивается с source descriptors при CI/runtime validation.

## 16.6 Spec drift

CI проверяет:

- Manifest loops/technical purposes ↔ descriptor bundle;
- Catalog fields ↔ bindings;
- Capability loop refs ↔ descriptor membership;
- consumers ↔ actual registered consumers;
- processor inputs/outputs ↔ graph;
- module specs ↔ baseline loops;
- tests ↔ outcomes.

---

# 17. Availability, offline и degradation

## 17.1 Availability declaration

```yaml
availability:
  producer_platforms: [desktop | mobile | cli]
  consumer_platforms: [desktop | mobile | cli]
  offline: full | bounded_queue | unavailable
  maximum_consumer_lag: duration | not_applicable
  required_modules: [ModuleVersionRef]
  degraded_paths: [DegradedLoopPath]
```

## 17.2 Local-first requirement

Core v1/v2 domain loop не может иметь cloud/AI единственным required consumer, если producer собирает данные offline или core feature заявлена local.

Допустимы:

- local user consumer;
- local Query/processor;
- bounded delayed consumer на другом paired device;
- optional cloud/AI enhancement.

## 17.3 Bounded delayed consumption

Если producer и consumer доступны на разных devices/platforms:

- canonical data остаются independently useful/exportable;
- maximum lag declared;
- queue/backlog bounded;
- sync absence visible;
- collection pause policy defined;
- no silent indefinite accumulation.

## 17.4 Degraded path

Degraded path сохраняет outcome subset и явно перечисляет unavailable decisions/actions.

Он не подменяет missing consumer dummy dashboard или stale result.

## 17.5 Module disable

Disable consumer module пересчитывает affected loops. Required dependency blocks/pauses path; optional consumer удаляется только если другой required closure остаётся.

---

# 18. AI integration

## 18.1 AI as consumer

AI может быть consumer только через registered Query/Tool Gateway и effective outbound policy.

Descriptor указывает:

- exact AI-enabled capability;
- non-AI fallback либо declared AI-specific optional loop;
- source preview/redaction;
- provider/local availability;
- cost budget;
- provenance;
- decision/action boundary.

Generic «model may use this later» не является consumer.

## 18.2 AI as producer

Provider output:

- временно `OR`, если не сохранён;
- `DD`, только если реально rebuildable;
- `CE proposal`/`CF observation` только через explicit promotion Command;
- не получает canonical authority автоматически.

## 18.3 AI-generated loop proposal

AI MAY предложить `LoopConfiguration` или draft descriptor change как `CE proposal`.

Proposal MUST NOT:

- создать capability/schema/field;
- добавить executable stage;
- расширить DataScope/permissions;
- понизить sensitivity;
- разрешить cloud outbound;
- ослабить review/cost budget;
- активировать automatic collection;
- изменить approved descriptor in place.

Runtime-extensible Loop Definition MAY быть создана/пересмотрена через approved typed extension point без module release. Изменение built-in baseline descriptor, manifest membership, field schema или capability set требует обычного module release.

## 18.4 Apply

Apply проходит:

- schema/hash/version validation;
- module ownership;
- graph closure;
- Catalog/capability refs;
- permissions/sensitivity/outbound policy;
- collection cost delta;
- review policy;
- preview/confirmation;
- acceptance tests для descriptor change;
- new configuration/Runtime LoopDefinition revision либо normal module release для built-in contract change.

## 18.5 Prompt injection

Retrieved content является data и не может изменить loop, Technical Purpose, cost budget, review state или Registry generation.

## 18.6 AI autonomous workflows

Restricted Workflow MAY быть action node только с pre-approved exact scope, stop conditions, expiry и outcome review. Loop не позволяет model добавлять новые steps/tools.

---

# 19. Versioning и compatibility

## 19.1 Patch

- editorial clarification;
- test/evidence ref fix;
- implementation bug fix к существующему semantics;
- stricter validation уже запрещённого state.

## 19.2 Minor

- optional consumer/path;
- compatible platform renderer;
- additional outcome evidence без изменения meaning;
- stricter default cost/review policy;
- optional data binding, не расширяющий collection без explicit configuration.

## 19.3 Major

- purpose/outcome change;
- new mandatory subject field/producer;
- collection frequency/granularity expansion;
- consumer/decision/action removal;
- loop kind change;
- sensitivity/outbound semantics change;
- incompatible graph/role meaning;
- changed primary loop ownership;
- weakened review/cost behavior.

## 19.4 Configuration revision

User scope, cadence, enablement и stricter budget change создают `CE` revision, но не descriptor version, если остаются внутри schema/contract.

## 19.5 Compatibility

New descriptor version объявляет:

- compatible configuration versions;
- migration/default handling;
- field coverage changes;
- running actions/workflows impact;
- persisted UI refs;
- old data interpretation;
- rollback/recovery.

## 19.6 Historical provenance

Historical data сохраняют original `LoopRef`/descriptor version. Новый loop не переписывает старое collection justification задним числом.

---

# 20. Testing и conformance

## 20.1 Descriptor validation

- ID/version/hash;
- owner/module membership;
- kind schema;
- graph node/edge refs;
- exact data bindings;
- producer/consumer/action refs;
- outcome/evidence;
- finite cost;
- review policy;
- availability;
- compatibility/deprecation.

## 20.2 Closure tests

- every subject field producer-reachable;
- every subject field required-consumer-reachable;
- consumer leads to decision/use/outcome;
- action leads to outcome/review;
- optional path removal preserves required closure;
- no orphan/sink;
- failure paths typed.

## 20.3 Coverage tests

- Catalog ↔ Loop symmetric refs;
- one primary coverage mode;
- inherited expansion exact;
- multiple-loop primary ownership;
- service field technical purpose;
- domain field cannot use technical purpose;
- loop retirement reassigns/stops collection.

## 20.4 Producer tests

- writes match Catalog;
- pause behavior;
- consumer outage;
- bounded batch/frequency;
- idempotency/provenance;
- automatic collection no hidden expansion;
- processor promotion boundary.

## 20.5 Consumer/action tests

- actual reads;
- unavailable/stale handling;
- decision options including no_action;
- permission/confirmation/undo preserved;
- AI/tool subset;
- action result linked;
- UI display not sole fake consumer.

## 20.6 Outcome tests

- end-to-end artifact use;
- raw/derived/confidence separation;
- missing/unknown behavior;
- proxy limitations;
- no false causality;
- evidence path without mandatory self-telemetry.

## 20.7 Cost/privacy tests

- finite budget;
- sampling/throttling;
- budget exceed behavior;
- P3 enhanced policy;
- P4 blocked;
- no raw content in technical diagnostics;
- retention proportionality.

## 20.8 Lifecycle tests

- initialization configuration;
- active/degraded/paused/review_due;
- review decision;
- resume revalidation;
- retirement without deletion;
- module/consumer disable;
- version migration;
- historical LoopRef retained.

## 20.9 AI tests

- proposal cannot activate;
- no new capability/schema/permission;
- outbound policy enforced;
- cost/stop conditions;
- prompt injection cannot change Registry;
- explicit promotion and provenance.

---

# 21. Provisional baseline loops v1

Точные artifacts принимаются в module specifications. Настоящий раздел фиксирует обязательные value paths, а не окончательные IDs/fields.

## 21.1 Knowledge note edit/retrieval

Kind: `artifact_use`.

```text
explicit create/import
→ Note CE revisions
→ get/search/navigation consumer
→ read/edit/link/export use
→ revise/archive
```

Hidden read telemetry не требуется.

## 21.2 Document access/reading

Kind: `artifact_use`.

```text
import/adopt original CB + Document CE
→ reader/search/navigation
→ read/annotate/bookmark/link/export
→ revise metadata/archive
```

Original bytes и annotations имеют собственные bindings; parser/OCR remain `DD`.

## 21.3 Reading resume feedback

Kind: `observation_feedback`.

```text
live cursor DL
→ meaningful checkpoint CF
→ latest resume DD
→ user resume decision/action
→ next checkpoint or explicit reset
```

Не сохраняет каждый scroll movement canonical.

## 21.4 Annotation capture/use

Kind: `artifact_use`.

```text
create annotation/anchor
→ retrieve in reader/search/note relation
→ use/revise/re-resolve
→ archive/export
```

Resolved current position `DD`; canonical anchor evidence не переписывается parser update.

## 21.5 Backup/export mechanisms

Не являются domain loops. Их service fields используют Technical Purposes recovery/integrity. User-facing export capability MAY быть action/outcome path внутри artifact-use loop.

---

# 22. Reference Loop Descriptor

Пример сокращён; `<hash>` заменяется реальными values. Все referenced product contracts окончательно определяются `KNOWLEDGE-MODULE.md`.

```yaml
loop_id: knowledge.note.edit_retrieval
version: 1.0.0
contract_hash: "sha256:<hash>"
owner_module: knowledge
status: active
origin: built_in
definition_revision: null
kind: artifact_use

summary: locale://loops/knowledge-note-edit-retrieval/summary
purpose:
  statement: preserve user-authored knowledge as retrievable, revisable and exportable notes
  user_or_domain_need: externalize and reuse information without losing history or ownership
  decision_or_use_enabled: read, revise, link, organize, archive or export a note
  excluded_uses: [behavioral profiling, hidden engagement scoring]
  success_without_telemetry: test://knowledge/note-create-retrieve-revise-export

beneficiaries:
  - beneficiary_id: user.knowledge_work
    kind: user_goal
    benefit: durable retrieval and reuse of authored knowledge

subject_scope:
  - subject_id: knowledge.notes
    catalog_types: [knowledge.note.entity, knowledge.note.revision]
    container_scope: authorized_spaces
    time_grain: revision
    missing_semantics: not_found_or_not_authorized
    sensitivity_ceiling: P3

outcomes:
  - outcome_id: note_access_and_reuse
    statement: a created note remains retrievable, readable, revisable and exportable
    kind: artifact_access_use
    beneficiary_ref: user.knowledge_work
    decision_supported: note_use_decision
    evidence_mode: acceptance_test
    evidence_refs: [test://knowledge/note-create-retrieve-revise-export]
    success_semantics: stable ID and content survive restart and round-trip export/import
    failure_semantics: note cannot be retrieved, interpreted, revised or exported
    uncertainty_semantics: not_applicable_for_contract_test
    minimum_usefulness: one explicit user-created note can complete the full path

stages:
  - {stage_id: capture, kind: producer}
  - {stage_id: canonical_note, kind: canonical_data}
  - {stage_id: retrieve, kind: consumer}
  - {stage_id: decide_use, kind: decision}
  - {stage_id: use_or_revise, kind: action}
  - {stage_id: accessible_result, kind: outcome}
  - {stage_id: lifecycle_review, kind: review}

edges:
  - {edge_id: e1, from: capture, to: canonical_note, kind: produces, condition: always, maximum_lag: not_applicable, failure_behavior: typed_command_failure}
  - {edge_id: e2, from: canonical_note, to: retrieve, kind: reads, condition: always, maximum_lag: not_applicable, failure_behavior: unavailable_with_recovery}
  - {edge_id: e3, from: retrieve, to: decide_use, kind: informs, condition: always, maximum_lag: not_applicable, failure_behavior: no_decision}
  - {edge_id: e4, from: decide_use, to: use_or_revise, kind: selects, condition: always, maximum_lag: not_applicable, failure_behavior: no_action}
  - {edge_id: e5, from: use_or_revise, to: accessible_result, kind: evaluates, condition: always, maximum_lag: not_applicable, failure_behavior: typed_outcome_failure}
  - {edge_id: e6, from: accessible_result, to: lifecycle_review, kind: updates, condition: always, maximum_lag: 365d, failure_behavior: review_due}

data_bindings:
  - binding_id: note_content
    catalog_ref: knowledge.note.revision
    field_paths: [title, body, properties]
    coverage: direct
    role: artifact_content
    required: true
    producer_refs: [note_create, note_revise]
    consumer_refs: [note_get, note_editor]
    retention_dependency: user_or_policy

producers:
  - producer_id: note_create
    kind: command
    source_ref: knowledge.note.create@1
    output_catalog_refs: [knowledge.note.entity, knowledge.note.revision]
    collection_mode: explicit_user
    trigger: user_submit
    frequency_bound: user_bounded
    batch_bound: 1
    consent_or_notice: explicit_form_content
    paused_behavior: reject
    failure_behavior: typed_command_error
  - producer_id: note_revise
    kind: command
    source_ref: knowledge.note.revise@1
    output_catalog_refs: [knowledge.note.revision]
    collection_mode: explicit_user
    trigger: user_submit
    frequency_bound: user_bounded
    batch_bound: 1
    consent_or_notice: explicit_editor_content
    paused_behavior: reject
    failure_behavior: typed_command_error

consumers:
  - consumer_id: note_get
    kind: query
    consumer_ref: knowledge.note.get@1
    input_catalog_refs: [knowledge.note.entity, knowledge.note.revision]
    purpose: retrieve current note and provenance for reading or editing
    output_ref: note_use_decision
    required: true
    availability_requirement: desktop_offline_v1
    maximum_lag: not_applicable
    failure_behavior: typed_unavailable_or_not_found
  - consumer_id: note_editor
    kind: user_surface
    consumer_ref: knowledge.note.editor_widget@1
    input_catalog_refs: [knowledge.note.entity, knowledge.note.revision]
    purpose: let the user read and explicitly revise the note
    output_ref: note_use_decision
    required: true
    availability_requirement: desktop_offline_v1
    maximum_lag: not_applicable
    failure_behavior: fallback_with_export_path

decisions:
  - decision_id: note_use_decision
    actor: user
    input_refs: [retrieve]
    options: [read_only, revise, no_action]
    default_behavior: no_default
    confidence_required: false
    freshness_requirement: canonical_current_head
    explanation: show_revision_and_conflict_state

actions:
  - action_id: read_note
    kind: artifact_use
    target_ref: knowledge.note.get@1
    permission_scope: knowledge.note.read_target@1
    confirmation: none
    undo: null
    result_node: accessible_result
  - action_id: revise_note
    kind: command
    target_ref: knowledge.note.revise@1
    permission_scope: knowledge.note.revise_target@1
    confirmation: standard
    undo: reversible
    result_node: accessible_result
  - action_id: no_change
    kind: no_action
    target_ref: null
    permission_scope: null
    confirmation: none
    undo: null
    result_node: accessible_result

feedback:
  mode: artifact_lifecycle
  source_nodes: [accessible_result]
  target_nodes: [lifecycle_review, capture]
  terminal_allowed: true
  maximum_gap: 365d

availability:
  producer_platforms: [desktop, mobile, cli]
  consumer_platforms: [desktop, mobile, cli]
  offline: full
  maximum_consumer_lag: not_applicable
  required_modules: [knowledge@^1.0]
  degraded_paths: [read_only_maintenance_export_when_module_disabled]

collection_cost:
  manual_burden: {unit: required_overhead_seconds, expected: 0, maximum: one_standard_submit}
  attention_burden: {unit: interruptions, expected: 0, maximum: 0}
  storage: {unit: bytes_per_note, expected: measured, maximum: capability_request_limit}
  compute: {unit: cpu_time, expected: bounded_interactive, maximum: capability_deadline}
  memory: {unit: bytes, expected: bounded_interactive, maximum: capability_memory_limit}
  network: {unit: bytes, expected: 0_offline, maximum: sync_policy_bound}
  monetary: {unit: currency, expected: 0, maximum: 0}
  energy: {unit: qualitative, expected: low, maximum: bounded_interactive}
  privacy_exposure: {sensitivity: P2_default, outbound: none_by_loop}
  frequency: user_initiated
  aggregate_budget: user_storage_and_capability_limits
  measurement_method: test://knowledge/note-performance-budget
  exceed_behavior: warn
  minimization_strategy: no hidden usage telemetry; index is rebuildable DD

review:
  owner: knowledge
  review_interval: 365d
  initial_review_due: 365d
  evidence_refs: [test://knowledge/note-create-retrieve-revise-export]
  triggers: [consumer_removed, export_failure, field_coverage_drift, user_request, module_deprecation]
  decisions: [keep, revise, pause, retire, split]
  overdue_behavior: warn
  high_sensitivity_behavior: pause_automatic_collection
  receipt_policy: audit://loop-review-minimized

configuration_schema: schema://knowledge/note-loop-configuration/1.0.0
acceptance_tests:
  - knowledge_note_loop_closure
  - knowledge_note_loop_offline
  - knowledge_note_loop_round_trip
  - knowledge_note_loop_pause_preserves_data
compatibility:
  minimum_core_version: 1.0.0
  supported_majors: [1]
deprecation: null
```

---

# 23. Reference Technical Purpose

```yaml
technical_purpose_id: kernel.technical.command_idempotency
version: 1.0.0
contract_hash: "sha256:<hash>"
owner: kernel.command_bus
status: active
category: idempotency

statement: prevent repeated delivery of one accepted command intent from duplicating observable effects
protected_invariant: same idempotency scope and fingerprint produces at most one accepted effect
catalog_refs: [kernel.command.idempotency_record]
producer_refs: [kernel.command_bus]
consumer_refs: [kernel.command_bus, kernel.command.status]
failure_consequence: duplicate canonical or irreversible external effect, or unsafe inability to reconcile status

retention: policy://idempotency/replay-window-and-irreversible-receipt
collection_cost:
  manual_burden: {unit: user_seconds, expected: 0, maximum: 0}
  attention_burden: {unit: interruptions, expected: 0, maximum: 0}
  storage: {unit: bytes_per_command, expected: bounded_record, maximum: policy_bound}
  compute: {unit: lookup_per_command, expected: 1, maximum: bounded}
  memory: {unit: bytes, expected: bounded_cache, maximum: runtime_limit}
  network: {unit: bytes, expected: 0, maximum: 0}
  monetary: {unit: currency, expected: 0, maximum: 0}
  energy: {unit: qualitative, expected: low, maximum: bounded}
  privacy_exposure: {sensitivity: target_derived_minimized, content: payload_hash_not_body}
  frequency: one_record_per_accepted_command
  aggregate_budget: retention_window_bound
  measurement_method: test://kernel/idempotency-storage-budget
  exceed_behavior: require_review
  minimization_strategy: store fingerprint/status/result reference, not raw sensitive payload
content_minimization: no_secrets_no_raw_payload_unless_separately_justified
reset_or_recovery: restore_active_records; retain_minimal_irreversible_receipts; never blind-reset_pending_unknown_effect
review:
  interval: 180d
  triggers: [protocol_retry_window_change, external_effect_policy_change, storage_budget_exceeded]
  overdue_behavior: require_review

acceptance_tests:
  - duplicate_same_fingerprint_returns_original_result
  - same_key_different_fingerprint_conflicts
  - restore_preserves_active_deduplication
  - unknown_effect_requires_status_reconciliation
compatibility:
  minimum_core_version: 1.0.0
  supported_majors: [1]
deprecation: null
```

---

# 24. Constitutional Conformance Matrix

| Инвариант | Loop/technical-purpose mechanism |
|---|---|
| I1 | Exact capability/workflow refs; loop cannot mutate or grant storage authority |
| I2 | `CF` observations have producer, immutable binding and correction-compatible feedback |
| I3 | `CE` configurations/artifacts use revisions; pause/retirement preserves history |
| I4 | `DD` interpretation nodes require provenance/version/rebuild and real consumer |
| I5 | Immutable descriptor identity, SemVer, hash and compatibility/migration |
| I6 | Module-owned finite descriptors; AI/external content cannot create executable capability |
| I7 | Symmetric per-field LoopRef or TechnicalPurposeRef coverage and Registry validation |
| I8 | Concrete beneficiary, consumer, decision/use, outcome, evidence and end-to-end tests |
| I9 | Separate raw/confidence/quality/uncertainty bindings and missing semantics |
| I10 | Actions remain idempotent Commands/Workflows; Kernel technical purposes cover receipts/outbox |
| I11 | Pause/retirement separate from purge; existing data remain readable/exportable |
| I12 | Availability/offline closure, bounded delayed consumption and local fallback |
| I13 | AI consumer/producer only through Tool Gateway, outbound policy and proposals |
| I14 | Producer/source/transformation/decision/action provenance preserved |
| I15 | Loop failure scopes, consumer outage, bounded cost, review and degraded behavior |
| I16 | Artifact-use/export paths and retirement preserve independent data ownership |

---

# 25. Зависимые решения и открытые параметры

| Решение | Документ |
|---|---|
| Exact Knowledge loops, fields, consumers и configurations | `KNOWLEDGE-MODULE.md` |
| Exact Documents reading/annotation loops | `DOCUMENT-MODULE.md` |
| Learning/Analytics loop types и models | v2 module specifications |
| Loop/TechnicalPurpose serialization dialect | ADR-001 или serialization specification |
| Runtime Registry tables/projections | v1 DDL |
| Review UI и diagnostics surface | Platform Shell/module specifications |
| Exact retention/review windows | Module specifications + ADR-008 |
| Cost measurement spikes/SLO | Module/module-platform spikes |

Open parameter не разрешает:

- uncovered field;
- string-only technical justification;
- hypothetical consumer;
- unbounded automatic collection;
- missing review policy;
- hidden telemetry;
- AI authority expansion;
- data deletion при pause/retirement;
- metric без decision/outcome;
- Technical Purpose для domain data.

---

# 26. Acceptance criteria

`LOOP-SPEC.md` v0.1 готов к утверждению, если:

1. Loop и Workflow однозначно разделены;
2. Loop Descriptor имеет stable identity/version/hash/owner;
3. kinds `artifact_use`, `observation_feedback`, `decision_action` имеют отдельные closure rules;
4. producer → data → consumer → decision/action → outcome path машиночитаем;
5. outcome не подменён proxy/metric и имеет evidence path;
6. hidden usage telemetry не требуется для artifact-use proof;
7. каждый subject field имеет symmetric exact LoopRef coverage;
8. inherited coverage ограничено structural fields;
9. multiple loops имеют primary collection owner;
10. service fields используют structured TechnicalPurposeRef;
11. Technical Purpose содержит invariant, consumer, failure, cost, retention и recovery;
12. domain data нельзя оправдать Technical Purpose;
13. collection costs finite и проходят proportionality test;
14. sensitivity/provenance/raw-confidence semantics сохранены;
15. review/pause/retirement не удаляют history;
16. runtime configuration является `CE`, validation — `DD`;
17. Loop Registry проверяет closure/coverage/availability атомарно с module generation;
18. offline/degraded path не зависит скрыто от cloud/AI;
19. AI proposal не создаёт authority или automatic collection;
20. tests покрывают closure, coverage, cost, lifecycle, failure и AI;
21. provisional v1 loops согласованы с Architecture/Data Classification;
22. Conformance Matrix покрывает I1-I16;
23. владелец проекта явно утверждает документ.

После утверждения следующий нормативный документ — `KNOWLEDGE-MODULE.md`.
