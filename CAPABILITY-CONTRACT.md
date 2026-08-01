# Nabla Capability Contract v0.1

**Статус:** утвержден  
**Дата:** 2026-07-11  
**Нормативная основа:** `CONSTITUTION.md` v0.1, `ARCHITECTURE.md` v0.1, `DATA-CLASSIFICATION.md` v0.1  
**Следующий зависимый документ:** `MODULE-MANIFEST.md`

---

# 0. Назначение

Capability является минимальной публичной и проверяемой возможностью Nabla.

Этот документ определяет единый contract для:

- Command;
- Query;
- Event;
- Processor;
- Widget;
- Form;
- Exporter.

Контракт должен быть достаточно строгим, чтобы:

- UI, CLI, Mobile, sync и AI использовали одинаковые semantics;
- ни один consumer не обходил Command/Query boundary;
- permissions проверялись Core, а не соглашением между components;
- retry не дублировал изменения;
- schema и meaning эволюционировали версионированно;
- errors, limits, provenance и sensitivity были машиночитаемыми;
- capability могла быть автоматически проверена до module activation;
- generated clients и AI tools не получали большей власти, чем сам contract.

Capability не является произвольной функцией. Она имеет одного owner, ограниченный scope, конечный schema, declared effects и acceptance suite.

---

# 1. Область действия и не-цели

## 1.1 Область действия

Contract обязателен для всех capabilities, доступных:

- Presentation clients;
- CLI;
- другим modules;
- processors/workflows;
- sync ingestion;
- AI Tool Gateway;
- administrative/recovery surfaces.

Internal pure function внутри одного module не обязана быть capability, пока она:

- не пересекает module/process/trust boundary;
- не меняет persistent state самостоятельно;
- не становится внешним contract;
- тестируется как implementation detail.

## 1.2 Не-цели

Документ не определяет:

- wire encoding IPC;
- язык реализации;
- окончательный JSON Schema dialect;
- DDL registry tables;
- UI styling;
- Safe Query DSL operators;
- конкретный список всех product capabilities.

## 1.3 Запрещённые обходы

Нельзя заменять typed capabilities следующими механизмами:

- `execute_arbitrary_operation(payload)`;
- raw SQL query/command;
- arbitrary filesystem path mutation;
- shell/code execution;
- generic reflection over all services;
- unbounded GraphQL-like mutation surface;
- AI tool с wildcard scopes;
- hidden side effect внутри Query/Widget/Processor.

---

# 2. Основные понятия

## 2.1 Capability Descriptor

Versioned manifest entry, описывающий identity, schemas, authority, data access, limits, errors и tests capability.

## 2.2 Invocation

Один вызов capability через Core boundary с request envelope и Core-injected execution context.

## 2.3 Consumer

UI, module, workflow, processor, CLI, sync adapter или AI Tool Gateway, использующий capability через public contract.

## 2.4 Effect

Наблюдаемое изменение canonical state, operational workflow state либо внешней системы.

## 2.5 Contract hash

Cryptographic hash canonical representation descriptor и всех referenced schemas. Одинаковые `capability_id + version` MUST иметь одинаковый hash.

## 2.6 Public semantics

Не только shape payload, но и:

- meaning полей;
- preconditions;
- ordering;
- consistency;
- error codes;
- idempotency;
- effects;
- authorization;
- limits;
- undo/confirmation behavior.

Изменение public semantics требует совместимой version policy, даже если JSON shape не изменился.

---

# 3. Identity и naming

## 3.1 Capability ID

Capability ID имеет namespaced lowercase form:

```text
<owner-namespace>.<resource-or-domain>.<action-or-view>
```

Примеры:

```text
knowledge.note.create
knowledge.note.revise
knowledge.note.get
documents.annotation.list
kernel.job.cancel
```

## 3.2 Naming rules

ID:

- содержит 3–6 dot-separated segments;
- каждый segment соответствует `[a-z][a-z0-9_-]*`;
- не содержит version;
- не зависит от UI wording;
- не меняется при internal refactor;
- уникален во всём Registry;
- начинается с owner namespace;
- использует action verb для Command и view/result noun либо read verb для Query.

Namespace `kernel` зарезервирован Kernel.

## 3.3 Rename

Rename ID создаёт новую capability. Старый ID проходит deprecation/migration и не становится alias без отдельного compatibility contract.

## 3.4 Version identity

Полная identity:

```text
(capability_id, semantic_version, contract_hash)
```

`contract_hash` обнаруживает spec drift, но не заменяет semantic version.

---

# 4. Common Capability Descriptor

Каждая capability объявляет language-neutral descriptor:

```yaml
capability_id: CapabilityId
version: SemVer
kind: command | query | event | processor | widget | form | exporter
owner_module: ModuleId
status: experimental | active | deprecated | disabled
summary: LocalizedTextRef
description: LocalizedTextRef

input_schema: SchemaRef | null
output_schema: SchemaRef | null
error_contract: ErrorContractRef | null

data_access:
  reads: [DataAccessRule]
  writes: [DataEffectRule]
  derived_outputs: [DataOutputRule]
  secret_handles: [SecretAccessRule]
  external_effects: [ExternalEffectRef]

permissions: PermissionDeclaration
ai_exposure_max: none | read_only | proposal | confirmed_command | restricted_workflow
availability: AvailabilityDeclaration
limits: ResourceLimits
observability: ObservabilityDeclaration

loop_refs: [LoopRef]
technical_purpose_ref: TechnicalPurposeRef | null
consumers: [ConsumerDeclaration]
acceptance_tests: [TestRef]

compatibility: CompatibilityDeclaration
deprecation: DeprecationDeclaration | null
contract_hash: Hash
```

Kind-specific sections расширяют descriptor, но не дублируют и не переопределяют common fields. `data_access`, `permissions`, `availability`, `limits`, `consumers` и `ai_exposure_max` имеют ровно один нормативный экземпляр в common descriptor.

## 4.1 Required fields

Для production capability обязательны:

- stable ID/version/hash;
- owner;
- kind/status;
- input/output schemas, где применимо;
- typed error contract для kind, который возвращает failure/result; Event MAY использовать `null`;
- data access/effects;
- permissions;
- finite limits;
- availability/offline semantics;
- loop либо technical purpose;
- declared consumers;
- acceptance tests;
- compatibility policy.

## 4.2 Loop и technical purpose

User/domain capability MUST ссылаться минимум на один exact active `LoopRef`.

Kernel/operational capability MAY вместо loop ссылаться на exact active
`TechnicalPurposeRef`. Строковое объяснение не является контрактом. Ссылаемый
`TechnicalPurposeDescriptor` обязан определять как минимум:

- integrity/security/recovery/transport outcome;
- consumer;
- retention/collection cost;
- failure consequence;
- reset/recovery path и acceptance tests.

Для одной capability `loop_refs` и `technical_purpose_ref` не могут одновременно
использоваться как два конкурирующих primary justification. Дополнительный
service state capability покрывается отдельными field-level Technical Purpose
bindings согласно `LOOP-SPEC.md`.

Фраза «общая utility» и произвольная строка недостаточны.

## 4.3 Descriptor immutability

Descriptor конкретной version immutable после release.

Исправление typo без semantic effect MAY создать patch version. Изменение уже опубликованного descriptor/hash in place запрещено.

## 4.4 Availability declaration

```yaml
availability:
  platforms: [desktop | mobile | cli]
  offline: full | local_data_only | unavailable
  required_modules: [ModuleVersionRef]
  external_dependencies: [ExternalDependencyRef]
  degraded_behavior: string
```

`offline: full` означает отсутствие скрытой external dependency для declared scope. `local_data_only` явно отделяет локальный результат от функций, требующих download/provider/peer.

## 4.5 Consumer declaration

```yaml
consumer_id: string
kind: ui | cli | module | processor | workflow | sync | ai_gateway
purpose: string
version_constraint: VersionConstraint
required: boolean
loop_ref: LoopId | null
```

Descriptor перечисляет известных normative consumers. Дополнительный caller MAY использовать public capability только через обычные permissions/limits, но capability не создаётся исключительно для гипотетического «будущего consumer».

## 4.6 Kind applicability matrix

Common validator применяет следующую baseline-матрицу:

| Kind | Required data access | Forbidden direct data access | Допустимый `ai_exposure_max` | Особое правило |
|---|---|---|---|---|
| Command | Все declared reads/writes и external-effect refs | Прямые `derived_outputs` | `none`, `proposal`, `confirmed_command`, `restricted_workflow` только для workflow entry | Canonical/`OT`/`DL` mutation только через declared effects; post-commit outputs принадлежат Processor/Kernel baseline |
| Query | `reads` | `writes`, `derived_outputs`, `external_effects` | `none`, `read_only` | Read-only; audit/cache являются Kernel-injected effects |
| Event | Нет direct storage access | `writes`, `derived_outputs`, `external_effects` | `none` | Payload и subscriptions задаются event section |
| Processor | `reads`, `derived_outputs` | canonical `writes`, `external_effects` | `none` | Пишет только `DD/OR`; promotion идёт Command |
| Widget | Нет direct storage access | Все direct effects | `none` | Использует только declared Query/action refs |
| Form | Нет direct storage access | Все direct effects | `none` | Submit вызывает target Command |
| Exporter | `reads` для фактического snapshot scope | canonical `writes`, `derived_outputs`, `external_effects` | `none` | Artifact создаётся вне canonical transaction |

Пустой список объявляется явно. `not_applicable` не заменяет обязательную kind-specific section.

Schema applicability также однозначна:

| Kind | Common `input_schema` / `output_schema` | Kind-specific schema |
|---|---|---|
| Command | Оба обязательны | Нет duplicate payload/result schema |
| Query | Оба обязательны | Нет duplicate payload/result schema |
| Event | Оба `null` | `event.payload_schema` |
| Processor | Оба `null`, если нет отдельной public manual invocation | Inputs/outputs задаются DataAccess/DataOutput rules |
| Widget | Оба `null` | `widget.props_schema`; Query results принадлежат referenced Queries |
| Form | Оба `null` | Field declarations отображаются в `target_command.input_schema` |
| Exporter | Оба `null` | Format и manifest schemas находятся в exporter section; Start/Status schemas принадлежат Commands/Queries |

`error_contract` обязателен для Command/Query. Event использует `null`; Processor/Widget/Form/Exporter сообщают failures через typed Job, bound capability или declared fallback contract и не создают второй несовместимый Error Envelope.

Для Event, Widget и Form common `permissions` описывает publication/subscription/render/action ceiling, а не даёт им самостоятельный storage access. Их platform availability задаётся только common `availability.platforms`; отдельные kind-specific `platforms` запрещены.

---

# 5. Registration и lifecycle

## 5.1 Lifecycle

```text
declared → validated → registered → active → deprecated → disabled → removed
```

`removed` означает удаление executable implementation из поддерживаемого release, а не удаление пользовательских данных или historical contract metadata.

Descriptor field `status` является release declaration (`experimental | active | deprecated | disabled`). Состояния `declared | validated | registered | removed` принадлежат Registry lifecycle и не записываются как дополнительные значения `status` того же descriptor.

Status `experimental` не является исключением из Конституции. Experimental capability либо полностью соблюдает применимые contracts, либо работает только в изолированном sandbox без production canonical data и release consumers.

## 5.2 Startup registration

При запуске Core:

1. загружает built-in module manifests;
2. собирает capability/workflow descriptors, scopes и schemas;
3. проверяет unique IDs и versions;
4. проверяет contract hashes;
5. разрешает schema references;
6. проверяет Data Catalog access;
7. проверяет permissions/limits;
8. проверяет loops/consumers;
9. проверяет workflow state machines, step refs, outbound allowlists и retry safety;
10. строит module/capability/workflow dependency DAG;
11. регистрирует совместимые capabilities и workflows;
12. активирует только contracts active modules.

Ошибка одной capability или workflow блокирует activation её module, но не должна повреждать Registry других modules.

## 5.3 Registry generation

Активные Capability и Workflow Registries образуют согласованный immutable snapshot одной runtime generation.

Activation/deactivation module создаёт новую Registry generation после validation. Invocation/workflow instance, начатый в старой generation, завершается по pinned contracts либо безопасно переводится в declared recovery/cancellation state согласно lifecycle policy.

## 5.4 Discovery

Registry MAY предоставлять filtered discovery Query.

Discovery возвращает только capabilities, которые:

- активны;
- доступны caller platform;
- не скрыты administrative policy;
- имеют хотя бы потенциально разрешённый scope для actor;
- допустимы соответствующему consumer type.

Наличие capability в полном Registry не означает её доступность AI.

## 5.5 Disabled capability

Invocation disabled capability возвращает `CAPABILITY_UNAVAILABLE` с typed recovery/dependency metadata.

Disable не удаляет schemas, revisions, data или exporter fallback, необходимые для чтения и переноса накопленной информации.

---

# 6. Contract type system

## 6.1 Scalar types

Поддерживаются как минимум:

| Type | Semantics |
|---|---|
| `string` | UTF-8 text с length/normalization policy |
| `boolean` | true/false |
| `int32` / `int64` | точное целое |
| `decimal` | точное decimal representation, не binary float |
| `enum` | closed или extensible string enum |
| `date` | календарная дата без timezone |
| `timestamp` | absolute instant + declared serialization |
| `local_datetime` | локальное время только с отдельным timezone/ambiguity policy |
| `duration` | точный duration с unit |
| `entity_id` | stable typed entity reference |
| `revision_id` | stable revision reference |
| `blob_handle` | Core-issued staged/final blob handle |
| `secret_handle` | opaque Secret Service reference |
| `cursor` | opaque bounded pagination/workflow token |
| `hash` | algorithm + digest |

Canonical measurements MUST NOT использовать binary float, если rounding меняет public semantics. Используется `decimal` + explicit unit/precision.

## 6.2 Composite types

Допускаются:

- bounded object;
- bounded list/set;
- typed map с ограниченными keys/value schema;
- tagged union с explicit discriminator;
- optional field;
- nullable field;
- namespaced extension object с отдельным SchemaRef.

Arbitrary recursive JSON и untyped `metadata: object` запрещены в public contracts.

## 6.3 Optionality и nullability

Отсутствие field и explicit `null` имеют разные semantics и объявляются отдельно.

Contract обязан определить missing behavior:

- required;
- optional with default;
- optional unknown;
- nullable;
- not_applicable.

## 6.4 Constraints

Input fields объявляют применимые:

- min/max length;
- numeric range/precision;
- list/map bounds;
- format;
- enum openness;
- normalization;
- sensitivity/classification reference;
- units;
- cross-field invariants;
- canonical serialization.

Normalization rule не даёт права терять semantically significant raw input. Если normalization может изменить научное, юридическое или пользовательски значимое содержание, schema объявляет отдельное raw field/provenance либо запрещает автоматическую canonicalization.

## 6.5 Unknown fields

Input неизвестного field отклоняется по умолчанию.

Extension points допускаются только как namespaced, schema-bound fields.

Client в пределах совместимого major MUST игнорировать неизвестные optional output fields, если они не меняют interpretation известных полей.

## 6.6 Enums

Closed enum требует major version для нового value, если consumer не может безопасно обработать unknown.

Extensible enum требует declared fallback behavior. Client не должен интерпретировать unknown как первое/default value.

## 6.7 Time

Contract различает:

- wall-clock timestamp для UX/audit;
- logical/device sequence для ordering;
- local date/timezone для календарной semantics;
- duration/lag.

Wall clock не используется как единственный conflict/order mechanism.

## 6.8 File и secret inputs

Capability не принимает arbitrary filesystem path или raw credential.

- file input использует Core-issued `blob_handle`/staging grant;
- secret input проходит Secret Service и передаётся как `secret_handle`;
- local path MAY использоваться только внутренним platform adapter в scoped user-approved file grant и не становится global identity.

---

# 7. Schemas и references

## 7.1 Schema identity

Schema имеет:

```text
schema_id
semantic_version
canonical_hash
owner_module
root_type
```

## 7.2 SchemaRef

Capability descriptor ссылается на exact schema version/hash либо совместимый immutable bundle, разрешённый во время Registry validation.

Floating `latest` reference запрещён в released descriptor.

## 7.3 Shared types

Kernel MAY поставлять общие primitive schemas:

- entity/revision refs;
- pagination;
- provenance;
- typed errors;
- confirmation token;
- job/workflow ref;
- blob/secret handles.

Shared schema не содержит domain-specific fields.

## 7.4 Canonical encoding

Для hashing/idempotency задаётся canonical serialization:

- deterministic field ordering;
- normalized numbers/timestamps;
- explicit absent/null distinction;
- stable Unicode normalization policy;
- no insignificant duplicate map keys;
- schema version included.

Wire encoding MAY отличаться, но payload fingerprint строится по canonical semantic representation.

---

# 8. Invocation model

## 8.1 Client Request Envelope

```yaml
request_id: RequestId
capability:
  id: CapabilityId
  version_constraint: VersionConstraint
client_context:
  client_id: ClientId
  client_version: SemVer
  locale: string
  timezone: string
deadline: timestamp | null
payload: InputSchema
```

Client MUST NOT передавать доверенные actor, permission или audit fields внутри payload.

`locale/timezone` в client context используются для presentation/default suggestions и не меняют parsing/meaning canonical typed fields. Семантически значимые timezone/unit передаются явно внутри validated domain payload.

## 8.2 Core Execution Context

Core создаёт и передаёт handler:

```yaml
execution_context:
  actor: VerifiedActor
  origin: VerifiedOrigin
  device_id: DeviceId
  client_id: ClientId
  registry_generation: RegistryGeneration
  resolved_capability_version: SemVer
  permission_grant: EffectiveGrant
  trace_id: TraceId
  request_id: RequestId
  clock: KernelClock
  id_generator: KernelIdGenerator
  cancellation: CancellationToken
  deadline: timestamp | null
```

Handler не читает actor/scopes из user payload и не использует hidden environment clock/randomness.

## 8.3 Result Envelope

```yaml
request_id: RequestId
capability:
  id: CapabilityId
  resolved_version: SemVer
registry_generation: RegistryGeneration
status: success | accepted | partial | error
result: OutputSchema | null
error: ErrorEnvelope | null
warnings: [TypedWarning]
provenance: ProvenanceEnvelope | null
freshness: FreshnessEnvelope | null
page: PageEnvelope | null
job: JobRef | null
audit_ref: AuditRef | null
trace_id: TraceId
```

Result MUST NOT возвращать internal stack trace, raw secret или необъявленное field.

## 8.4 Version resolution

Core разрешает version constraint до policy/handler execution и возвращает exact resolved version.

Unknown/incompatible version возвращает `UNSUPPORTED_VERSION`, а не silently выбирает другой major.

Если существует idempotency record этого intent, первоначально resolved version/contract hash pinned и используются для status/result reconciliation. Retry не переезжает на новый minor только из-за обновления Registry.

## 8.5 Cancellation

Cancellation является request, а не гарантией rollback уже committed effect.

Contract объявляет cancellation point и terminal state semantics.

---

# 9. Permission model

## 9.1 Maximum authority vs effective grant

Descriptor определяет максимальную власть capability. Runtime grant является пересечением:

```text
declared capability maximum
∩ verified actor grants
∩ module policy
∩ container/record policy
∩ data sensitivity policy
∩ consumer type policy
∩ destination/provider policy
```

Deny/restriction имеет приоритет.

## 9.2 Actor kinds

Минимальные kinds:

- `user`;
- `system`;
- `module`;
- `device`;
- `sync_peer`;
- `ai`;
- `migration`;
- `recovery`.

Origin AI не становится `user` после UI confirmation. Audit сохраняет AI origin и user confirmer как разные identities.

## 9.3 Permission declaration

```yaml
permissions:
  allowed_actor_kinds: [ActorKind]
  read_scopes: [DataScopeRef]
  write_scopes: [DataScopeRef]
  sensitivity_ceiling: P0 | P1 | P2 | P3 | P4
  field_allowlist: [CatalogFieldRef]
  max_time_range: duration | null
  max_batch: int
  outbound_network: none | declared_only
  secret_access: none | [SecretPurpose]
  administrative: false
  confirmation_floor: ConfirmationLevel
```

Для Command kind-specific `confirmation` MUST быть не слабее `confirmation_floor`. Runtime MAY повысить effective level из-за actual scope, sensitivity, consumer или operation policy.

`permissions.max_batch` является authority ceiling конкретного grant, а `limits.max_batch` — абсолютным contract/resource ceiling. Effective batch равен минимуму capability limit, verified grant, consumer policy и runtime admission limit. Ни одно из значений не расширяет другое.

## 9.4 DataScope

`DataScopeRef` ссылается на immutable namespaced scope declaration из того же module contract bundle. Floating/wildcard reference запрещён.

```yaml
scope_id: DataScopeId
version: SemVer
contract_hash: Hash
owner_module: ModuleId
catalog_refs: [CatalogTypeOrFieldRef]
field_allowlist: [FieldPath]
selector: SelectorConstraint
operations: [read | create | correct | revise | tombstone | purge]
sensitivity_ceiling: P0 | P1 | P2 | P3 | P4
max_cardinality: int
```

Scope ID использует namespaced stable identity. `SelectorConstraint` не допускает произвольный predicate/SQL и ограничивается schema-defined target ID, container subtree, bounded time range или другим зарегистрированным selector kind.

Resolved scope ограничивает:

- owner module;
- record/catalog types;
- field paths;
- record IDs/container subtree;
- time range;
- operation;
- sensitivity;
- batch cardinality.

Global wildcard запрещён для AI, external modules и ordinary clients.

## 9.5 Secret access

Capability получает не raw secret через Query, а purpose-bound handle/use operation.

Provider Adapter MAY использовать secret только для declared provider/purpose. Secret value не возвращается caller и не попадает в result/audit body.

## 9.6 Permission failure

Denied access возвращает `PERMISSION_DENIED` или policy-specific safe error без раскрытия существования restricted record, если existence чувствительна.

## 9.7 Administrative capabilities

Migration, restore, purge, device revocation и security configuration:

- помечены `administrative: true`;
- недоступны generic discovery/AI;
- используют отдельный confirmation/policy path;
- имеют exact scopes;
- не объединяются в universal admin command.

---

# 10. Data Classification integration

## 10.1 DataAccessRule

Каждое чтение объявляет:

```yaml
catalog_ref: CatalogTypeOrFieldRef
class: CF | CE | CR | CB | CA | DD | OT | OR | DL
fields: [FieldPath]
purpose: string
consistency: canonical | derived | mixed
sensitivity_max: P0 | P1 | P2 | P3 | P4
selector_limits: SelectorLimits
```

## 10.2 DataEffectRule

Каждый effect объявляет:

```yaml
catalog_ref: CatalogTypeOrFieldRef
class: CF | CE | CR | CB | CA | OT | DL
operation: ClassOperation
writer: command | audit_service | blob_service | admin_workflow | kernel_service | local_state_service
syncable: boolean
outbox_required: boolean
undo_behavior: UndoBehavior
```

`ClassOperation` является tagged union; допустимые значения определяются class:

| Class | Допустимые operations |
|---|---|
| `CF` | `append_fact`, `append_correction` |
| `CE` | `create_entity`, `append_revision`, `move_head`, `archive`, `tombstone` |
| `CR` | `create_relation`, `append_relation_revision`, `tombstone_relation` |
| `CB` | `adopt_blob` |
| `CA` | `append_evidence` |
| `OT` | `create_intent`, `transition`, `checkpoint`, `complete`, `fail`, `cleanup` |
| `DL` | `set_local`, `reset_local` |
| `CF/CE/CR/CB/CA` through administrative workflow | `purge` с exact scope; ordinary writer использовать его не может |

Operation из другой строки таблицы является schema error, а не runtime no-op. `CF` не имеет generic tombstone; invalidation создаётся `append_correction`.

Domain-to-blob attach/release является `CR` mutation и использует relation operations; Blob Service не получает право менять module references напрямую.

Ordinary capability не пишет `DD/OR` как canonical effect и не пишет `SE` в DB. Processor outputs описываются отдельно.

Service writers используются строго по class: `audit_service` для `CA`, `blob_service` для adoption `CB`, `kernel_service` для `OT`, `local_state_service` для `DL`. `OR/DD` описываются как `DataOutputRule`, а не canonical effect. Module descriptor не может самоназначить service writer без соответствующего Kernel port.

`SE` отсутствует в обычных DataAccessRule/DataEffectRule. Доступ к credential выражается только отдельным `SecretAccessRule` и purpose-bound `secret_handle`.

## 10.3 DataOutputRule

Processor/Kernel output объявляется отдельно:

```yaml
catalog_ref: CatalogTypeOrFieldRef
class: DD | OR
writer: processor | kernel_service
input_refs: [CatalogTypeOrFieldRef]
algorithm_or_service_version: string
sensitivity_inheritance: max_inputs | explicit_stricter
rebuild_or_reset: RebuildOrResetRef
```

`DD` требует provenance и rebuild; `OR` требует safe reset/cleanup proof.

## 10.4 SecretAccessRule

```yaml
purpose: SecretPurpose
handle_type: SecretHandleType
operations: [create_handle | use_for_declared_adapter | rotate | revoke]
adapter_or_service: ServiceRef
raw_value_returned: false
```

Raw secret read через capability запрещён.

## 10.5 Validation

Registry отклоняет capability, если:

- writer не разрешён primary class;
- operation не входит в tagged operation set заявленного class;
- field отсутствует в Data Catalog;
- write sensitivity выше permission ceiling;
- capability пишет syncable data без outbox rule;
- Query объявляет mutation;
- Processor пытается promotion без Command;
- secret передаётся как обычное field;
- export/AI exposure конфликтует с classification policy;
- capability читает field без consumer/purpose;
- один и тот же common/kind semantic field объявлен повторно;
- `ai_exposure_max` несовместим с kind applicability matrix.

## 10.6 Effective sensitivity

Runtime вычисляет sensitivity из Data Catalog и конкретных records. Descriptor ceiling не понижает record sensitivity.

Если actual record выше ceiling, invocation выполняет redaction, partial denial либо полный deny согласно declared output policy; silently раскрывать field запрещено.

## 10.7 Kernel-injected baseline effects

Некоторые system effects следуют из kind и policy, а не повторяются вручную в каждом descriptor:

- Command receipt `CA`;
- idempotency `OT` для Command;
- event/sync outbox `OT`, когда соответствующие declarations не `not_applicable`;
- required security-read audit `CA` для Query;
- bounded cache/diagnostic `DD/OR`, если разрешён query/observability contract.

Registry normalizer разворачивает эти baseline effects в effective descriptor до validation и contract hashing. Module не может отключить их пустым `data_access` или переопределить writer. Domain-specific `CA/OT/DD/OR` effects baseline не покрывает и они объявляются явно.

---

# 11. Command Contract

## 11.1 Назначение

Command изменяет declared canonical state, управляемое `OT/DL` state либо создаёт контролируемый intent внешнего effect. Все фактические reads/writes указываются только в common `data_access`.

## 11.2 Descriptor extension

```yaml
command:
  transaction: required | administrative
  idempotency: IdempotencyDeclaration
  preconditions: [PreconditionDeclaration]
  events_emitted: [EventRef]
  workflow_started: WorkflowRef | null
  sync_outbox: required | not_applicable
  preview: PreviewPolicy
  confirmation: ConfirmationPolicy
  undo: UndoDeclaration
  batch_atomicity: all_or_nothing | per_item | not_batch
  result_visibility: full | minimized
```

## 11.3 Command Request fields

Command invocation дополнительно содержит Core-recognized:

```yaml
command_id: GlobalCommandId
idempotency_key: string
expected_revisions: [ExpectedRevision]
preview_token: OpaquePreviewToken | null
confirmation_token: OpaqueConfirmationToken | null
```

Эти fields находятся в command envelope, а не смешиваются с domain payload.

## 11.4 Validation phases

Command проходит:

1. transport/size validation;
2. actor/origin verification;
3. capability ID/major parsing и idempotency-scope lookup;
4. exact version resolution либо восстановление pinned version существующего intent;
5. input schema validation;
6. permission/sensitivity policy;
7. fingerprint comparison/new intent registration;
8. preview/confirmation validation;
9. optimistic preconditions;
10. domain validation;
11. Unit of Work;
12. canonical effects + audit + events + outbox;
13. commit;
14. post-commit signaling.

## 11.5 Handler restrictions

Command handler MUST NOT:

- выполнять network/AI call;
- читать wall clock/random environment напрямую;
- открывать DB connection;
- писать чужой module storage напрямую;
- вызывать nested public Command;
- обходить Data Catalog policy;
- создавать unbounded result;
- скрыто менять data вне declared effects.

Kernel предоставляет transaction context, clock, IDs и scoped repositories.

## 11.6 Optimistic concurrency

Revisioned mutation SHOULD требовать `expected_revision` или explicit merge intent.

Mismatch возвращает `REVISION_CONFLICT` с безопасным current head reference и supported recovery actions. Silent overwrite запрещён.

## 11.7 Batch commands

Batch capability обязана объявить finite `max_batch` и atomicity:

- `all_or_nothing` — один failure откатывает весь batch;
- `per_item` — каждый item имеет отдельный sub-result/effect boundary и idempotency sub-key;
- `not_batch` — list payload запрещён.

Неопределённая частичная успешность запрещена.

## 11.8 No-op

Command MAY вернуть `changed: false`, если desired state уже достигнут. Это не считается ошибкой и не создаёт duplicate domain fact без необходимости.

No-op сохраняет command/idempotency receipt, но не создаёт fake revision/event только ради видимости activity.

## 11.9 Correction и revision

- `CF` исправляется отдельной correction Command;
- `CE` изменяется новой revision;
- `CR` изменяется relation revision/tombstone semantics;
- `CB` bytes не меняются, создаётся новый blob/reference;
- `CA` append выполняет Audit Service, не ordinary module handler.

---

# 12. Query Contract

## 12.1 Назначение

Query читает canonical/derived state и не меняет предметное состояние.

## 12.2 Descriptor extension

```yaml
query:
  consistency: canonical | projection | mixed
  freshness: FreshnessContract
  pagination: none | cursor | bounded_offset
  ordering: OrderingContract
  snapshot: none | request | cursor_bound
  provenance: none | summary | item_level
  redaction: deny | field_redaction | partial_items
  security_audit: none | metadata | required
  cache: none | local | derived
```

## 12.3 Read-only semantics

Query MUST NOT:

- писать canonical state;
- создавать domain event;
- запускать external effect;
- принимать raw SQL;
- изменять head/job/workflow;
- скрыто сохранять user content.

Security audit и bounded cache выполняются Kernel Services по отдельным classification rules и не превращают Query в Command.

Если `security_audit: required`, Audit Service failure является fail-closed: sensitive result не возвращается. `metadata` и `none` следуют явной policy, но не могут ослабить Data Classification requirement.

## 12.4 Pagination

Unbounded list Query запрещён.

Cursor:

- opaque;
- связан с capability/version/filter/sort;
- имеет expiry и sensitivity;
- не содержит secret/raw query plan;
- не расширяет permission при повторном использовании;
- возвращает stable ordering contract.

Offset pagination допускается только для bounded/local datasets с объявленным consistency behavior.

## 12.5 Ordering

Query указывает deterministic tie-breaker. Wall-clock field без stable ID tie-breaker недостаточен.

## 12.6 Freshness

Projection/mixed Query возвращает:

- processor/model version;
- source cursor/generation;
- built_at;
- lag/stale state;
- rebuild/error state, если применимо.

## 12.7 Provenance

Analytics/model Query по contract возвращает ссылки на definitions и source observations в заявленной granularity.

## 12.8 Safe Query DSL

Saved/dynamic Query может ссылаться только на registered sources/operators и проходит тот же permission/cost/classification boundary.

Raw SQL/implementation table names не являются public contract.

---

# 13. Event Contract

## 13.1 Назначение

Event уведомляет consumers о committed semantic change. Event не заменяет canonical state и не создаёт full event sourcing.

Если information нельзя восстановить из canonical state и она имеет предметную/evidence ценность, Command MUST сохранить отдельный `CF/CA`; Event record не становится её единственной копией.

## 13.2 Descriptor extension

```yaml
event:
  payload_schema: SchemaRef
  subjects: [SubjectDeclaration]
  emitted_by: [CommandRef]
  sensitivity_inheritance: SensitivityRule
  delivery: at_least_once
  ordering: none | per_subject | per_device_sequence
  retention: RetentionPolicyRef
  subscriptions: [EventSubscriptionDeclaration]
```

Каждая subscription ссылается по `consumer_id` на один common `ConsumerDeclaration` и добавляет только delivery/filter/checkpoint semantics. Она не создаёт второго описания purpose, loop или version constraint.

## 13.3 Event envelope

```yaml
event_id: GlobalEventId
event_type: CapabilityId
event_version: SemVer
owner_module: ModuleId
command_id: GlobalCommandId | null
correlation_id: CorrelationId
subject_refs: [TypedEntityRef]
device_id: DeviceId
device_sequence: int64
logical_time: LogicalTime
committed_at: timestamp
sensitivity: P0 | P1 | P2 | P3
payload: EventPayload
```

Event MUST NOT содержать `P4` secret.

## 13.4 Atomicity

Event/outbox append происходит в одной transaction с canonical change.

Notification dispatch начинается только после commit.

## 13.5 Payload minimization

Payload содержит только данные, необходимые declared consumers. Consumer SHOULD получать full current state через Query, если дублирование content увеличивает privacy/compatibility risk.

## 13.6 Delivery

Delivery at-least-once. Consumer использует event ID/checkpoint и MUST быть идемпотентным.

Глобальный total order не обещается. Ordering гарантируется только в declared scope.

## 13.7 Event consumer effects

Consumer:

- MAY обновлять declared `DD/OR` через Processor;
- MAY инициировать новую Command с собственным idempotency key;
- MUST NOT писать canonical state напрямую.

---

# 14. Processor Contract

## 14.1 Назначение

Processor асинхронно строит derived state либо выполняет ограниченную maintenance работу после canonical commit.

## 14.2 Descriptor extension

```yaml
processor:
  mode: derived | maintenance
  triggers: [EventRef | ScheduleRef | ManualJobRef | RebuildRef]
  algorithm_version: string
  deterministic: true | seeded | false_with_reason
  checkpoint: CheckpointPolicy
  rebuild: RebuildDeclaration
  delivery: at_least_once
  retry: RetryPolicy
  concurrency: ConcurrencyPolicy
```

Processor inputs и outputs объявляются только в common `data_access.reads` и `data_access.derived_outputs`; resource ceilings — только в common `limits`.

## 14.3 Outputs

Processor напрямую пишет только declared `DD` или `OR`.

Исторически значимый/невоспроизводимый результат становится `CF/CE/CA` только через отдельную Command promotion.

## 14.4 Determinism

Rebuildable output зависит от:

- exact canonical inputs/cursor;
- definition version;
- processor/algorithm/model version;
- explicit parameters;
- seed, если применяется.

External nondeterministic response не считается rebuildable Processor output.

Mode `derived` допускает только `true` или `seeded`. `false_with_reason` разрешён лишь maintenance Processor, который пишет `OR` и не создаёт semantic `DD`; значимый nondeterministic result проходит Command promotion в `CF/CA`.

## 14.5 Retry/checkpoint

Processor должен переживать duplicate event и crash без duplicate observable state.

Checkpoint:

- связан с processor version;
- не перескакивает непроцессированный input;
- atomically связан с output generation, где требуется;
- сбрасывается безопасно при full rebuild.

## 14.6 External effects

Обычный Processor не выполняет network/external irreversible effect.

Такие действия используют explicit external-effect workflow раздела 18 с intent/outbox/executor/result Command.

## 14.7 Failure

Failure переводит processor/job в typed diagnostic state и помечает зависимые projections stale/unavailable. Canonical inputs остаются доступными.

---

# 15. Widget Contract

## 15.1 Назначение

Widget отображает typed Query results и объявленные actions, не владея domain logic.

## 15.2 Descriptor extension

```yaml
widget:
  props_schema: SchemaRef
  query_slots: [QueryBindingDeclaration]
  actions: [CommandActionDeclaration]
  states: [loading, empty, ready, stale, error, unauthorized, unavailable]
  sensitivity_display: DisplayPolicy
  accessibility: AccessibilityDeclaration
  fallback: FallbackDeclaration
```

## 15.3 Query bindings

Widget instance связывается только с:

- registered Query;
- saved Query с validated Safe Query DSL;
- typed parameters из props/layout context.

Widget не генерирует SQL и не расширяет Query scopes.

## 15.4 Actions

Action ссылается на declared Command/Form и может передать только schema-bound mapping.

Widget не выполняет mutation самостоятельно.

## 15.5 Required states

Widget явно обрабатывает:

- permission denied;
- unavailable module/capability;
- stale/rebuilding projection;
- empty result;
- partial/redacted data;
- typed error;
- unknown compatible optional fields.

## 15.6 Unknown widget

Unknown/incompatible widget не ломает layout. Shell отображает fallback с owner/version/recovery и сохраняет instance data для будущего восстановления/export.

## 15.7 Sensitivity

Widget не должен раскрывать sensitive value через title, preview, notification, count или cached screenshot вне effective display policy.

---

# 16. Form Contract

## 16.1 Назначение

Form декларативно собирает input и создаёт Command invocation.

## 16.2 Descriptor extension

```yaml
form:
  fields: [FormFieldDeclaration]
  target_command: CommandRef
  mapping: DeclarativeMapping
  option_queries: [QueryRef]
  local_validation: [AdvisoryValidation]
  preview: inherit | force | none
  draft_policy: none | device_local | revisioned
```

## 16.3 Authority

Command input schema и Core validation являются авторитетными. Form validation только ускоряет feedback.

Form `preview` MAY сохранить или усилить target Command policy, но MUST NOT ослабить её. Значение `none` допустимо только когда Command не требует preview для фактического scope.

## 16.4 Declarative mapping

Mapping допускает только:

- field reference;
- literal/default;
- typed rename;
- approved lossless conversion;
- list/object construction по schema;
- Core-bound context value, например expected revision.

Arbitrary expression/code, SQL и hidden permission field запрещены.

## 16.5 Dynamic options

Options загружаются registered Query и наследуют permissions/sensitivity. Form не может отправить значение, отсутствующее в Command schema, только потому что оно было показано UI.

## 16.6 Files и secrets

- file picker создаёт scoped staging `blob_handle`;
- secret field записывает value через Secret Service и передаёт `secret_handle`;
- Form draft не хранит raw secret;
- hidden field не может содержать actor/grant/confirmation token.

## 16.7 Drafts

- `none` — input живёт только в UI memory;
- `device_local` — `DL` с sensitivity/cleanup;
- `revisioned` — отдельная `CE` capability и явный user expectation.

Form не повышает draft durability молча.

## 16.8 Submit

Новая user intent создаёт новый command ID/idempotency key. Повтор transport submit использует тот же key.

---

# 17. Exporter Contract

## 17.1 Назначение

Exporter создаёт portable artifact из consistent Query/snapshot scope согласно Data Classification.

## 17.2 Descriptor extension

```yaml
exporter:
  coverage: [CatalogTypeOrFieldRef]
  formats: [ExportFormatDeclaration]
  manifest_schema: SchemaRef
  snapshot: required | best_effort_declared
  redaction: RedactionPolicy
  secret_policy: prohibit
  streaming: StreamingPolicy
  checksums: ChecksumPolicy
  validation: [ExportValidationRef]
  round_trip: required | supported | not_supported_with_reason
  disabled_module_mode: maintenance | generic_fallback
```

## 17.3 Invocation

User-facing export начинается Command, которая:

1. фиксирует scope/policy;
2. выполняет preview/confirmation;
3. создаёт durable job;
4. возвращает JobRef.

Exporter читает snapshot и пишет artifact вне canonical transaction.

## 17.4 Completeness

Exporter MUST:

- покрывать declared required canonical types;
- включать stable IDs/versions/relations;
- сохранять original blobs по scope;
- документировать exclusions/redactions;
- проверять checksums;
- выдавать typed incomplete/failure, а не молча успешный partial export.

Для каждого v1 module, владеющего пользовательскими canonical data, минимум один обязательный machine-readable format имеет `round_trip: required` и сохраняет stable IDs, revisions/parents/heads, relations и original blob references. Human-readable format MAY использовать `supported` или `not_supported_with_reason`.

## 17.5 Sensitivity

`P2/P3` export требует exact scope/destination warning. `SE` запрещён. Marked unstructured `P4` требует отдельного targeted high-risk workflow по Data Classification.

## 17.6 Disabled module

Disable module не лишает пользователя export. Maintenance exporter или documented generic fallback остаётся доступным без запуска обычных module handlers/processors.

## 17.7 Retained artifacts

Generated file не становится canonical автоматически. Explicit retain/import Command создаёт `CB/CE` согласно Data Classification.

---

# 18. Workflows и external effects

Workflow является explicit composition capabilities, но не новым unrestricted capability kind.

## 18.1 Atomic composite Command

Используется, если несколько module effects обязаны commit атомарно.

Composite Command:

- имеет одного owner;
- объявляет participants/effects;
- открывает один Unit of Work;
- вызывает internal mutation ports, не nested public Commands;
- применяет permissions каждого effect;
- создаёт один command receipt с typed sub-results;
- имеет одну idempotency/undo policy.

## 18.2 Long-running workflow

Используется для import, export, backup, restore, sync batch, AI/external operations.

```text
Start Command
→ durable workflow state (OT)
→ bounded steps/jobs
→ optional external effect
→ terminal OT transition
→ optional Result Command for canonical domain outcome
→ mandatory CA receipt for significant boundary outcome
```

`CA` не заменяет terminal `OT` transition и не становится предметным result автоматически. Если внешний ответ имеет самостоятельную историческую ценность, Result Command сохраняет отдельный `CF/CE` согласно Data Classification.

## 18.3 Workflow Descriptor

Workflow не является восьмым capability kind, но является first-class registered contract с собственной identity:

```yaml
workflow_id: WorkflowId
version: SemVer
contract_hash: Hash
owner_module: ModuleId
status: experimental | active | deprecated | disabled

entry_command: CommandRef
state_schema: SchemaRef  # primary class OT
initial_state: string
terminal_states: [string]
steps: [WorkflowStepDeclaration]

permissions: WorkflowPermissionDeclaration
ai_exposure_max: none | restricted_workflow
capability_refs: [CapabilityRef]
external_effects: [ExternalEffectRule]
secret_handles: [SecretAccessRule]
limits: ResourceLimits
cost_budget: CostBudget
stop_conditions: [StopCondition]
concurrency: ConcurrencyPolicy
cancellation: CancellationPolicy
compensation: CompensationPlan

result_query: QueryRef
audit: AuditDeclaration
consumers: [ConsumerDeclaration]
acceptance_tests: [TestRef]
compatibility: CompatibilityDeclaration
```

`WorkflowStepDeclaration` содержит:

```yaml
step_id: string
executor_kind: capability | kernel_service | external_effect
target_ref: CapabilityRef | KernelWorkflowPortRef | ExternalEffectRef
input_mapping: DeclarativeMapping
allowed_from_states: [string]
success_transition: string
failure_transition: string
idempotency: StepIdempotencyDeclaration
timeout: duration
retry: RetryPolicy
checkpoint: CheckpointPolicy
compensation_step: WorkflowStepRef | null
```

Правила:

- descriptor, state schema, referenced schemas и exact external-effect rules входят в `contract_hash`;
- все references разрешаются при module activation; floating `latest` запрещён;
- state machine конечна, имеет хотя бы одно terminal state и не содержит unreachable/implicit transitions;
- Kernel Workflow Service является единственным writer `OT` workflow state;
- module capability/executor возвращает typed step outcome и не меняет workflow row напрямую;
- capability step выполняется как отдельная invocation/transaction с derived idempotency key и causation reference, а не как nested public Command внутри открытой transaction;
- input mapping декларативен и не содержит code/SQL/arbitrary expression;
- workflow version pinned при Start Command и не меняется во время retry после Registry update;
- disable/deprecation сохраняет status/recovery Query для уже принятых workflow instances.

`command.workflow_started` является единственной связью entry Command с Workflow Descriptor. Все `ExternalEffectRef` common descriptor должны разрешаться в rules этого workflow либо другого явно referenced workflow contract.

## 18.4 External-effect pattern

Каждый declared `ExternalEffectRule` содержит:

```yaml
effect_id: string
adapter: AdapterRef
action: string
destination: DestinationRef
input_schema: SchemaRef
input_catalog_fields: [CatalogFieldRef]
outbound_policy: OutboundPolicyRef
redaction: RedactionPolicy
input_sensitivity_max: P0 | P1 | P2 | P3
secret_purposes: [SecretPurpose]
output_schema: SchemaRef
result_classification: ResultClassificationDeclaration
provider_idempotency: required | supported | unavailable
timeout: duration
retry: RetryPolicy
cost_budget: CostBudget
reversibility: reversible | compensating | irreversible
result_command: CommandRef | null
status_reconciliation: QueryOrAdapterStatusRef | null
```

`input_catalog_fields` является полным allowlist outbound data. Adapter не может добавить field из execution environment, log, retrieved content или secret store, кроме явно declared `secret_purposes`; raw secret не входит в `input_schema`.

Runtime вычисляет effective outbound policy по каждому record/field и destination до создания intent. `P4` запрещён. `P3` для cloud destination требует заранее committed усиленную policy revision согласно Data Classification; один workflow grant или prompt её не заменяет.

1. Intent Command commit-ит canonical intent/OT outbox.
2. Executor получает intent после commit.
3. Executor заново проверяет destination, outbound policy generation, exact serialized input hash и cost budget.
4. Executor использует provider idempotency, если доступно.
5. Kernel Workflow Service фиксирует attempt/status в `OT`.
6. Result Command фиксирует самостоятельный domain outcome, если он declared.
7. Audit Service создаёт minimized `CA` receipt.
8. Unknown effect state требует status reconciliation до retry.

Network call внутри canonical transaction запрещён.

Retry safety matrix:

| Provider idempotency | Status reconciliation | Reversibility | Automated retry |
|---|---|---|---|
| `required/supported` и key принят | Любая | Любая | Только в declared retry budget |
| `unavailable` | Доступна и authoritative | Reversible/compensating | После обязательной reconciliation |
| `unavailable` | Отсутствует | Любая | Запрещён после ambiguous attempt |
| Любая | Не доказала outcome | Irreversible | Запрещён; terminal `effect_status_unknown` и ручное решение |

Registry отклоняет rule, если retry policy допускает путь, запрещённый этой матрицей.

## 18.5 Saga

Cross-transaction workflow объявляет compensation для каждого обратимого completed step.

Saga не обещает atomic rollback внешней системы. UI показывает partial/compensating state.

## 18.6 Cancellation

Cancellation:

- останавливает ещё не начатые steps;
- запрашивает отмену cancellable step;
- не скрывает уже committed/external effects;
- MAY инициировать compensation;
- завершается typed state `cancelled`, `partially_completed` или `compensation_failed`.

## 18.7 Restricted AI workflow

AI Level 4 использует только заранее зарегистрированный workflow с exact scope, budget, stop conditions и allowed capabilities. Model не конструирует новый executable state machine at runtime.

---

# 19. Preview и confirmation

## 19.1 Preview policy

```text
none
optional
required
required_for_sensitive_scope
required_for_irreversible
```

## 19.2 Preview semantics

Preview выполняет те же schema, permission, policy и domain checks, но не создаёт effect.

Preview возвращает:

- normalized intent summary;
- exact affected scope/count;
- expected revisions/snapshot;
- warnings;
- undo/irreversibility;
- estimated resource/external cost;
- redactions/exclusions;
- opaque preview token.

## 19.3 Preview token

Token связан с:

- capability ID/exact version;
- actor/origin;
- payload fingerprint;
- affected scope;
- expected revisions/snapshot;
- permission/policy generation;
- expiry;
- random nonce/signature.

Apply с stale token возвращает `PREVIEW_STALE` и требует новый preview.

## 19.4 Revalidation

Preview не резервирует state. Apply всегда повторно проверяет permissions, preconditions и current policy.

## 19.5 Confirmation levels

| Level | Применение |
|---|---|
| `none` | безопасная low-risk operation |
| `standard` | обычная user mutation |
| `explicit` | broad/sensitive effect |
| `danger` | difficult-to-reverse/external effect |
| `irreversible` | purge/key destruction и объективно необратимые actions |

## 19.6 Confirmation token

Confirmation выдаётся trusted UI/Core flow, а не моделью или document content.

AI MAY сформировать draft/preview, но не получает raw confirmation token как tool argument.

Token привязан к одному logical intent и atomically consumed при его принятии. Transport retry с тем же idempotency key получает прежний result; попытка применить token к другому key/payload/scope отклоняется.

---

# 20. Undo, compensation и irreversibility

## 20.1 Undo modes

```text
reversible
compensating
irreversible
```

## 20.2 Reversible

Descriptor указывает undo Command builder/target и preconditions.

Undo создаёт новую Command/revision/correction/head change и не удаляет history/audit.

## 20.3 Compensating

Descriptor объясняет:

- какой effect компенсируется;
- что останется наблюдаемым;
- возможные partial failures;
- idempotency compensation;
- user-visible terminal states.

## 20.4 Irreversible

Допускается только для:

- purge;
- cryptographic key destruction;
- external effect, который provider не позволяет отменить.

Irreversible capability:

- administrative/restricted;
- exact scoped;
- имеет required preview;
- confirmation level `irreversible`;
- недоступна generic AI tool;
- сохраняет minimal privacy-safe idempotency/audit receipt.

## 20.5 Undo invocation

Undo ссылается на original command receipt, но повторно проверяет current state. Если последующие revisions делают undo неоднозначным, возвращается `UNDO_CONFLICT`, а не destructive guess.

---

# 21. Idempotency

## 21.1 Identity

- `command_id` идентифицирует логическую Command;
- `idempotency_key` идентифицирует retry intent в declared scope;
- `request_id` идентифицирует transport attempt.

Они не взаимозаменяемы, хотя client MAY первоначально генерировать связанные значения.

## 21.2 Scope

Default idempotency scope:

```text
(verified actor, origin device, capability_id, major_version, idempotency_key)
```

Sync/external adapters MAY использовать явно объявленный origin-specific scope.

## 21.3 Fingerprint

Fingerprint включает:

- resolved exact capability version;
- canonical payload;
- expected revisions;
- effective stable options;
- relevant preview/confirmation binding.

Raw token bytes/secret values не включаются; используются safe handles/hashes согласно policy.

## 21.4 Duplicate behavior

Same key + same fingerprint:

- committed result возвращается без повторного effect;
- pending workflow возвращает тот же JobRef/status;
- deterministic terminal domain error MAY возвращаться повторно;
- unknown-effect state требует status reconciliation.

Current permissions/sensitivity policy повторно проверяются до возврата сохранённого result. Revocation не повторяет effect, но MAY привести к redacted status либо `PERMISSION_DENIED` вместо раскрытия прежнего sensitive output.

Same key + different fingerprint возвращает `IDEMPOTENCY_CONFLICT`.

## 21.5 Sealing outcome

Idempotency record становится terminal для:

- committed success/no-op;
- committed accepted workflow;
- deterministic domain/precondition failure после принятия intent, если contract это объявляет;
- confirmed irreversible effect receipt.

Transient transport failure до принятия intent не seals key.

Если Core не может определить, произошёл ли effect, он возвращает `EFFECT_STATUS_UNKNOWN`; caller MUST выполнить status Query, а не blind retry с новым key.

Первый принятый intent сохраняет resolved exact capability version и contract hash. Все повторы того же key сравниваются и обслуживаются относительно этой pinned version, даже если Registry позднее активировал более новый compatible minor.

## 21.6 Intentional repeat

Повторить пользовательское действие намеренно можно только с новым idempotency key.

## 21.7 Retention

Idempotency `OT` хранится как минимум весь replay/retry window и включается в backup, пока active. Для irreversible effects минимальный receipt может храниться дольше по ADR-008.

## 21.8 Queries/processors

Query не требует idempotency key, но request/cursor не расширяет authority.

Processor использует event ID/checkpoint; Export/Backup start являются Commands и используют обычную idempotency.

---

# 22. Error Contract

## 22.1 Error envelope

```yaml
code: StableErrorCode
category: validation | auth | permission | conflict | policy | resource | availability | integrity | external | internal
message_key: LocalizedMessageKey
safe_parameters_schema: SchemaRef | null
safe_parameters: SchemaBoundedValue | null
field_violations: [FieldViolation]
retry: never | same_request | after_refresh | after_delay | status_check_required
retry_after: duration | null
recovery_actions: [RecoveryAction]
details_schema: SchemaRef | null
details: SchemaBoundedValue | null
trace_id: TraceId
```

Consumer не парсит human-readable message для логики.

`safe_parameters` и `details` MUST быть schema-bound, конечными по размеру и пройти sensitivity/redaction validation. Если соответствующий `*_schema` равен `null`, value также MUST быть `null`. Untyped map/object и provider-native arbitrary error payload запрещены.

Retry semantics:

- `same_request` — тот же idempotency key/fingerprint;
- `after_delay` — тот же key, если intent/fingerprint не меняется;
- `after_refresh` — caller перечитывает state; изменение payload/preconditions создаёт новый intent и новый key;
- `status_check_required` — сначала `kernel.command.status`, blind retry запрещён;
- `never` — automated retry запрещён.

## 22.2 Global error codes

Минимальный набор:

| Code | Semantics |
|---|---|
| `INVALID_ARGUMENT` | Input не соответствует schema/domain constraints |
| `UNAUTHENTICATED` | Origin/credential не подтверждён |
| `PERMISSION_DENIED` | Effective grant запрещает operation |
| `NOT_FOUND` | Record/capability отсутствует либо скрыт policy |
| `CAPABILITY_UNAVAILABLE` | Module/dependency/platform unavailable |
| `UNSUPPORTED_VERSION` | Нет совместимой contract version |
| `PRECONDITION_FAILED` | Общая declared precondition не выполнена |
| `REVISION_CONFLICT` | expected revision/head устарел |
| `IDEMPOTENCY_CONFLICT` | Key повторён с другим fingerprint |
| `PREVIEW_REQUIRED` | Нужен preview |
| `PREVIEW_STALE` | Preview больше не соответствует state/policy |
| `CONFIRMATION_REQUIRED` | Нужен trusted confirmation |
| `UNDO_CONFLICT` | Undo неоднозначен из-за последующего state |
| `RESOURCE_EXHAUSTED` | Нарушен finite limit/budget |
| `DEADLINE_EXCEEDED` | Deadline истёк |
| `CANCELLED` | Request/workflow отменён в declared scope |
| `UNAVAILABLE` | Временная локальная/external dependency недоступна |
| `INTEGRITY_FAILURE` | Checksum/schema/history invariant нарушен |
| `EXTERNAL_FAILURE` | Typed provider/external failure |
| `EFFECT_STATUS_UNKNOWN` | Нельзя безопасно определить, был ли external effect |
| `INTERNAL` | Неожиданная implementation failure без leakage |

## 22.3 Domain errors

Module MAY добавлять namespaced codes, например `knowledge.note.TITLE_CONFLICT`, с schema, retry semantics и tests.

Новый domain error в compatible minor допустим только если старый client безопасно обработает его declared category/fallback.

## 22.4 Sensitive errors

Error не раскрывает:

- secret;
- existence restricted record;
- raw sensitive value;
- SQL/path/stack;
- provider credential;
- hidden policy details, позволяющие обход.

## 22.5 Batch errors

`per_item` batch возвращает bounded ordered sub-results с stable item key. Top-level status явно `partial`, если не все items успешны.

---

# 23. Versioning и compatibility

## 23.1 Semantic versioning

### Patch

- editorial/schema metadata fix без observable semantic change;
- более точная документация;
- implementation bug fix, возвращающий поведение к существующему contract.

### Minor

- новый optional input с прежним default behavior;
- новый optional output field;
- новый extensible enum value с declared fallback;
- новый capability consumer;
- более строгий internal validation, если ранее запрещённый input уже был contract-invalid.

### Major

- удаление/rename field;
- optional → required;
- изменение type/unit/meaning/default;
- изменение idempotency/transaction/undo semantics;
- расширение/сужение public effects, требующее client change;
- изменение error fallback несовместимо;
- изменение ordering/consistency;
- изменение authority model;
- изменение closed enum.

Изменение declared maximum scopes/actor kinds, требующее client/workflow adaptation, является major. Runtime effective policy MAY стать строже без contract bump, поскольку grant никогда не гарантируется descriptor; это фиксируется policy/audit и не расширяет authority.

## 23.2 Behavior compatibility

Одинаковый payload shape не делает meaning совместимым. Schema compatibility и semantic compatibility проверяются отдельно.

## 23.3 Negotiation

Client передаёт supported constraint, обычно exact major + minimum minor.

Core:

- выбирает highest supported compatible version;
- возвращает exact version;
- не пересекает major молча;
- MAY поддерживать несколько major versions через adapters/migrations;
- отклоняет unsupported constraint typed error.

## 23.4 Events

Event consumer pin-ит supported major и обязан игнорировать compatible optional fields. Producer не меняет meaning существующего event field.

## 23.5 Deprecation

Deprecation declaration содержит:

- announced_at/version;
- replacement capability;
- migration adapter/path;
- last supported release/date condition;
- impacted saved forms/layouts/workflows;
- telemetry/evidence без sensitive content;
- removal test.

Capability нельзя удалить, пока persisted layouts/forms/workflows ссылаются на неё без migration/fallback.

## 23.6 Contract drift

CI сравнивает descriptor/schema hash с released contract. Изменение без version bump блокирует build/module activation.

Generated clients строятся из exact contract bundle и проверяются contract tests.

## 23.7 Compatibility declaration

```yaml
compatibility:
  minimum_core_version: SemVer
  supported_contract_majors: [int]
  input_unknown_fields: reject
  output_unknown_fields: ignore_optional
  enum_policy: SchemaDefined
  adapters: [CompatibilityAdapterRef]
```

Compatibility adapter является versioned code, проходит те же permissions/data-classification tests и не может скрыто менять semantics.

---

# 24. Limits, scheduling и backpressure

## 24.1 Finite limits

Каждая invoked capability объявляет применимые finite:

- request bytes;
- output bytes;
- batch/items;
- rows/page;
- time range;
- execution deadline;
- memory class;
- concurrency;
- queue depth;
- retry count/backoff;
- network/token/financial cost;
- blob size/stream chunk.

`unbounded` запрещён.

## 24.2 Resource profiles

```text
interactive
background
bulk
administrative
```

Profile определяет scheduler queue, priority, default timeout и UI expectations, но не заменяет exact limits.

## 24.3 Backpressure

При насыщении система:

- ограничивает admission;
- возвращает `RESOURCE_EXHAUSTED`/retry metadata;
- не создаёт бесконечную очередь;
- не блокирует higher-priority integrity/backup work;
- не теряет already accepted durable workflow.

## 24.4 Streaming

Large query/export/blob transfer использует bounded stream с:

- chunk limits;
- cancellation;
- checksum/sequence;
- resumability, если declared;
- no hidden full buffering.

## 24.5 Deadlines

Deadline проверяется Core и передаётся cancellation token. Handler не обещает отменить already committed transaction.

Effective deadline равен наиболее раннему из client deadline, capability maximum и runtime policy deadline. Client не может увеличить declared execution budget.

## 24.6 Cost preview

Capability с external/token/financial cost объявляет estimate method, hard budget и behavior при неопределённости.

---

# 25. AI Tool exposure

## 25.1 Exposure levels

```text
none
read_only
proposal
confirmed_command
restricted_workflow
```

Descriptor `ai_exposure_max` задаёт абсолютный верхний предел и по умолчанию равен `none`. Tool Gateway policy выбирает effective exposure, который может быть только таким же или более узким.

## 25.2 Derived tool schema

AI tool schema строится из capability contract, но MAY только сужать:

- input fields;
- record/container scope;
- sensitivity ceiling;
- batch/time range;
- available enum values;
- output fields;
- cost;
- action mode.

Tool schema не расширяет base capability.

## 25.3 Removed fields

AI tool не получает:

- actor/grant;
- raw confirmation token;
- secret/raw credential;
- arbitrary path;
- hidden expected revision override;
- administrative flag;
- unrestricted extensions.

## 25.4 Read-only

AI read tool может вызывать только Query с effective outbound policy. Context Broker применяет source selection/redaction/preview.

## 25.5 Proposal

AI proposal tool создаёт `CE` proposal либо возвращает draft без target mutation. Apply является отдельной user/policy-authorized Command.

## 25.6 Confirmed command

Model формирует Command draft. Trusted UI/Core:

1. показывает preview;
2. получает confirmation;
3. inject-ит actor/confirmation context;
4. выполняет Command;
5. сохраняет AI origin + user confirmer.

## 25.7 Restricted workflow

Автономный workflow использует pre-approved exact capabilities, scopes, budget, stop conditions и expiry. Model не добавляет новые tools/steps за пределами registered state machine.

## 25.8 Prompt injection

Tool input/output и retrieved content являются data. Они не меняют:

- exposure level;
- permissions;
- confirmation;
- system policy;
- budget;
- capability version.

## 25.9 AI tool errors

Tool Gateway возвращает модели minimized typed error. Sensitive policy/record existence не раскрывается сверх разрешённого.

---

# 26. Observability, audit и provenance

## 26.1 Observability declaration

Capability указывает:

- trace spans;
- metrics;
- health signal;
- audit level;
- redaction policy;
- correlation fields;
- success/failure counters;
- latency/resource measurements.

## 26.2 Audit baseline

| Kind | Audit |
|---|---|
| Command | Обязательный `CA` receipt |
| Query | Metadata audit только для security/sensitive/outbound policy |
| Event | Delivery logs/checkpoints; не duplicate full audit по умолчанию |
| Processor | Job/run diagnostics; promotion Command audited отдельно |
| Widget | Нет content audit; actions/queries следуют своим contracts |
| Form | Submit Command audited; draft согласно class |
| Exporter | Scope/result/checksum `CA` receipt |

## 26.3 Content minimization

Logs/metrics/audit SHOULD использовать IDs, hashes, sizes, types и safe codes вместо raw content.

## 26.4 Provenance

Capability result содержит необходимое:

- source entity/revision IDs;
- query/definition/model versions;
- processor generation/freshness;
- origin/provider/tool refs;
- redactions;
- coverage/uncertainty.

Granularity объявляется contract и не может быть обещана UI постфактум без данных.

## 26.5 Correlation

Request, Command, Event, Job, external effect и Result связываются correlation/causation IDs без копирования body.

---

# 27. Testing и conformance

## 27.1 Descriptor validation

Автоматически проверяются:

- ID/version/hash uniqueness;
- schema references;
- kind-specific required fields;
- owner/module compatibility;
- Data Catalog accesses;
- permissions;
- finite limits;
- loop/technical purpose;
- error contract;
- AI exposure;
- deprecation references.

## 27.2 Contract tests

Каждая capability имеет:

- valid input success case;
- boundary/invalid inputs;
- typed error cases;
- permission matrix;
- sensitivity/redaction cases;
- limits/cancellation;
- unavailable dependency;
- compatibility fixtures;
- observability redaction test.

## 27.3 Command tests

- duplicate delivery property test;
- different payload/same key conflict;
- transaction rollback;
- audit/event/outbox atomicity;
- optimistic conflict;
- undo/compensation;
- preview/confirmation stale state;
- batch atomicity;
- no undeclared writes.

## 27.4 Query tests

- read-only enforcement;
- pagination stability;
- deterministic ordering;
- permission non-disclosure;
- freshness/provenance;
- bounded result;
- security audit policy.

## 27.5 Event/Processor tests

- at-least-once duplicate delivery;
- checkpoint crash recovery;
- rebuild equivalence;
- stale projection behavior;
- processor version change;
- canonical data unaffected by processor failure.

## 27.6 UI descriptor tests

- unknown/unavailable widget fallback;
- loading/empty/stale/error/unauthorized states;
- Form mapping schema safety;
- secret/file handling;
- accessibility contract;
- no direct mutation/query scope escalation.

## 27.7 Exporter tests

- complete required catalog coverage;
- original blobs/checksums;
- redaction/exclusion manifest;
- partial failure is not success;
- clean external readability;
- round-trip, если declared.

## 27.8 AI tests

- tool schema is subset of capability;
- prompt injection cannot expand scope;
- no secret/confirmation token;
- read-only cannot mutate;
- proposal cannot Apply;
- retry does not duplicate effect;
- budget/stop condition enforcement.

---

# 28. Reference contracts

Примеры проверяют выразительность и внутреннюю согласованность meta-contract, но являются сокращёнными descriptor excerpts: неуказанные common metadata/hash/observability fields должны присутствовать в реальном Registry bundle. Каждая показанная structure и value при этом type-correct; сокращение не разрешает shorthand другого типа. Exact product IDs/schemas остаются предварительными до module specifications.

## 28.1 Command example: revise note

```yaml
capability_id: knowledge.note.revise
version: 1.0.0
kind: command
owner_module: knowledge
status: active
input_schema: schema://knowledge/note-revise-input/1.0.0
output_schema: schema://knowledge/note-revise-result/1.0.0
error_contract: errors://knowledge/note-write/1.0.0

data_access:
  reads:
    - catalog_ref: knowledge.note.head
      class: CE
      purpose: optimistic concurrency
  writes:
    - catalog_ref: knowledge.note.revision
      class: CE
      operation: append_revision
      writer: command
      syncable: true
      outbox_required: true
      undo_behavior: reversible
  derived_outputs: []
  secret_handles: []
  external_effects: []

ai_exposure_max: confirmed_command

permissions:
  allowed_actor_kinds: [user, module, ai]
  read_scopes: [knowledge.note:read_target]
  write_scopes: [knowledge.note:revise_target]
  sensitivity_ceiling: P3
  max_batch: 1
  outbound_network: none
  secret_access: none
  administrative: false
  confirmation_floor: standard

command:
  transaction: required
  idempotency:
    required: true
  preconditions: [expected_note_revision]
  events_emitted:
    - id: knowledge.note.revised
      version_constraint: ^1.0
  workflow_started: null
  sync_outbox: required
  preview: optional
  confirmation: standard
  undo: reversible
  batch_atomicity: not_batch

availability:
  platforms: [desktop, mobile, cli]
  offline: full
  required_modules: [knowledge@^1.0]
  external_dependencies: []
  degraded_behavior: unavailable_when_knowledge_disabled

limits:
  request_bytes: 2000000
  output_bytes: 65536
  max_batch: 1
  deadline: 5s

loop_refs: [knowledge.note_edit_retrieval]
consumers:
  - consumer_id: desktop_editor
    kind: ui
    purpose: edit note content
    version_constraint: ^1.0
    required: true
    loop_ref: knowledge.note_edit_retrieval
  - consumer_id: mobile_editor
    kind: ui
    purpose: edit note content offline
    version_constraint: ^1.0
    required: true
    loop_ref: knowledge.note_edit_retrieval
  - consumer_id: knowledge_cli
    kind: cli
    purpose: scripted explicit note revision
    version_constraint: ^1.0
    required: false
    loop_ref: knowledge.note_edit_retrieval
  - consumer_id: ai_confirmed_draft
    kind: ai_gateway
    purpose: apply a user-confirmed note revision draft
    version_constraint: ^1.0
    required: false
    loop_ref: knowledge.note_edit_retrieval
acceptance_tests:
  - note_revise_success
  - note_revise_retry_idempotent
  - note_revise_revision_conflict
  - note_revise_ai_requires_confirmation
```

## 28.2 Query example: get note

```yaml
capability_id: knowledge.note.get
version: 1.0.0
kind: query
owner_module: knowledge
status: active
input_schema: schema://knowledge/note-get-input/1.0.0
output_schema: schema://knowledge/note-get-result/1.0.0
error_contract: errors://knowledge/note-read/1.0.0

data_access:
  reads:
    - catalog_ref: knowledge.note.current
      class: CE
      purpose: display/edit/export
  writes: []
  derived_outputs: []
  secret_handles: []
  external_effects: []

ai_exposure_max: read_only

query:
  consistency: canonical
  freshness: not_applicable
  pagination: none
  ordering: not_applicable
  snapshot: request
  provenance: item_level
  redaction: deny
  security_audit: metadata
  cache: local

permissions:
  allowed_actor_kinds: [user, module, ai]
  read_scopes: [knowledge.note:read_target]
  write_scopes: []
  sensitivity_ceiling: P3
  max_batch: 1
  outbound_network: none
  secret_access: none
  administrative: false
  confirmation_floor: none

availability:
  platforms: [desktop, mobile, cli]
  offline: full
  required_modules: [knowledge@^1.0]
  external_dependencies: []
  degraded_behavior: unavailable_when_knowledge_disabled
```

## 28.3 Other kinds

| Kind | Illustrative ID | Essential rule |
|---|---|---|
| Event | `knowledge.note.revised` | Minimal payload, atomic outbox, at-least-once |
| Processor | `knowledge.search.index_note` | `CE → DD`, versioned rebuild/checkpoint |
| Widget | `knowledge.note.editor_widget` | Query binding + declared revise action; no DB logic |
| Form | `documents.annotation.create_form` | Declarative mapping to typed Command |
| Exporter | `knowledge.markdown.exporter` | Required catalog coverage + manifest/checksums |

---

# 29. Baseline Kernel capabilities

Точные schemas будут приняты позднее, но следующие ограниченные surfaces зарезервированы как architectural baseline:

| Capability | Kind | Purpose |
|---|---|---|
| `kernel.capability.list` | Query | Filtered Registry discovery |
| `kernel.command.status` | Query | Reconcile idempotent/unknown command effect |
| `kernel.job.get` | Query | Read workflow/job progress |
| `kernel.job.cancel` | Command | Request bounded cancellation |
| `kernel.module.activate` | Administrative Command | Validated module activation |
| `kernel.module.disable` | Administrative Command | Safe disable without data deletion |
| `kernel.backup.start` | Command | Start backup workflow |
| `kernel.backup.get` | Query | Read backup status/result |
| `kernel.export.start` | Command | Start registered exporter workflow |
| `kernel.restore.preview` | Administrative Query | Validate/preview restore scope |
| `kernel.restore.apply` | Administrative Command | Apply confirmed staged restore |

Этот список не создаёт generic admin capability и не заменяет будущие detailed contracts.

---

# 30. Constitutional Conformance Matrix

| Инвариант | Capability mechanism |
|---|---|
| I1 | Command effects, Core Execution Context, Query read-only, writer validation |
| I2 | `CF` correction-only Command operations |
| I3 | `CE` append-revision/head/tombstone effects + expected revision |
| I4 | Processor outputs/rebuild/provenance contracts |
| I5 | Schema/semantic versions + immutable descriptor/hash |
| I6 | Finite capability kinds, first-class bounded Workflow Descriptor, Registry, no arbitrary operation/code/SQL |
| I7 | Loop/technical purpose + Data Catalog purpose per access |
| I8 | Consumers/outcomes/acceptance tests |
| I9 | Typed separate fields and schema semantics |
| I10 | Command envelope, idempotency, workflow version pinning, audit/events/outbox atomicity |
| I11 | Reversible/compensating/irreversible declarations |
| I12 | Availability/offline contract and external dependency isolation |
| I13 | AI exposure subset, Tool Gateway, no secret/confirmation/actor fields |
| I14 | Schema-bound raw/transformed/provenance contracts |
| I15 | Typed errors, failure states, limits, cancellation, local fallbacks |
| I16 | Exporter coverage/manifest/checksums/secret prohibition |

---

# 31. Зависимые решения

| Решение | Документ |
|---|---|
| Exact manifest serialization, workflow registration и module dependency schema | `MODULE-MANIFEST.md` |
| Safe Query DSL operators/type system | ADR-003 + отдельная specification |
| Local IPC wire encoding/auth/version negotiation | ADR-010 |
| Implementation/generation language toolchain | ADR-001 |
| External module signing/trust | ADR-007 |
| Exact retention idempotency/audit/events | ADR-008 |
| Data entity schemas и catalog IDs | Module specifications/Data Catalog |

Open encoding decision не разрешает arbitrary JSON, raw SQL или unversioned contracts.

---

# 32. Acceptance criteria

`CAPABILITY-CONTRACT.md` v0.1 готов к утверждению, если:

1. все семь capability kinds имеют отдельные исполнимые semantics;
2. common descriptor содержит owner, schemas, authority, data access, errors, limits, loops и tests;
3. client-controlled payload отделён от trusted Core Execution Context;
4. public type system исключает arbitrary JSON/path/secret;
5. Command pipeline определяет transaction, preconditions, idempotency, preview, confirmation и undo;
6. Query contract гарантирует read-only, pagination, freshness и provenance;
7. Event/Processor contracts выдерживают duplicate delivery и rebuild;
8. Widget/Form не содержат domain mutation logic;
9. Exporter обеспечивает classification-aware completeness;
10. external effects выполняются через durable workflow вне transaction;
11. versioning учитывает behavior, а не только schema shape;
12. AI tool может только сузить capability authority;
13. errors и resource limits typed/bounded;
14. reference patterns не противоречат common и kind-specific contracts;
15. Conformance Matrix покрывает I1-I16;
16. common fields не дублируются в kind-specific sections;
17. Workflow Descriptor однозначно определяет identity, OT writer, state machine, steps, effects и recovery;
18. ExternalEffectRule имеет полный outbound allowlist и безопасную retry matrix;
19. владелец проекта явно утверждает документ.

После утверждения следующий документ — `MODULE-MANIFEST.md`.
