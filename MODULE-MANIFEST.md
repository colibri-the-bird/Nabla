# Nabla Module Manifest v0.1

**Статус:** проект к утверждению  
**Дата:** 2026-07-11  
**Нормативная основа:** `CONSTITUTION.md` v0.1, `ARCHITECTURE.md` v0.1, `DATA-CLASSIFICATION.md` v0.1, `CAPABILITY-CONTRACT.md` v0.1  
**Следующий зависимый документ:** `LOOP-SPEC.md`

---

# 0. Назначение

Module является минимальной версионируемой единицей предметного владения, поставки и activation в Nabla.

Настоящий документ определяет:

- stable identity и version module;
- единственный нормативный Module Manifest;
- состав immutable contract bundle;
- ownership schemas, Data Catalog entries, capabilities, workflows, loops и migrations;
- dependency и compatibility model;
- maximum authority envelope;
- правила registration, activation, disable, upgrade и recovery;
- сохранность данных при отсутствии executable implementation;
- требования к export, backup, sync preparation, diagnostics и conformance;
- ограничения built-in modules v1 и будущих external modules.

Manifest не является списком пожеланий и не выдаёт полномочия сам по себе. Он представляет проверяемое утверждение о том, что module поставляет, чем владеет, от чего зависит и какие ограничения обязан соблюдать.

## 0.1 Нормативность

MUST, MUST NOT, SHOULD и MAY используются в смысле `CONSTITUTION.md`.

При расхождении действует следующий приоритет:

1. `CONSTITUTION.md`;
2. `ARCHITECTURE.md`;
3. `DATA-CLASSIFICATION.md` и `CAPABILITY-CONTRACT.md` в своих областях;
4. настоящий документ;
5. module specifications;
6. generated Registry representation и implementation.

Код, runtime Registry или package layout не становятся новым контрактом молча.

## 0.2 Не-цели

Документ не определяет:

- окончательный filesystem layout package;
- язык реализации module;
- executable plugin ABI;
- sandbox внешнего кода;
- signing/key infrastructure;
- окончательный JSON/YAML Schema dialect;
- fields предметных entities;
- DDL module tables;
- конкретные algorithms domain handlers/processors;
- точный набор product modules после v1.

Эти решения принимаются в ADR, module specifications и DDL, не ослабляя настоящий contract.

---

# 1. Инварианты module model

Для каждого production module выполняются следующие правила.

1. Module имеет один stable `module_id`, одного owner и одну active version в конкретной Registry generation.
2. Manifest конкретной version immutable.
3. Manifest является единственной точкой перечисления owned contract references; содержимое capability/workflow/catalog descriptors не копируется в него.
4. Каждый owned artifact имеет ровно одного owner module.
5. Необъявленный capability, workflow, schema, migration, processor binding или external adapter не активируется.
6. Module не получает DB connection, global permission, network listener или raw secret через manifest.
7. Effective authority всегда является пересечением declaration, verified runtime policy и actor/consumer grant.
8. Required dependency graph ацикличен и разрешается до migration/activation.
9. Activation атомарно публикует целую Registry generation; частично зарегистрированный module запрещён.
10. Disable/upgrade/removal executable implementation не удаляет canonical data.
11. Накопленные данные сохраняют schema, catalog, manifest и export metadata, необходимые для интерпретации.
12. Module failure не повреждает Kernel и unrelated modules.
13. Manifest не содержит executable code, arbitrary expressions, raw SQL, shell commands или provider prompts как authority.
14. v1 активирует только compile-time built-in modules, поставленные с доверенным application release.
15. Будущий external package не считается безопасным только потому, что имеет валидный manifest.

---

# 2. Основные понятия

## 2.1 Module

Версионируемая единица владения domain semantics и contracts, подключаемая к Kernel registries через публичные interfaces.

## 2.2 Module Manifest

Immutable language-neutral descriptor identity, compatibility, ownership, dependencies, authority ceiling, lifecycle и contract bundle module.

## 2.3 Contract Bundle

Замкнутый набор exact immutable descriptors и schemas, на которые ссылается manifest.

## 2.4 Implementation Bundle

Доверенные compiled bindings, migrations, renderers, resources и adapters, реализующие Contract Bundle. Implementation не изменяет public semantics descriptors.

## 2.5 Registry Generation

Согласованный immutable snapshot active modules, capabilities, workflows, schemas, scopes, loops и bindings.

## 2.6 Maintenance Surface

Минимальный ограниченный набор schemas, queries/exporters и migration metadata, сохраняемый для чтения, export или recovery данных inactive module.

## 2.7 Authority Envelope

Максимальный набор Kernel ports и effect categories, который module может использовать. Envelope является ceiling и validation summary, а не grant.

---

# 3. Identity, naming и version

## 3.1 Module ID

`module_id` имеет stable lowercase namespaced form:

```text
<namespace>[.<submodule>...]
```

Правила:

- 1–4 dot-separated segments;
- segment соответствует `[a-z][a-z0-9_-]*`;
- ID не содержит version, platform или implementation language;
- ID не зависит от UI display name;
- ID уникален во всём application release;
- первый segment совпадает с owner namespace public capabilities;
- `kernel` и `nabla.kernel` зарезервированы Kernel;
- rename создаёт новый module и требует explicit migration/deprecation path.

Baseline IDs v1:

```text
platform.shell
knowledge
documents
```

Kernel Services не маскируются под обычный domain module.

## 3.2 Version identity

Полная identity release module:

```text
(module_id, module_version, manifest_hash, artifact_set_hash, bundle_hash)
```

- `module_version` использует SemVer;
- `manifest_hash` обнаруживает изменение logical manifest;
- `artifact_set_hash` покрывает exact referenced descriptors/schemas/resources;
- `bundle_hash` связывает manifest и artifact set;
- одинаковые `module_id + module_version` MUST иметь одинаковые hashes.

## 3.3 Hash computation

1. Manifest canonicalized согласно общим canonical-encoding rules без fields `manifest_hash`, `artifact_set_hash` и `bundle_hash`.
2. `manifest_hash = H(canonical_manifest_without_hashes)`.
3. Artifact references сортируются по `(artifact_kind, stable_id, version, hash)`.
4. `artifact_set_hash = H(canonical_ordered_artifact_refs)`.
5. `bundle_hash = H(manifest_hash || artifact_set_hash)`.

Hash algorithm и version указываются в каждом `Hash`; bare digest запрещён.

## 3.4 Display metadata

Human-readable name, description, icon и localization MAY изменяться совместимым release, если stable IDs и semantics не меняются.

Display metadata не используется для dependency resolution, permissions, ownership или migration ordering.

---

# 4. Common Module Manifest

Логический meta-schema:

```yaml
manifest_schema_version: SemVer

module_id: ModuleId
module_version: SemVer
status: experimental | active | deprecated | disabled
owner: OwnerDeclaration
display: ModuleDisplayDeclaration

distribution: DistributionDeclaration
kernel_compatibility: KernelCompatibilityDeclaration
platform_support: PlatformSupportDeclaration

dependencies: [ModuleDependency]
optional_integrations: [OptionalIntegration]

contract_bundle: ContractBundleDeclaration
implementation_bundle: ImplementationBundleDeclaration
authority_envelope: ModuleAuthorityEnvelope
lifecycle: ModuleLifecycleDeclaration
data_survival: DataSurvivalDeclaration

conformance: ModuleConformanceDeclaration
acceptance_tests: [TestRef]
deprecation: ModuleDeprecationDeclaration | null

manifest_hash: Hash
artifact_set_hash: Hash
bundle_hash: Hash
```

Все lists присутствуют явно, даже если пусты. Unknown top-level field отклоняется, кроме versioned namespaced extension point, разрешённого manifest schema.

## 4.1 Owner declaration

```yaml
owner:
  owner_id: OwnerId
  namespace: string
  responsibility: string
  security_contact: ContactRef | null
  data_steward: OwnerId
```

`owner_id` является project ownership identity, а не runtime actor credential. Один module не имеет shared ownership.

## 4.2 Distribution declaration

```yaml
distribution:
  kind: built_in | first_party_package | external_package
  trust_tier: core_release | signed_trusted | restricted_external
  publisher_id: PublisherId
  package_format_version: SemVer
  signature: SignatureRef | null
  install_source_policy: InstallSourcePolicy
```

Для v1 допустимо только:

```text
kind = built_in
trust_tier = core_release
signature = null или release-signing metadata
```

`external_package` не активируется до ADR-007 и реализации installation/trust/sandbox boundary.

## 4.3 Kernel compatibility

```yaml
kernel_compatibility:
  minimum_kernel_version: SemVer
  maximum_kernel_version_exclusive: SemVer | null
  required_kernel_contracts: [KernelContractRef]
  forbidden_kernel_contracts: [KernelContractRef]
  manifest_schema_versions: [VersionConstraint]
```

Open upper bound допускается только если Kernel compatibility policy гарантирует соответствующий stable major contract. Unknown Kernel major не считается совместимым.

## 4.4 Platform support

```yaml
platform_support:
  portable_core: required | not_applicable_with_reason
  desktop: full | degraded | unavailable
  mobile: full | degraded | unavailable
  cli: full | degraded | unavailable
  degradation_contracts: [DegradationDeclaration]
  required_platform_services: [PlatformServiceRef]
```

Одинаковая capability version сохраняет domain semantics на всех declared platforms. Platform difference MAY ограничить availability, renderer или local adapter, но не изменить meaning команды.

Syncable domain module SHOULD иметь `portable_core: required`, даже если Mobile UI появится позднее.

---

# 5. Contract Bundle

## 5.1 Bundle declaration

```yaml
contract_bundle:
  schemas: [OwnedSchemaRef]
  catalog_entries: [OwnedCatalogRef]
  data_scopes: [OwnedDataScopeRef]
  capabilities: [OwnedCapabilityRef]
  workflows: [OwnedWorkflowRef]
  loops: [OwnedLoopRef]
  relation_types: [OwnedRelationTypeRef]
  migrations: [OwnedMigrationRef]
  renderer_descriptors: [OwnedRendererRef]
  search_sources: [OwnedSearchSourceRef]
  adapter_descriptors: [OwnedAdapterRef]
  compatibility_adapters: [OwnedCompatibilityAdapterRef]
```

Manifest перечисляет exact references, но не копирует descriptor bodies.

Каждый owned reference содержит минимум:

```yaml
id: StableArtifactId
version: SemVer
hash: Hash
owner_module: ModuleId
artifact_kind: ArtifactKind
```

`owner_module` MUST совпадать с `module_id`. Чужие artifacts указываются только через dependency/integration requirements.

## 5.2 Bundle closure

Contract Bundle является замкнутым, если:

- все SchemaRef разрешаются exact immutable schemas;
- все CatalogRef существуют и owned module;
- все DataScopeRef разрешаются;
- capability event/query/command refs разрешаются либо объявлены dependencies;
- workflow steps/effects/result queries разрешаются;
- loop refs разрешаются;
- relation endpoint types существуют;
- migration schema/catalog impacts разрешаются;
- renderer query/action refs существуют;
- adapter refs используются только declared external effects;
- compatibility adapters имеют exact source/target versions.

Unresolved optional reference не игнорируется: он должен находиться внутри explicit `OptionalIntegration` с declared degraded behavior.

## 5.3 One source of truth

Manifest MUST NOT inline или переопределять:

- capability data access, permissions, limits или consumers;
- workflow steps/effect rules;
- Data Catalog policies;
- Loop Descriptor fields;
- schema definitions;
- migration implementation;
- relation type semantics.

Manifest владеет membership и exact identity bundle. Соответствующий descriptor владеет semantics artifact.

## 5.4 Artifact kinds

Минимальные kinds:

```text
schema
catalog_entry
data_scope
capability
workflow
loop
relation_type
migration
renderer
search_source
adapter
compatibility_adapter
```

Новый kind требует совместимого manifest schema update либо Constitutional/architectural review, если расширяет власть runtime.

---

# 6. Schemas и ownership

## 6.1 Schema classes

Owned schema ref объявляет purpose:

```yaml
schema_id: SchemaId
version: SemVer
hash: Hash
purpose: public_contract | event_payload | workflow_state | catalog | export | storage | configuration | renderer_props
visibility: public | dependency_only | module_internal
compatibility: CompatibilityDeclaration
```

`module_internal` не разрешает обходить Data Catalog или migrations для persistent fields.

## 6.2 Ownership rules

Module владеет:

- своими domain entity/revision schemas;
- предметными Catalog entries;
- public capabilities и events своего namespace;
- domain processors/workflows;
- migrations собственных schemas;
- domain exporters;
- module-specific renderer descriptors.

Module MUST NOT объявлять ownership:

- Kernel command/audit/outbox/revision primitives;
- Secret Service storage;
- чужих entity types/tables;
- общих transport schemas;
- implementation чужого capability;
- Platform Shell global navigation semantics, если это domain module.

## 6.3 Shared schemas

Kernel shared primitive schema используется по exact `KernelContractRef`. Domain module не копирует primitive под новым ID ради обхода compatibility.

Shared domain concept либо имеет одного owner и public contract, либо остаётся отдельными concepts разных modules с explicit mapping. Shared ownership запрещён.

## 6.4 Namespace validation

Owned public IDs начинаются с module namespace, кроме явно зарегистрированного cross-namespace contribution point.

Contribution point:

- имеет owner;
- перечисляет допустимые artifact kinds;
- не передаёт ownership contributor;
- не позволяет подменить existing ID;
- проверяется при activation.

---

# 7. Data Catalog integration

## 7.1 Catalog coverage

Каждый module перечисляет exact `OwnedCatalogRef` для:

- каждого persistent record type;
- каждого persistent field;
- derived/device-local/operational stores;
- temporary sensitive files, если требуется Catalog entry;
- retained configuration;
- module audit/evidence types;
- workflow `OT` state;
- export artifacts retained in Nabla.

## 7.2 Activation checks

Module activation отклоняется, если:

- persistent schema не имеет Catalog coverage;
- catalog owner не совпадает;
- class/writer не соответствует capability/workflow effects;
- sensitivity/export/backup/sync/retention/purge/AI policy отсутствует;
- subject field не покрыт loop;
- service field не имеет technical purpose/consumer/retention;
- `DD` не имеет processor/rebuild proof;
- `OT` не имеет workflow/Kernel owner;
- `DL` объявлен global sync;
- `SE` включён в ordinary storage bundle.

## 7.3 No policy duplication

Manifest MAY содержать generated coverage summary, но он не является редактируемой policy.

Normative policies остаются в Data Catalog entries. Registry пересчитывает summary и отклоняет mismatch.

## 7.4 Data survival declaration

```yaml
data_survival:
  disable_behavior: preserve_all_canonical
  uninstall_behavior: block_while_canonical_present | archive_with_maintenance_surface
  unknown_version_behavior: read_only_or_reject
  maintenance_exporter: CapabilityRef | GenericExportProfileRef
  schema_metadata_retention: required
  catalog_metadata_retention: required
  purge_entrypoint: CommandRef | null
```

`uninstall_behavior` никогда не означает implicit delete. Purge остаётся отдельным administrative workflow.

---

# 8. Dependency model

## 8.1 Required dependency

```yaml
module_id: ModuleId
version_constraint: VersionConstraint
required_artifacts: [ArtifactRequirement]
reason: string
activation_behavior: block
data_dependency: none | public_contract_only
```

Required dependency означает, что module не активируется без совместимой active dependency.

## 8.2 Optional integration

```yaml
integration_id: IntegrationId
target_module: ModuleId
version_constraint: VersionConstraint
required_artifacts: [ArtifactRequirement]
enabled_by_default: boolean
degraded_behavior: string
capabilities_enabled: [CapabilityRef]
renderers_enabled: [RendererRef]
tests: [TestRef]
```

Отсутствие optional target не блокирует базовый module. Связанные capabilities/renderers не регистрируются либо возвращают declared unavailable state.

## 8.3 Dependency rules

1. Required dependency graph MUST быть DAG.
2. Optional integrations также не создают activation cycle.
3. Self-dependency запрещена.
4. Version constraint не использует floating `latest`.
5. Dependency декларирует необходимые public artifacts, а не internal package/class/table.
6. Module не получает право читать/писать dependency data из факта зависимости.
7. Cross-module write выполняется только public Command/composite workflow.
8. Cross-module read выполняется Query/versioned read model/declared analytics source.
9. Dependency removal блокируется при active dependants либо требует согласованный upgrade plan.
10. Optional integration не меняет semantics уже active capability version молча.

## 8.4 Resolution и lock

Manifest хранит version constraints. Build/release lock и runtime Registry generation фиксируют exact resolved:

```text
(module_id, module_version, bundle_hash)
```

Generated lock является производным release/Registry artifact и не редактируется независимо от manifests.

Resolution детерминирован:

1. Kernel compatibility;
2. exact installed candidates;
3. version constraints;
4. highest compatible version внутри allowed release set;
5. stable tie-breaker по bundle hash;
6. conflict → activation failure, не silent choice.

---

# 9. Authority Envelope

## 9.1 Declaration

```yaml
authority_envelope:
  kernel_ports: [KernelPortRef]
  data_scope_refs: [DataScopeRef]
  secret_purposes: [SecretPurpose]
  external_adapter_refs: [AdapterRef]
  administrative_entrypoints: [CapabilityRef]
  local_file_grants: none | staged_user_selected
  inbound_listener: none
  maximum_sensitivity: P0 | P1 | P2 | P3 | P4
```

Для обычного module `inbound_listener` MUST быть `none`. Sync transport принадлежит Kernel adapter boundary, а не domain module.

## 9.2 Computed authority

Registry вычисляет required authority как union exact declarations из:

- capabilities;
- workflows;
- processors;
- exporters;
- adapters;
- migrations;
- renderer actions.

Затем проверяется:

```text
computed required authority ⊆ manifest authority envelope
```

Для production module неиспользуемое broad authority также является defect: envelope SHOULD совпадать с computed union после нормализации. Wildcard scope запрещён.

## 9.3 Effective grant

Runtime authority:

```text
manifest envelope
∩ artifact descriptor maximum
∩ verified actor/consumer grant
∩ record/container policy
∩ sensitivity/outbound policy
∩ platform/runtime policy
```

Manifest никогда не расширяет более узкий artifact contract.

## 9.4 Kernel ports

Kernel port имеет stable ID/version и purpose. Минимальные categories:

- scoped transaction/read context;
- Command/Query registration;
- Workflow registration;
- Event/Outbox;
- Revision;
- Relation;
- Blob;
- Search source;
- Job/Processor;
- Audit;
- Policy;
- Export/Backup stream;
- Secret handle use;
- Platform renderer contribution.

Raw DB connection, arbitrary filesystem access, shell execution и global service reflection не являются Kernel ports.

## 9.5 Secrets и external access

- Manifest перечисляет только `SecretPurpose`, не secret handles/values.
- Adapter получает purpose-bound handle во время invocation.
- Network action существует только как `ExternalEffectRule` registered Workflow Descriptor.
- Local import использует scoped staged user-selected grant.
- Module не читает environment credentials напрямую.
- Provider SDK не становится transitive Kernel dependency.

---

# 10. Capabilities и workflows

## 10.1 Capability membership

Каждый `OwnedCapabilityRef`:

- exact version/hash;
- owner совпадает с module;
- ID находится в namespace;
- kind входит в закрытый набор Capability Contract;
- implementation binding существует для active executable capability;
- Data Catalog, scopes, loops, consumers и tests разрешаются;
- status совместим со status module.

Manifest не повторяет capability fields.

## 10.2 Workflow membership

Каждый `OwnedWorkflowRef`:

- exact version/hash;
- имеет entry Command этого или dependency module;
- state schema классифицирован `OT`;
- Kernel Workflow Service является state writer;
- все steps, external effects, compensation и result Query разрешаются;
- finite limits/terminal states/stop conditions существуют;
- pinned instance recovery поддерживается при upgrade/disable;
- AI exposure не превышает `restricted_workflow` и effective policy.

## 10.3 Cross-module composite Command

Manifest owner composite Command перечисляет dependencies на public contracts participants.

Internal mutation ports participants:

- имеют exact contract refs;
- доступны только Application composite coordinator;
- сохраняют permissions/validation владельца данных;
- не экспортируются UI/AI;
- не дают raw table access;
- покрыты joint integration tests.

## 10.4 Disabled contracts

После disable:

- новые ordinary invocations возвращают `CAPABILITY_UNAVAILABLE`;
- historical descriptors и hashes остаются доступны Registry maintenance path;
- running workflow следует pinned drain/cancel/recovery policy;
- maintenance exporter и status Query остаются доступны в restricted mode;
- Layout/Form refs сохраняются без destructive rewrite;
- reactivation той же совместимой version восстанавливает bindings.

---

# 11. Implementation Bundle и bindings

## 11.1 Declaration

```yaml
implementation_bundle:
  binding_set_id: BindingSetId
  binding_set_version: SemVer
  binding_set_hash: Hash
  capability_bindings: [CapabilityBinding]
  workflow_port_bindings: [WorkflowPortBinding]
  processor_bindings: [ProcessorBinding]
  migration_bindings: [MigrationBinding]
  renderer_bindings: [RendererBinding]
  adapter_bindings: [AdapterBinding]
  resources: [ResourceRef]
```

## 11.2 Binding rules

Binding связывает exact descriptor ref с compiled implementation ID.

Binding MUST NOT использовать:

- arbitrary class reflection по строке из user data;
- dynamic code download;
- script path;
- raw SQL declared в manifest;
- wildcard capability handler;
- fallback «обработать любой unknown action».

V1 binding table генерируется build system и проверяется compile-time/CI.

## 11.3 Contract drift

CI и startup validator сравнивают:

- implemented handler input/output с schema;
- declared effects с repository writes;
- emitted events;
- permissions/scopes;
- workflow ports;
- processor inputs/outputs;
- renderer query/actions;
- adapter actions;
- test fixtures.

Mismatch блокирует build либо module activation. Implementation не обновляет hash descriptors автоматически.

## 11.4 Resources

Localization, icons, static templates и help content:

- content-addressed или hash-covered;
- не исполняются как code;
- не предоставляют permissions;
- имеют size/type limits;
- malformed optional resource деградирует локально;
- required security/policy text failure блокирует соответствующую surface.

---

# 12. Migration Contract

## 12.1 Migration Descriptor

```yaml
migration_id: MigrationId
version: SemVer
hash: Hash
owner_module: ModuleId
from_schema_versions: [SchemaVersionRef]
to_schema_versions: [SchemaVersionRef]
depends_on: [MigrationRef]
affected_catalog_refs: [CatalogRef]
mode: online_read_compatible | exclusive
backup_precondition: none_with_reason | verified_backup | safe_copy
apply_binding: MigrationBindingRef
verification: [MigrationVerificationRef]
recovery_plan: RecoveryPlanRef
estimated_resources: ResourceLimits
acceptance_tests: [TestRef]
```

## 12.2 Migration rules

Migration:

- принадлежит owner schemas;
- имеет stable ID/checksum/hash;
- выполняется Kernel Migration Service под exclusive writer coordination, если требуется;
- не выполняет network/AI call;
- не обращается к UI;
- не читает/пишет чужие module tables напрямую;
- не понижает Data Classification молча;
- обновляет Catalog/schema references атомарно;
- сохраняет provenance и completion `CA`;
- имеет проверяемый recovery path;
- идемпотентно определяет already-applied state.

## 12.3 Ordering

Migration graph должен быть ацикличным и иметь один deterministic plan для текущего installed state.

Tie-breaker не заменяет missing dependency. Две migrations, порядок которых влияет на result, обязаны объявить edge.

## 12.4 Failure

При failure:

- current active Registry generation остаётся прежней;
- partially migrated staging/transaction откатывается либо переводится в explicit recovery state;
- module не активируется;
- dependants не активируются;
- unrelated modules остаются доступны, если canonical DB integrity подтверждена;
- UI получает typed diagnostic/recovery action;
- silent retry без recovery policy запрещён.

## 12.5 Downgrade

Automatic destructive downgrade запрещён.

Открытие older application release при future schema:

- read-only при доказанной совместимости;
- либо explicit rejection;
- никогда silent reverse migration.

---

# 13. Lifecycle и activation

## 13.1 Release status и runtime state

Manifest `status` описывает release intent. Runtime activation state хранится отдельно:

```text
discovered
→ integrity_verified
→ parsed
→ dependency_resolved
→ contracts_validated
→ migration_ready
→ activated
→ running
```

Дополнительные terminal/degraded states:

```text
blocked
incompatible
migration_failed
disabled
archived
quarantined
```

Runtime state является `DD/OT` согласно конкретному record purpose и не переписывает manifest.

## 13.2 Activation pipeline

Core выполняет:

1. package/source trust validation;
2. manifest schema parsing с limits;
3. identity/version/hash verification;
4. artifact-set closure verification;
5. Kernel/platform compatibility;
6. dependency resolution и DAG validation;
7. ownership/namespace uniqueness;
8. schemas/Catalog/scopes validation;
9. capabilities/workflows/loops validation;
10. authority envelope comparison;
11. binding integrity validation;
12. migration plan и backup/recovery preflight;
13. migrations;
14. post-migration integrity checks;
15. construction новой immutable Registry generation;
16. atomic generation publication;
17. start processors/jobs согласно policy;
18. activation `CA` evidence и health report.

Failure до шага 16 не публикует partial Registry.

## 13.3 Deterministic activation order

Modules упорядочиваются topologically по required dependencies. Внутри одного DAG level используется `module_id`, затем exact version/hash.

Порядок activation не используется как скрытый способ override. Duplicate ID/artifact остаётся conflict.

## 13.4 Disable

Disable workflow:

1. dependency impact preview;
2. запрет новых ordinary invocations;
3. drain/cancel running calls;
4. pinned workflow decision;
5. stop processors/subscriptions;
6. publish Registry generation без active contracts module;
7. сохранить maintenance surface;
8. проверить export/data readability;
9. записать evidence.

Disable не запускает purge и не удаляет blobs/revisions/catalog metadata.

## 13.5 Reactivation

Reactivation повторяет полный validation pipeline. Она не предполагает, что старые bindings, dependencies или policies всё ещё совместимы.

## 13.6 Archive/removal

Executable package MAY быть удалён только если:

- built-in release policy это допускает;
- active dependants отсутствуют;
- running workflows завершены/перенесены;
- maintenance surface материализован независимо;
- canonical data остаются интерпретируемыми/exportable;
- user получил preview последствий;
- removal evidence сохранён.

Canonical data physical removal выполняется только отдельным purge.

---

# 14. Upgrade и compatibility

## 14.1 Module SemVer

### Patch

- implementation bug fix к существующим contracts;
- resource/localization fix;
- новые test/evidence metadata;
- patch versions owned artifacts без observable incompatible change.

### Minor

- новые backward-compatible capabilities/workflows;
- optional integration;
- новые optional schema fields с fallback;
- новый renderer/platform support;
- compatible migration;
- deprecation announcement.

### Major

- incompatible public contract bundle;
- removal/rename owned artifact;
- changed ownership/namespace;
- incompatible storage/data semantics;
- required dependency change, ломающий installed consumers;
- changed disable/export guarantees;
- authority model change, требующий consumer/admin adaptation.

## 14.2 Artifact versions

Module version не заменяет versions capabilities/schemas/workflows. Release pin-ит exact artifact versions.

Изменение artifact без соответствующего module version/hash change запрещено.

## 14.3 Upgrade plan

Upgrade проверяет:

- old/new manifest diff;
- contract compatibility;
- dependency resolution;
- migrations;
- persisted layout/form/workflow refs;
- maintenance exporter;
- authority expansion;
- platform degradation;
- rollback/recovery.

Authority expansion, новый external adapter или administrative entrypoint требует explicit review и не маскируется patch release.

## 14.4 One active version

В одной workspace/Registry generation активна одна module version для одного `module_id`.

Несколько historical contract majors MAY обслуживаться compatibility adapters той же active module version. Две competing executable versions одного module одновременно не активируются в v1.

## 14.5 Deprecation

```yaml
deprecation:
  announced_in: SemVer
  replacement_module: ModuleRef | null
  replacement_artifacts: [ArtifactRef]
  migration_path: MigrationOrExportRef
  last_supported_release: ReleaseCondition
  persisted_reference_plan: string
  removal_tests: [TestRef]
```

Deprecation без data/reference migration path недействительна.

---

# 15. UI, Forms и renderers

## 15.1 Ownership split

- Module владеет Widget/Form descriptors и domain-specific renderer bindings.
- Kernel Capability Registry владеет авторитетным descriptor registry.
- Platform Shell владеет renderer host, composition и read-only client projection.
- Layout остаётся revisioned data и не владеет capability.

## 15.2 Renderer Descriptor

Renderer ref объявляет:

- descriptor ID/version/hash;
- supported Widget/Form refs;
- platforms;
- props/state schemas;
- accessibility contract;
- fallback;
- resource refs;
- implementation binding;
- no-direct-storage guarantee;
- acceptance tests.

## 15.3 Failure и unknown version

Unknown/incompatible renderer:

- не ломает layout;
- сохраняет instance data;
- показывает owner/version/unavailable state;
- предлагает disable/recovery/export path;
- не выполняет fallback mutation;
- не раскрывает sensitive cached content.

## 15.4 Cross-module composition

Split view/dashboard использует public Query/Command refs modules. Platform Shell не выполняет join чужих tables и не становится owner composed data.

---

# 16. Search, processors и jobs

## 16.1 Search Source Descriptor

```yaml
search_source_id: SearchSourceId
version: SemVer
hash: Hash
owner_module: ModuleId
input_catalog_refs: [CatalogRef]
serializer_schema: SchemaRef
processor_ref: CapabilityRef
output_index_schema: SchemaRef
sensitivity_inheritance: max_inputs | explicit_stricter
rebuild: RebuildRef
navigation_target_schema: SchemaRef
limits: ResourceLimits
```

Search output является `DD`. Search Service не получает ownership content.

## 16.2 Processor membership

Processor capability регистрируется только если:

- event/schedule/manual triggers существуют;
- inputs/outputs принадлежат declared Catalog refs;
- output только `DD/OR`;
- algorithm version/rebuild/checkpoint определены;
- duplicate delivery tests существуют;
- failure помечает projection stale, не повреждая canonical inputs;
- resources укладываются в module/runtime budgets.

## 16.3 Job isolation

Module job queue имеет bounded concurrency и failure domain. Saturation одного module не блокирует Kernel integrity, migration, restore или backup work.

---

# 17. Relations и cross-module data

## 17.1 Relation Type Descriptor

Manifest перечисляет exact relation type refs. Descriptor определяет:

- owner;
- endpoint type constraints;
- anchors;
- cardinality;
- revision/tombstone semantics;
- sensitivity inheritance самой relation;
- sync/export/delete behavior;
- query permissions;
- tests.

## 17.2 Endpoint ownership

Relation owner не получает ownership или implicit read/write permission endpoint content.

Cross-module relation требует dependency только на public entity/reference contract, а не на storage implementation.

## 17.3 Missing module

Если endpoint module inactive:

- stable reference сохраняется;
- relation не удаляется;
- generic export сохраняет IDs/type/version;
- UI показывает unresolved/inactive state;
- reactivation может восстановить navigation;
- backlink projection MAY быть stale/rebuilt.

---

# 18. Sync preparation

## 18.1 V1 requirements

Даже без network sync module, владеющий syncable canonical types, объявляет и проверяет:

- global offline IDs;
- revisions/parents/heads либо immutable fact identity;
- device/logical sequence integration;
- tombstone/correction semantics;
- transactional sync outbox requirement;
- versioned schemas/events;
- blob manifest behavior;
- deterministic conflict/merge hook refs, если применимо.

## 18.2 Sync summary

Manifest MAY включать generated sync coverage summary, но normative policy остаётся в Data Catalog и capability effects.

Summary mismatch блокирует activation/build.

## 18.3 Disabled module sync

Inactive module не выполняет domain merge code. Kernel MAY сохранять/передавать opaque versioned canonical records только если protocol и Catalog policy это безопасно поддерживают.

Unknown future schema не преобразуется и не признаётся валидным current state молча.

## 18.4 No custom transport

Domain module не открывает listener и не реализует собственный pairing/auth/replay protocol. Он предоставляет schemas, merge contracts и data hooks Kernel Sync boundary.

---

# 19. Export, backup и recovery

## 19.1 Export coverage

Для каждого canonical Catalog type manifest closure доказывает один из путей:

- module Exporter capability;
- documented Kernel generic fallback, сохраняющий raw versioned records;
- explicit redacted evidence export для `CA`;
- prohibited secret recovery path для `SE`.

Silent exclusion запрещён.

## 19.2 Required round-trip format

Module с пользовательскими `CF/CE/CR/CB` предоставляет минимум один machine-readable export format с:

- `round_trip: required`;
- stable IDs;
- schema/semantic versions;
- revisions/parents/heads;
- relations/anchors;
- original blob refs/checksums;
- provenance/units/timestamps;
- manifest/module version;
- validation fixtures.

Human-readable format MAY не поддерживать import.

## 19.3 Disable exporter

Maintenance exporter не запускает ordinary module processors/handlers без необходимости. Он работает через verified schemas/catalog metadata и restricted read path.

Generic fallback обязан честно сообщить о потере human-friendly semantics, но сохраняет raw machine-readable ownership data.

## 19.4 Backup

Backup set включает:

- exact active/historical module manifests, необходимые данным;
- module/schema/migration versions;
- catalog entries;
- canonical DB records;
- applicable blobs;
- workflow `OT`, если active;
- checksums;
- exclusions и required external recovery actions.

Implementation binaries MAY поставляться отдельно application release, но restore обязан определить совместимость до activation.

## 19.5 Restore

Restore:

1. проверяет bundle/schema availability;
2. сохраняет данные unknown/inactive module;
3. не запускает migration до staging/preflight;
4. активирует только compatible modules;
5. предоставляет maintenance export для остальных;
6. rebuild `DD` после canonical integrity;
7. фиксирует recovery report.

Missing executable module не превращает его canonical data в cache.

---

# 20. Security и trust

## 20.1 V1 built-in trust

V1 module code:

- compile-time linked/packaged с application release;
- проходит dependency/license/security review;
- не загружается из user workspace;
- не изменяется AI proposal;
- имеет build-pinned bundle hash;
- использует только declared Kernel ports.

Built-in trust не отменяет permissions, Data Catalog или failure boundaries.

## 20.2 Future external modules

До ADR-007 external module execution запрещено.

Будущее решение обязано определить:

- signature/publisher identity;
- installation consent;
- package integrity;
- sandbox/process boundary;
- filesystem/network/secret isolation;
- permission review;
- update/revocation;
- malicious module recovery;
- data ownership/export при удалении package.

Manifest validation без runtime isolation недостаточна.

## 20.3 Quarantine

Package переводится в `quarantined`, если:

- signature/hash mismatch;
- unexpected executable/resource;
- contract/binding drift;
- forbidden authority request;
- migration integrity failure;
- known revoked publisher/package.

Quarantine не удаляет user data. Maintenance surface загружается только из доверенного Kernel-compatible representation.

## 20.4 Supply-chain declaration

Implementation dependency set имеет lockfile/version pinning, license review, vulnerability/maintenance assessment и replacement strategy согласно Architecture dependency governance.

Transitive dependency считается частью risk surface module.

---

# 21. Reliability и diagnostics

## 21.1 Module health

Runtime health state содержит:

- active version/bundle hash;
- activation state;
- dependency status;
- migration status;
- capability/workflow availability;
- processor lag/failures;
- projection freshness;
- export coverage status;
- last conformance result;
- correlation IDs;
- safe recovery actions.

## 21.2 Failure isolation

- Invalid manifest блокирует module до migration.
- Dependency failure блокирует только dependants.
- Handler exception откатывает current transaction.
- Processor failure затрагивает declared projection chain.
- Renderer failure затрагивает component surface.
- Adapter failure переводит workflow в typed state.
- Migration failure не публикует новую Registry generation.
- Registry generation publication атомарна.

## 21.3 Diagnostics minimization

Diagnostics/logs не содержат raw domain content, secrets или full external payload по умолчанию.

Module ID/version/hash, artifact IDs, safe error codes, durations, sizes и trace IDs допускаются после sensitivity review.

## 21.4 Recovery actions

Typed recovery MAY включать:

- retry validation;
- install/activate compatible dependency;
- restore previous application release;
- resume/rollback migration recovery;
- disable optional integration;
- rebuild projection;
- export via maintenance surface;
- inspect corrupt artifact evidence.

Generic «force load» с отключёнными validators запрещён.

---

# 22. Testing и conformance

## 22.1 Static manifest validation

Автоматически проверяются:

- manifest schema;
- ID/version/hash integrity;
- namespace/owner uniqueness;
- artifact closure;
- dependency DAG;
- Kernel/platform compatibility;
- Data Catalog coverage;
- scope/authority envelope;
- capability/workflow/loop refs;
- migration graph;
- binding completeness;
- export coverage;
- conformance/test refs;
- forbidden external/runtime features.

## 22.2 Dependency tests

- compatible dependency activation;
- missing required dependency blocks;
- missing optional integration degrades locally;
- incompatible version blocks;
- dependency disable impact;
- no cycles;
- no internal package/table access.

## 22.3 Lifecycle tests

- clean activation;
- validation failure before migration;
- atomic Registry generation;
- disable with data preservation;
- reactivation;
- upgrade with migration;
- migration failure recovery;
- unknown future schema;
- running workflow during disable/upgrade;
- maintenance surface without ordinary module runtime.

## 22.4 Data tests

- every persistent field classified;
- writer/class match;
- derived delete-and-rebuild;
- OT recovery;
- canonical data unchanged by processor failure;
- disable/uninstall preserves data;
- purge isolated from lifecycle;
- relation endpoints retained;
- secret absent from ordinary stores.

## 22.5 Authority/security tests

- computed authority equals allowed envelope;
- wildcard/broad unused scope rejected;
- no raw DB/path/secret/network listener;
- external effect refs resolve exact workflow rules;
- P3/P4 outbound enforcement;
- malicious resource/manifest limits;
- contract-binding drift;
- prompt/content cannot alter manifest or grants.

## 22.6 Export/recovery tests

- required catalog coverage;
- machine-readable round-trip;
- original blobs/checksums;
- disabled-module maintenance export;
- backup restore on clean compatible installation;
- missing module data remains recoverable;
- partial export is typed failure/incomplete;
- manifest/schema versions retained.

## 22.7 Platform tests

- Desktop Core Service bindings;
- portable Core behavior для declared syncable domain;
- Mobile unavailable/degraded behavior до v2;
- CLI contract parity;
- renderer fallback;
- no platform-specific semantic mutation.

## 22.8 Failure-injection tests

- invalid hash;
- missing schema;
- handler crash;
- processor duplicate/crash;
- migration interruption;
- adapter timeout/unknown effect;
- registry publication failure;
- corrupt resource;
- dependency disappearance.

---

# 23. Baseline modules v1

## 23.1 Platform Shell

`platform.shell`:

- владеет navigation/composition surfaces;
- поставляет renderer host и client Registry projection;
- не владеет domain entities;
- не открывает DB;
- использует public Queries/Commands;
- сохраняет unknown widget/form instance data;
- деградирует при inactive domain module локально.

## 23.2 Knowledge

`knowledge`:

- владеет notes, revisions, spaces, collections, tags, properties, templates и saved-query definitions;
- публикует domain Commands/Queries/Events;
- регистрирует search sources/processors;
- экспортирует machine-readable round-trip и Markdown representation;
- использует Kernel Revision/Relation/Search ports по exact scopes;
- не получает Blob port без отдельного module-specific contract и authority review;
- не зависит от Documents internals.

## 23.3 Documents

`documents`:

- владеет documents, versions, annotations, bookmarks, active reader session
  state и checkpoints; completed session facts требуют отдельного active loop;
- использует Kernel Blob Service для original bytes;
- регистрирует parser/extraction processors и reader renderers;
- экспортирует original files, anchors и machine-readable metadata;
- использует generic relations для Knowledge links;
- не читает Knowledge tables.

## 23.4 Optional composition

Knowledge ↔ Documents composition реализуется через:

- public capabilities;
- generic relation contracts;
- optional Platform Shell renderers;
- explicit integration tests.

Required cyclic dependency между `knowledge` и `documents` запрещена.

## 23.5 Kernel не module

Command Bus, Query Bus, Workflow Registry, Revision, Audit, Event/Outbox, Blob, Relation, Policy, Migration и Backup/Recovery Services являются Kernel components.

Их release metadata MAY иметь отдельный Core Manifest, но они не используют domain Module Manifest для обхода запрета Kernel domain knowledge.

---

# 24. Reference manifest skeleton

Пример сокращён. `<hash>` и exact product refs заменяются реальными immutable values до activation; placeholder запрещён в production bundle.

```yaml
manifest_schema_version: 1.0.0

module_id: knowledge
module_version: 1.0.0
status: active

owner:
  owner_id: nabla.project
  namespace: knowledge
  responsibility: knowledge domain semantics and data portability
  security_contact: null
  data_steward: nabla.project

display:
  name: locale://modules/knowledge/name
  description: locale://modules/knowledge/description
  icon: resource://knowledge/icon

distribution:
  kind: built_in
  trust_tier: core_release
  publisher_id: nabla.project
  package_format_version: 1.0.0
  signature: null
  install_source_policy: application_release_only

kernel_compatibility:
  minimum_kernel_version: 1.0.0
  maximum_kernel_version_exclusive: 2.0.0
  required_kernel_contracts:
    - kernel.command@^1.0
    - kernel.query@^1.0
    - kernel.revision@^1.0
    - kernel.relation@^1.0
    - kernel.search@^1.0
  forbidden_kernel_contracts: []
  manifest_schema_versions: [^1.0]

platform_support:
  portable_core: required
  desktop: full
  mobile: degraded
  cli: full
  degradation_contracts:
    - platform: mobile
      behavior: unavailable_before_v2_host
  required_platform_services: []

dependencies: []
optional_integrations:
  - integration_id: knowledge.documents.links
    target_module: documents
    version_constraint: ^1.0
    required_artifacts:
      - relation-endpoint://documents/document-ref@1
    enabled_by_default: true
    degraded_behavior: document links remain unresolved but preserved
    capabilities_enabled: []
    renderers_enabled: [knowledge.document_link.preview@1.0.0]
    tests: [knowledge_documents_optional_integration]

contract_bundle:
  schemas:
    - {id: knowledge.note, version: 1.0.0, hash: "sha256:<hash>", owner_module: knowledge, artifact_kind: schema}
  catalog_entries:
    - {id: knowledge.note.revision, version: 1.0.0, hash: "sha256:<hash>", owner_module: knowledge, artifact_kind: catalog_entry}
  data_scopes:
    - {id: knowledge.note.read_target, version: 1.0.0, hash: "sha256:<hash>", owner_module: knowledge, artifact_kind: data_scope}
    - {id: knowledge.note.revise_target, version: 1.0.0, hash: "sha256:<hash>", owner_module: knowledge, artifact_kind: data_scope}
  capabilities:
    - {id: knowledge.note.revise, version: 1.0.0, hash: "sha256:<hash>", owner_module: knowledge, artifact_kind: capability}
    - {id: knowledge.note.get, version: 1.0.0, hash: "sha256:<hash>", owner_module: knowledge, artifact_kind: capability}
    - {id: knowledge.export.machine_readable, version: 1.0.0, hash: "sha256:<hash>", owner_module: knowledge, artifact_kind: capability}
  workflows: []
  loops:
    - {id: knowledge.note_edit_retrieval, version: 1.0.0, hash: "sha256:<hash>", owner_module: knowledge, artifact_kind: loop}
  relation_types: []
  migrations:
    - {id: knowledge.schema.initialize, version: 1.0.0, hash: "sha256:<hash>", owner_module: knowledge, artifact_kind: migration}
  renderer_descriptors:
    - {id: knowledge.note.editor, version: 1.0.0, hash: "sha256:<hash>", owner_module: knowledge, artifact_kind: renderer}
    - {id: knowledge.document_link.preview, version: 1.0.0, hash: "sha256:<hash>", owner_module: knowledge, artifact_kind: renderer}
  search_sources:
    - {id: knowledge.search.notes, version: 1.0.0, hash: "sha256:<hash>", owner_module: knowledge, artifact_kind: search_source}
  adapter_descriptors: []
  compatibility_adapters: []

authority_envelope:
  kernel_ports:
    - kernel.command.register@1
    - kernel.query.register@1
    - kernel.revision.scoped@1
    - kernel.relation.scoped@1
    - kernel.search.source@1
  data_scope_refs:
    - knowledge.note.read_target@1.0.0
    - knowledge.note.revise_target@1.0.0
  secret_purposes: []
  external_adapter_refs: []
  administrative_entrypoints: []
  local_file_grants: none
  inbound_listener: none
  maximum_sensitivity: P4

data_survival:
  disable_behavior: preserve_all_canonical
  uninstall_behavior: archive_with_maintenance_surface
  unknown_version_behavior: read_only_or_reject
  maintenance_exporter: knowledge.export.machine_readable@1.0.0
  schema_metadata_retention: required
  catalog_metadata_retention: required
  purge_entrypoint: null

conformance:
  constitution_matrix: conformance://knowledge/constitution@1
  architecture_matrix: conformance://knowledge/architecture@1
  data_catalog_validation: required
  capability_validation: required
  loop_validation: required

acceptance_tests:
  - knowledge_manifest_closure
  - knowledge_activation_atomic
  - knowledge_disable_preserves_data
  - knowledge_export_round_trip

deprecation: null

manifest_hash: "sha256:<hash>"
artifact_set_hash: "sha256:<hash>"
bundle_hash: "sha256:<hash>"
```

---

# 25. Constitutional Conformance Matrix

| Инвариант | Module-manifest mechanism |
|---|---|
| I1 | Scoped Kernel ports, declared capabilities/workflows, no raw DB/listener/path |
| I2 | Catalog/class ownership и `CF` effect validation |
| I3 | Revision schemas/services pinned в bundle; disable сохраняет history |
| I4 | Processor/search source descriptors, rebuild refs, `DD` validation |
| I5 | Module/artifact SemVer, hashes, compatibility и migrations |
| I6 | Finite artifact kinds, trusted v1 distribution, external code blocked до ADR-007 |
| I7 | Catalog/loop closure и activation validation |
| I8 | Consumers, acceptance tests и module purpose/owner |
| I9 | Exact schemas/catalog fields; manifest не объединяет raw/confidence semantics |
| I10 | Capability/workflow refs, Kernel-injected receipts/outbox, pinned Registry generation |
| I11 | Disable/archive отдельно от purge; data survival и maintenance surface |
| I12 | Platform/offline declarations, local Core ports, external adapter isolation |
| I13 | Authority envelope, AI exposure только через capability/workflow contracts |
| I14 | Catalog/provenance/schema closure и migration traceability |
| I15 | Atomic activation, dependency DAG, failure domains, migration recovery |
| I16 | Required round-trip exporter, maintenance fallback, manifest/schema/blob preservation |

---

# 26. Зависимые решения и открытые параметры

| Решение | Документ |
|---|---|
| Exact executable/package layout и build toolchain | ADR-001, ADR-007 |
| External signing, installation, sandbox и revocation | ADR-007 |
| Migration engine, state records и recovery implementation | ADR-012 |
| Global IDs/device sequence formats | ADR-009 |
| Exact module storage schemas | Module specifications + v1 DDL |
| Loop Descriptor и field/capability coverage algorithm | `LOOP-SPEC.md` |
| Knowledge artifact/catalog IDs | `KNOWLEDGE-MODULE.md` |
| Documents artifact/catalog IDs | `DOCUMENT-MODULE.md` |
| Backup maintenance bundle/container | `BACKUP-RECOVERY.md` |
| Exact manifest serialization dialect | ADR-001 или отдельная serialization specification |

Open parameter не разрешает:

- unknown manifest field;
- floating contract ref;
- unclassified persistent data;
- executable code из manifest;
- external module activation;
- raw DB/network/secret authority;
- removal данных при disable;
- partial Registry publication.

---

# 27. Acceptance criteria

`MODULE-MANIFEST.md` v0.1 готов к утверждению, если:

1. module identity/version/hash однозначны и не зависят от UI/package path;
2. Manifest имеет один normative source и не дублирует artifact semantics;
3. Contract Bundle closure разрешается детерминированно;
4. каждый artifact имеет одного owner и exact version/hash;
5. required/optional dependencies не создают cycles или скрытый storage access;
6. authority envelope является проверяемым ceiling, а не grant;
7. capabilities и workflows регистрируются только exact references;
8. workflow `OT` writer и external effects остаются Kernel-controlled;
9. migration graph, preflight и recovery определены;
10. activation публикует Registry generation атомарно;
11. disable/archive/removal сохраняют canonical data и maintenance export;
12. v1 допускает только compile-time built-in module code;
13. future external execution заблокировано до ADR-007;
14. platform support не меняет domain semantics;
15. search/processors/renderers/adapters имеют отдельные bounded contracts;
16. каждый canonical type имеет export/backup/recovery path;
17. baseline boundaries Platform Shell, Knowledge и Documents не образуют cycles;
18. automated conformance покрывает lifecycle, authority, migration, export и failure isolation;
19. Conformance Matrix покрывает I1-I16;
20. владелец проекта явно утверждает документ.

После утверждения следующий нормативный документ — `LOOP-SPEC.md`.
