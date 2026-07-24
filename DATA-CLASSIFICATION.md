# Nabla Data Classification v0.1

**Статус:** проект к утверждению  
**Дата:** 2026-07-11  
**Нормативная основа:** `CONSTITUTION.md` v0.1, `ARCHITECTURE.md` v0.1  
**Следующий зависимый документ:** `CAPABILITY-CONTRACT.md`

---

# 0. Назначение

Этот документ определяет, как Nabla классифицирует любую сохраняемую информацию до проектирования DDL, sync, export, backup и AI access.

Классификация отвечает не только на вопрос «canonical это или derived». Для каждого record type и field она определяет:

- основной класс состояния;
- источник истины и допустимого writer;
- mutability/correction model;
- sensitivity;
- sync policy;
- export policy;
- backup policy;
- retention и deletion mode;
- purge behavior;
- outbound AI policy;
- provenance;
- loop либо техническое обоснование.

Цель — исключить следующие ошибки:

- потерю пользовательских данных из-за ошибочной маркировки как cache;
- синхронизацию device-local state;
- превращение derived model output в source of truth;
- попадание secrets в DB, logs, backup или AI context;
- бессрочный сбор данных без consumer;
- неоднозначное удаление audit, revisions и tombstones;
- невозможность независимого export;
- смешение raw result, confidence и transformed value.

---

# 1. Область действия

Классификация обязательна для:

- canonical DB;
- module-owned tables;
- blob stores;
- derived indexes и caches;
- device-local stores;
- job/outbox/inbox state;
- logs, diagnostics и audit;
- secret stores;
- backup/export manifests;
- persistent AI context, transcripts и proposals;
- temporary files, если они переживают process boundary или содержат чувствительные данные.

Чисто transient значение в памяти MAY не иметь записи в Data Catalog, но sensitivity и outbound policy всё равно применяются к нему при передаче между trust boundaries.

## 1.1 Единица классификации

Классификация выполняется на трёх уровнях:

1. **Record type** — основной класс и default policies.
2. **Field** — уточнение sensitivity, semantics, retention и outbound behavior.
3. **Record instance** — унаследованные или явно повышенные ограничения конкретного объекта.

Каждый record type и каждое persistent field MUST иметь ровно один основной state class.

Sensitivity, sync, export, backup, retention и AI policy являются независимыми измерениями и не заменяют основной класс.

## 1.2 Mixed records

Таблица MAY содержать records разных classes только если это явно поддержано schema discriminator и отдельными policy paths. По умолчанию это запрещено.

Record MAY содержать structural metadata другого назначения, например checksum или schema version. Такое поле наследует класс record, если не имеет самостоятельного lifecycle или consumer.

Если поле требует отдельного writer, retention, sync или purge behavior, оно MUST быть вынесено в отдельный record type либо получить отдельную field classification.

## 1.3 Fail-closed default

Неизвестная или отсутствующая классификация обрабатывается следующим образом:

- новый persistent schema не активируется;
- outbound AI запрещён;
- обычный sync запрещён;
- export помечает ошибку полноты;
- sensitivity считается не ниже `P3 Restricted`;
- deletion/purge не выполняется автоматически;
- legacy data доступна read-only до классификации, если это безопасно.

`unclassified` не является допустимым production class.

---

# 2. Classification Descriptor

Data Catalog entry для record type или field содержит как минимум:

```text
catalog_id
owner_module
schema_id
schema_version
record_type
field_path
description
primary_state_class
source_of_truth
allowed_writers
mutability_model
origin_kinds
sensitivity_default
sensitivity_inheritance
sync_policy
presence_policy
export_policy
backup_policy
retention_policy
deletion_mode
purge_behavior
outbound_ai_policy
encryption_requirement
declassification_policy
loop_id_or_technical_purpose
provenance_requirements
semantic_definition
validation_rules
consumers
conformance_tests
```

## 2.1 Type-level и field-level policy

Field наследует type policy, если не объявлено более строгое правило.

Field MAY повышать sensitivity или ограничивать sync/export/AI, но MUST NOT ослаблять type/container policy без явного declassification workflow.

## 2.2 Effective policy

Во время query, sync, export, backup или AI context строится effective policy:

```text
effective policy = most restrictive of:
  schema default
  field override
  record override
  parent/container policy
  relation endpoint policy, only when the operation exposes a relation or endpoint-associated projection
  operation policy
  destination/provider policy
```

Конфликт policies разрешается в сторону меньших полномочий и меньшего раскрытия.

---

# 3. Основные классы состояния

| Код | Класс | Source of truth | Обычная мутация | Типичный writer |
|---|---|---|---|---|
| `CF` | Canonical Fact | Да | Append + correction fact | Command handler |
| `CE` | Canonical Revisioned Entity | Да | New revision/head/tombstone | Command handler |
| `CR` | Canonical Relation | Да | Relation fact/revision/tombstone | Command handler |
| `CB` | Canonical Blob | Да | Immutable adoption + reference changes | Blob Service + Command |
| `CA` | Canonical Audit/Evidence | Да | Append-only, privacy-aware retention | Audit/Evidence Service |
| `DD` | Derived Data | Нет | Rebuild/replace | Registered processor |
| `OT` | Operational Transaction-Critical | Нет, но необходимо для корректности workflow | State machine/receipt | Kernel Service |
| `OR` | Operational Re-creatable | Нет | Replace/reset | Kernel Service |
| `DL` | Device-Local | Нет | Local update/reset | Local State Service |
| `SE` | Secret | Нет | Create/rotate/revoke | Secret Service |

Основной класс описывает смысл и lifecycle, а не физический формат. Бинарный derived model artifact остаётся `DD`, а не становится `CB` только потому, что хранится файлом.

---

# 4. Профили основных классов

## 4.1 `CF` — Canonical Fact

### Определение

Невосстановимое наблюдение о произошедшем событии, действии, результате или измерении.

### Примеры

- reading session, только если её history имеет active domain loop/consumer;
- learning attempt;
- evaluation;
- review observation;
- import event;
- intervention;
- measurement;
- AI evaluation result, если он используется как историческое наблюдение;
- independently actionable integrity/recovery finding discovered during verification.

### Правила

- создаётся только Command;
- не обновляется in place;
- correction создаётся новым `CF` с `correction.supersedes_id = original.id`;
- raw value хранится отдельно от confidence/quality;
- schema/semantic version обязательна;
- producer, consumer и loop обязательны;
- ordinary delete и generic tombstone запрещены; invalidation выполняется новым correction `CF`, пользовательское скрытие — отдельной `CE/CR` policy, физическое уничтожение — только purge;
- sync по global ID выполняется как union;
- payload mismatch одного ID является integrity conflict.

### Policy baseline

| Измерение | Default |
|---|---|
| Sync | `SYNC_GLOBAL` для syncable domain facts |
| Export | `EXPORT_REQUIRED` |
| Backup | `BACKUP_REQUIRED` |
| Retention | `RET_USER_OR_POLICY` |
| Delete | Correction/invalidation fact; physical only by purge |
| AI | По sensitivity/container policy |

## 4.2 `CE` — Canonical Revisioned Entity

### Определение

Пользовательски изменяемый объект со stable identity, immutable revisions и head set.

### Состав

- entity shell;
- immutable revision;
- parent edges;
- head/head set;
- archive/delete tombstone.

Все эти records относятся к `CE`, хотя имеют разные технические роли.

### Примеры

- note;
- layout;
- collection;
- template;
- saved query;
- objective;
- concept;
- task definition;
- metric definition;
- module configuration;
- policy definition;
- annotation;
- bookmark;
- AI proposal.

### Правила

- content меняется только новой revision;
- head update и revision insert происходят одной Command transaction;
- expected revision используется для optimistic concurrency;
- concurrent heads не разрешаются silent LWW;
- delete создаёт tombstone/archive revision;
- export включает stable ID, current content и необходимую semantic metadata;
- machine-readable export MUST включать revision graph и stable parent/head semantics; человекочитаемое представление MAY по умолчанию показывать только current content.

### Policy baseline

| Измерение | Default |
|---|---|
| Sync | `SYNC_GLOBAL` для syncable entities |
| Export | `EXPORT_REQUIRED` |
| Backup | `BACKUP_REQUIRED` |
| Retention | `RET_USER_OR_POLICY` |
| Delete | Revision/tombstone; physical only by purge |
| AI | По effective outbound policy |

## 4.3 `CR` — Canonical Relation

### Определение

Типизированная невосстановимая связь между stable identities либо между identity и stable anchor.

### Примеры

- collection membership;
- note references document span;
- annotation supports note;
- task tests concept;
- concept prerequisite;
- tag assignment;
- semantic link между notes.

### Правила

- relation type и version обязательны;
- endpoints используют stable IDs, а не titles/paths;
- relation existence может быть чувствительнее собственных metadata;
- effective sensitivity не ниже наиболее чувствительного endpoint;
- backlink index является `DD`;
- relation delete использует tombstone или revisioned relation semantics;
- relation не даёт module права читать content endpoint без query permission.

### Inline Markdown links

Для inline link существуют две связанные canonical части:

1. человекочитаемый token/anchor внутри Note Revision (`CE`);
2. stable resolved edge (`CR`).

Они commit атомарно как один note workflow. Несоответствие является integrity defect.

Если target ещё не разрешён, создаётся unresolved link representation с исходным token. Позднее resolution создаёт/обновляет `CR`, не переписывая старую Note Revision.

## 4.4 `CB` — Canonical Blob

### Определение

Невосстановимое пользовательское бинарное содержание, идентифицированное content hash.

### Примеры

- original PDF;
- image attachment;
- user-imported file;
- вручную сохранённый artifact;
- original scan/audio, если поддерживается module.

### Правила

- bytes immutable по hash;
- adoption проходит staging/checksum/final-path/Command flow;
- domain entity ссылается на blob identity, но не совпадает с ним;
- global identity/metadata могут sync без bytes;
- local presence является `DL`;
- derived thumbnail/OCR/model artifact является `DD`, а не `CB`;
- export сохраняет original bytes и checksum;
- backup включает bytes согласно presence и backup policy;
- GC учитывает references, retention, backup и sync.

## 4.5 `CA` — Canonical Audit/Evidence

### Определение

Невосстановимое доказательство того, кто, когда, через какой policy boundary и с каким результатом выполнил значимое действие.

### Примеры

- command receipt;
- security-relevant read record;
- AI tool-call audit;
- purge receipt;
- device pairing/revocation evidence;
- migration completion record;
- restore/backup verification record;
- external-effect execution receipt.

### Правила

- append-only;
- создаётся только Audit/Evidence Service либо специализированным Kernel workflow;
- не дублирует full sensitive content без необходимости;
- secrets запрещены;
- sensitivity наследуется от target/action, но body минимизируется;
- обычный portable export не обязан включать полный audit;
- отдельный audit export может быть redacted;
- retention определяется ADR-008;
- purge оставляет минимальный privacy-safe receipt, если он необходим для идемпотентности или доказательства завершения.

### Не относится к `CA`

- idempotency lookup state — `OT`;
- pending outbox — `OT`;
- debug log — `OR`;
- domain observation пользователя — `CF`.

## 4.6 `DD` — Derived Data

### Определение

Данные, полностью воспроизводимые из canonical inputs, versioned definition и processor/model version.

### Примеры

- full-text index;
- backlinks;
- extracted PDF text;
- OCR output;
- thumbnail;
- latest reading position projection;
- analytics aggregate;
- metric value;
- memory state;
- scheduler recommendation;
- embedding;
- model artifact, если он воспроизводим;
- dashboard cache.

### Правила

- имеет input provenance/cursor;
- имеет definition и processor version;
- rebuild test обязателен;
- не является единственным export/sync source;
- MAY удаляться и заменяться;
- sensitivity не ниже максимальной sensitivity inputs;
- stale/freshness metadata показывается, когда влияет на решение;
- изменение model не меняет canonical observations.

### Невоспроизводимый внешний результат

Если результат невозможно воспроизвести и его история важна, он не маскируется под `DD`: предметное наблюдение классифицируется `CF`, а доказательство выполнения workflow — `CA`. Конкретный record type выбирает ровно один из них.

## 4.7 `OT` — Operational Transaction-Critical

### Определение

Служебное состояние, которое не является пользовательским source of truth, но необходимо для идемпотентности, causal progress или корректного завершения durable workflow.

### Примеры

- idempotency records;
- command deduplication index;
- transactional outbox;
- sync inbox/deduplication receipts;
- device sequence;
- durable job/workflow state;
- migration progress;
- restore checkpoint;
- external-effect intent state.

### Правила

- writer — только Kernel Service;
- создаётся атомарно с соответствующей canonical mutation, где требуется;
- retention покрывает максимальное retry/replay window;
- не попадает в ordinary export;
- backup включается, если потеря нарушит recovery или повторную доставку;
- purge не должен позволять повтору уже завершённого необратимого effect;
- transport metadata минимизирует content.

## 4.8 `OR` — Operational Re-creatable

### Определение

Служебное состояние, потеря которого не меняет canonical history и не нарушает exactly-once observable effect.

### Примеры

- temporary leases;
- transient retry counters, если их reset безопасен;
- diagnostics buffers;
- parser scratch state;
- download staging metadata до canonical adoption;
- non-durable performance cache;
- health snapshots.

### Правила

- может очищаться при restart/recovery;
- не sync/export;
- backup не требуется;
- имеет короткий retention или cleanup trigger;
- чувствительные временные bytes удаляются после success/failure;
- если потеря state способна повторить внешний effect, state ошибочно классифицирован и должен стать `OT`.

## 4.9 `DL` — Device-Local

### Определение

Состояние, смысл которого относится только к конкретному device/application installation.

### Примеры

- window geometry;
- last open panel;
- local filesystem path;
- blob presence;
- download progress;
- live reading cursor;
- unsaved editor draft, если product policy допускает его потерю;
- local cache preference;
- platform notification state.

### Правила

- не sync как global record;
- не ordinary export;
- не должно быть единственным местом пользовательского content;
- reset не меняет canonical history;
- local path не используется как entity identity;
- чувствительные drafts получают sensitivity и cleanup policy, несмотря на `DL`.

Если пользователь ожидает восстановление state на другом device или как глобальное состояние после reinstall, это не `DL`: изменяемое пользовательское состояние классифицируется `CE`, а наблюдение/checkpoint — `CF`. Локальный restore MAY восстановить `DL` как удобство, но не превращает его в глобальную истину.

## 4.10 `SE` — Secret

### Определение

Значение, раскрытие которого предоставляет authority либо раскрывает cryptographic material.

### Примеры

- OAuth refresh/access token;
- API key;
- encryption key;
- device private key;
- local IPC credential;
- recovery secret;
- password.

### Правила

- хранится только Secret Service/OS-backed store;
- DB хранит только opaque handle и non-secret metadata;
- не попадает в logs, audit body, ordinary export/backup/sync/AI;
- доступ выдаётся минимальному adapter по handle;
- поддерживаются rotation/revocation;
- recovery определяется ADR-005 и provider-specific policy;
- отсутствие secret после restore должно приводить к re-auth/recovery flow, а не к повреждению canonical data.

### Secrets внутри unstructured content

Structured credential/key/token fields MUST использовать `SE` и opaque handle.

Nabla не может гарантированно распознать любой secret, случайно вставленный пользователем в произвольный Note/PDF/text blob. Такое unstructured content сохраняет свой основной класс (`CE/CB`), но при explicit marking или high-confidence detection получает `P4`, блокируется для AI и вызывает предложение переместить credential в Secret Service.

Detection не даёт права молча удалить или преобразовать пользовательский текст. Система не использует credential из unstructured content как authority без отдельного explicit import в Secret Service.

---

# 5. Процедура выбора основного класса

Классификация выполняется как закрытое decision tree. Физическое размещение само по себе не определяет class: локально сохранённый full-text index остаётся `DD`, а синхронизируемое device trust decision не становится `DL`.

## Шаг 1. Предоставляет ли значение authority?

Если значение позволяет аутентифицироваться, расшифровать данные или действовать от имени пользователя, это `SE`. Structured authority value не рассматривается в следующих шагах.

## Шаг 2. Несёт ли значение самостоятельную canonical information?

Значение является canonical, если без него пользователь потеряет исходное содержание, решение, наблюдение, историю, связь или доказательство, которые нельзя однозначно восстановить из других canonical records.

- если **нет**, применяется non-canonical branch, шаги 3–6;
- если **да**, применяется canonical branch, шаги 7–11.

## Шаг 3. Нужно ли non-canonical значение для корректности durable workflow?

Если потеря вызывает duplicate external effect, replay, нарушение migration/restore, повтор committed intent либо невозможность безопасно продолжить workflow, это `OT`.

Workflow correctness имеет приоритет над rebuildability и device locality.

## Шаг 4. Является ли значение semantic transformation?

Если значение однозначно воспроизводится из exact canonical inputs, versioned definition, processor/model version и explicit parameters/seed, это `DD`.

То, что representation строится отдельно на каждом device, не делает его `DL`.

## Шаг 5. Имеет ли значение собственно device-specific semantics?

Если значение описывает конкретную installation/device: UI geometry, local presence, local path, live cursor или platform state — это `DL`.

Критерий — локальный смысл, а не просто локальное хранение или отсутствие sync.

## Шаг 6. Является ли значение иным безопасно сбрасываемым service state?

Если значение не несёт model semantics, не относится к одному device как пользовательское состояние и имеет доказуемый safe reset/cleanup path, это `OR`.

Если ни `OT`, ни `DD`, ни `DL`, ни `OR` не доказаны, schema не активируется.

## Шаг 7. Является ли canonical значение evidence выполнения boundary action?

Если основной смысл record — доказать actor, policy, scope и result команды, security operation, migration, backup/restore или external effect, это `CA`.

Предметный результат того же действия MAY дополнительно создать отдельный `CF`, но один record type не классифицируется одновременно как `CA` и `CF`.

## Шаг 8. Является ли значение независимой typed связью?

Если canonical meaning состоит в существовании/versioned state связи между stable endpoints или anchor, это `CR`, даже если relation имеет собственный stable ID и revisions.

## Шаг 9. Является ли значение оригинальными binary bytes?

Если canonical meaning — пользовательские или невосстановимые bytes, адресуемые content hash, это `CB`. Domain entity и references классифицируются отдельно.

## Шаг 10. Имеет ли объект stable identity и пользовательски изменяемое состояние?

Если да, это `CE`. Изменяемость означает новые immutable revisions, а не in-place update.

## Шаг 11. Является ли значение невосстановимым наблюдением?

Если оно фиксирует произошедший предметный результат, измерение или действие и не является evidence boundary из шага 7, это `CF`.

## Шаг 12. Проверка единственности и потери

Для выбранного class проверяются два условия:

1. Если удалить все records этого типа и оставить остальные classes, ожидаемая потеря соответствует заявленному canonical/non-canonical branch.
2. Ни один другой class не подходит без нарушения его writer, mutability, rebuild, retention или consumer semantics.

Если остаются два допустимых class, catalog entry отклоняется до разделения record type по независимым lifecycle. `primary_state_class` никогда не выбирается по удобству текущего DDL.

---

# 6. Sensitivity classification

Sensitivity является независимой от primary state class.

| Код | Уровень | Примеры | Default cloud AI |
|---|---|---|---|
| `P0` | Public | опубликованный материал, публичная справка | Allowed по policy |
| `P1` | Personal | обычные настройки, непубличные названия, низкорисковые metadata | Ask/allowed by container |
| `P2` | Sensitive | private notes, learning performance, переписка, unpublished work | Ask + preview |
| `P3` | Restricted | health, biometrics, finance, identity docs, exact location, intimate data, security evidence | Local-only by default |
| `P4` | Secret | credentials, keys, tokens, passwords | Forbidden |

## 6.1 Defaults

- user-authored/imported content по умолчанию `P2`;
- unknown content — не ниже `P3` до classification;
- secrets всегда `P4`;
- audit наследует target sensitivity, но минимизирует body;
- title, relation и existence metadata MAY быть столь же чувствительными, как content;
- health/biometric/financial/identity fields по умолчанию `P3`;
- public marking требует явного user/schema intent.

Structured field с `P4` MUST иметь primary class `SE`. `P4` в unstructured `CE/CB` допускается только как защитная маркировка обнаруженного/указанного пользователем embedded secret и не превращает весь record в credential store.

## 6.2 Inheritance

Record наследует наиболее строгую sensitivity из:

- field default;
- parent Space/Collection/Document;
- explicit record label;
- source records, если catalog явно объявляет derivation/containment inheritance;
- operation context.

Child MAY повысить sensitivity без изменения parent. Понижение выполняется только declassification workflow.

Обычная associative relation не повышает sensitivity endpoint records друг от друга. Повышение по relation применяется к самой `CR`, backlink/count/search projection и операции, раскрывающей существование relation. Только relation type с явно объявленной containment/derivation semantics MAY передавать sensitivity endpoint record, и такое правило проверяется на циклы.

## 6.3 Derived sensitivity

Derived output наследует максимальную sensitivity inputs.

Aggregation, embedding, summarization или redaction не понижают sensitivity автоматически.

Approved anonymization/declassification требует отдельного versioned transformation, threat test и evidence того, что output не раскрывает исходные records в заявленной модели угроз.

## 6.4 Relation sensitivity

Relation effective sensitivity не ниже максимума endpoints и relation metadata.

Query без permission на endpoint не должен раскрывать существование relation через count, backlink или timing side channel в пределах принятой threat model.

## 6.5 Declassification

Понижение sensitivity:

1. никогда не изменяет original record;
2. создаёт новую revision/export artifact либо explicit policy revision;
3. фиксирует actor, reason и transformation version;
4. проходит preview;
5. не распространяется назад на sources;
6. может быть отменено для будущих disclosures, но не возвращает уже отправленные copies.

## 6.6 Storage protection requirement

| Код | Требование |
|---|---|
| `PROTECT_STANDARD` | OS permissions, integrity, encrypted transport для network |
| `PROTECT_SENSITIVE` | Standard + content-minimized logs + protected backup recommendation |
| `PROTECT_RESTRICTED` | Sensitive + encrypted remote/backup destination и явная at-rest policy |
| `PROTECT_SECRET_STORE` | Только Secret Service/OS-backed credential storage |

Default mapping: `P0-P1 → PROTECT_STANDARD`, `P2 → PROTECT_SENSITIVE`, `P3 → PROTECT_RESTRICTED`, `P4/SE → PROTECT_SECRET_STORE`.

ADR-005 определяет конкретные encryption mechanisms и recovery. Если текущая platform implementation не достигает требуемого профиля, это отображается как известное ограничение; classification не понижается для сокрытия пробела.

---

# 7. Origin и provenance

## 7.1 Origin kinds

Canonical data указывает один или несколько origins:

- `user`;
- `import`;
- `sync`;
- `migration`;
- `system-observation`;
- `external-provider`;
- `ai`;
- `correction`;
- `recovery`.

## 7.2 Минимальный provenance

Canonical record имеет либо наследует:

- stable ID;
- owner module;
- schema/semantic version;
- origin kind;
- actor/device;
- committed/logical sequence;
- source references, если применимо;
- correction/revision parentage;
- sensitivity/effective policy source;
- import/provider/model metadata, если применимо.

## 7.3 Raw и transformed

Raw observation является `CF` либо частью canonical revision.

Transformation output является `DD`, если воспроизводим.

Если пользователь вручную исправляет extracted/OCR text, correction сохраняется как `CE`; новый derived text строится как composition original extraction + canonical correction layer.

Raw value не перезаписывается normalized, capped или modelled value.

---

# 8. Sync policies

| Код | Значение |
|---|---|
| `SYNC_GLOBAL` | Metadata/record передаётся paired replicas |
| `SYNC_METADATA_ONLY` | Передаётся identity/manifest, но не content bytes/body |
| `SYNC_ON_DEMAND` | Передаётся только по user/device selection |
| `SYNC_HUB_ONLY` | Собирается на Hub, не fan-out всем replicas |
| `SYNC_REBUILD` | Не передаётся; строится локально |
| `SYNC_NEVER` | Никогда не входит в обычный sync |
| `SYNC_SECRET_PROVISIONING` | Отдельный explicit credential provisioning, не domain sync |

## 8.1 Baseline by class

| Class | Default sync |
|---|---|
| `CF` | `SYNC_GLOBAL` если type syncable |
| `CE` | `SYNC_GLOBAL` |
| `CR` | `SYNC_GLOBAL` |
| `CB` | Identity `SYNC_GLOBAL`, bytes `SYNC_ON_DEMAND` |
| `CA` | `SYNC_NEVER` по умолчанию; конкретный catalog type MAY явно разрешить `SYNC_HUB_ONLY` или `SYNC_METADATA_ONLY` |
| `DD` | `SYNC_REBUILD` |
| `OT` | `SYNC_NEVER`; protocol receipts локальны endpoint |
| `OR` | `SYNC_NEVER` |
| `DL` | `SYNC_NEVER` |
| `SE` | `SYNC_NEVER` либо отдельный `SYNC_SECRET_PROVISIONING` |

## 8.2 Sensitivity и sync

Sensitivity сама по себе не запрещает encrypted paired-device sync canonical data, но может потребовать:

- explicit user opt-in;
- selected devices;
- metadata-only mode;
- no Hub fan-out;
- stronger encryption/key policy;
- local-only container.

`P4` не входит в ordinary sync. Это относится и к явно маркированному unstructured `CE/CB`: такой record остаётся local-only либо использует отдельный targeted protected-content transfer. `SYNC_SECRET_PROVISIONING` применяется только к structured `SE`, а не к произвольному `CE/CB` content.

## 8.3 Sync receipts

- deduplication/inbox receipt — `OT`;
- security evidence о pairing/revocation — `CA`;
- domain fact, полученный через sync, сохраняет исходный `CF/CE/CR` class и origin metadata;
- транспортная доставка не создаёт новую domain observation.

## 8.4 Presence policies

Presence описывает наличие bytes/derived representation на конкретном device и не заменяет sync policy.

| Код | Значение |
|---|---|
| `PRESENCE_REQUIRED` | Данные должны находиться на device для заявленной local core-функции |
| `PRESENCE_SELECTIVE` | Metadata доступна, bytes загружаются по выбору/необходимости |
| `PRESENCE_HUB_FULL` | Hub обязан поддерживать полный заявленный blob scope |
| `PRESENCE_REBUILD` | Representation создаётся локально из canonical inputs |
| `PRESENCE_EPHEMERAL` | Существует только во время ограниченного workflow/session |

Blob identity имеет global canonical presence как metadata, но blob bytes обычно `PRESENCE_SELECTIVE` на Mobile и `PRESENCE_HUB_FULL` на Desktop Hub.

Факт наличия bytes остаётся `DL`; он не переносится как глобальная истина.

---

# 9. Export policies

| Код | Значение |
|---|---|
| `EXPORT_REQUIRED` | Обязателен portable machine-readable export; human-readable где возможно |
| `EXPORT_REDACTED` | Экспорт только через отдельный redacted/minimized формат |
| `EXPORT_OPTIONAL` | MAY включаться как convenience, но не нужен для владения данными |
| `EXPORT_NONE` | Не включается, потому что rebuildable/local/operational |
| `EXPORT_PROHIBITED` | Запрещён в ordinary export, например secrets |

## 9.1 Baseline by class

| Class | Default export |
|---|---|
| `CF/CE/CR/CB` | `EXPORT_REQUIRED` |
| `CA` | `EXPORT_REDACTED` через отдельный explicit audit export |
| `DD` | `EXPORT_NONE`; definition/provenance canonical parts экспортируются |
| `OT/OR/DL` | `EXPORT_NONE` |
| `SE` | `EXPORT_PROHIBITED` |

## 9.2 Export sensitivity

Portable export не теряет ownership из-за высокой sensitivity, но `P2/P3` export требует:

- exact scope preview;
- destination warning;
- optional/recommended encryption;
- no implicit cloud upload;
- checksum manifest;
- explicit handling of filenames/metadata leakage.

Secret export выполняется только отдельным recovery/credential workflow, если он вообще поддерживается.

Явно маркированный unstructured `P4` content в `CE/CB` не включается в широкий export автоматически. Он доступен только через targeted high-risk export с точным preview и подтверждением; это не превращает его в поддерживаемый credential format.

## 9.3 Export completeness

Export validator проверяет:

- все required types;
- stable IDs и relations;
- original blobs;
- schema/semantic versions;
- units/timestamps/missing semantics;
- checksums;
- redactions и exclusions;
- unresolved references;
- module exporter versions.

---

# 10. Backup policies

| Код | Значение |
|---|---|
| `BACKUP_REQUIRED` | Должно входить в полноценный restore set |
| `BACKUP_IF_PRESENT` | Bytes включаются, если являются частью выбранного backup scope/presence |
| `BACKUP_OPTIONAL_REBUILD` | Можно исключить и перестроить |
| `BACKUP_EXCLUDE` | Не включается |
| `BACKUP_SECRET_SEPARATE` | Отдельная защищённая recovery policy |

## 10.1 Baseline by class

| Class | Default backup |
|---|---|
| `CF/CE/CR/CA` | `BACKUP_REQUIRED` с применимой retention/privacy policy |
| `CB` | `BACKUP_IF_PRESENT`, но full Desktop backup должен покрывать все canonical blobs scope |
| `DD` | `BACKUP_OPTIONAL_REBUILD` |
| `OT` | `BACKUP_REQUIRED` пока record активен; безопасно ненужный после cleanup record должен быть удалён, а не переклассифицирован на лету |
| `OR/DL` | `BACKUP_EXCLUDE` по умолчанию |
| `SE` | `BACKUP_SECRET_SEPARATE` |

## 10.2 Sensitivity и backup

Canonical data не исключаются молча только потому, что чувствительны: это создало бы неполный restore.

Для `P3` backup destination SHOULD быть зашифрован. До ADR-005 UI обязан честно показывать фактическую защиту и получать явное risk acceptance, если backup создаётся без требуемого encryption.

`SE` и structured credential `P4` не попадают в canonical backup; отдельно определяется key/token recovery.

Если unstructured `CE/CB` явно маркирован `P4`, backup обязан либо использовать утверждённый protected scope, либо сообщить о неполноте и потребовать решения пользователя. Он не должен ни молча раскрыть content, ни молча заявить полный restore при исключённом record.

## 10.3 Backup container classification

Backup set наследует максимальную sensitivity содержащихся records и не может считаться менее чувствительным из-за compression/encryption.

Encryption снижает риск disclosure, но не меняет semantic sensitivity class.

---

# 11. Retention, deletion и purge

## 11.1 Retention codes

| Код | Значение |
|---|---|
| `RET_USER_OR_POLICY` | До user delete/purge либо принятой domain policy |
| `RET_POLICY_WINDOW` | Явно заданное окно ADR/module policy |
| `RET_UNTIL_CONSUMED` | До подтверждённого завершения workflow/replay window |
| `RET_REBUILDABLE` | Можно удалить после canonical commit; восстановимо |
| `RET_SESSION` | До конца session/process + cleanup |
| `RET_SECRET_LIFETIME` | До rotation/revocation/provider expiry |

Точные durations принимаются в ADR-008 и module specifications. Формулировка «хранить пока не понадобится место» недопустима.

## 11.2 Deletion modes

| Mode | Применение |
|---|---|
| Correction | Исправление `CF` |
| Revision/archive | Обычное изменение/скрытие `CE` |
| Tombstone | Распространяемое delete state для `CE/CR` |
| Rebuild reset | `DD` |
| Workflow cleanup | `OT/OR` после policy proof |
| Local reset | `DL` |
| Rotate/revoke | `SE` |
| Purge | Физическое уничтожение canonical data |

## 11.3 Reference-aware deletion

До delete/purge система определяет:

- inbound/outbound relations;
- revision descendants/parents;
- blob references;
- derived dependants;
- sync replicas/tombstones;
- backups/snapshots;
- active jobs/outbox;
- legal/technical impossibility удалить external copies.

Обычный delete не должен создавать dangling canonical reference без explicit unresolved/tombstone semantics.

## 11.4 Purge behavior

Purge policy для type указывает:

- scope expansion;
- cascade vs detach;
- replica propagation;
- backup reachability;
- blob GC;
- audit minimization;
- idempotency receipt;
- verification proof;
- ограничения внешних copies.

Purge не используется как housekeeping derived/operational state.

---

# 12. Outbound AI policies

| Код | Поведение |
|---|---|
| `AI_ALLOWED` | Cloud/local AI разрешён в пределах scopes; audit/provenance сохраняются |
| `AI_ASK` | Каждый disclosure/workflow требует preview и подтверждения |
| `AI_LOCAL_ONLY` | Только локальная модель, без передачи внешнему provider |
| `AI_FORBIDDEN` | Никакой AI context/tool exposure |

## 12.1 Default mapping

| Sensitivity | Default outbound AI |
|---|---|
| `P0` | `AI_ALLOWED` |
| `P1` | `AI_ASK`, container MAY разрешить постоянный scope |
| `P2` | `AI_ASK` с source preview и минимизацией |
| `P3` | `AI_LOCAL_ONLY`; explicit one-time override требует усиленного warning/policy |
| `P4` | `AI_FORBIDDEN` |

`AI_LOCAL_ONLY` является жёсткой effective policy и не обходится prompt или обычным session grant. Для `P3` пользователь MAY отдельным усиленно подтверждённым policy revision временно установить `AI_ASK`, если parent/container/security policy не запрещает cloud disclosure. Это изменение фиксируется до формирования context.

## 12.2 Effective outbound policy

Context Broker применяет наиболее строгую policy из:

- Space/Collection/Note/Document;
- field/record sensitivity;
- requested query/tool;
- provider destination;
- user session grant;
- organization/device security policy, если появится.

Модель или retrieved content не может ослабить effective policy.

## 12.3 Derived и AI outputs

- embedding/summary/model state наследует sensitivity sources;
- AI response audit наследует sensitivity context;
- сохранённый AI answer становится обычной `CE` revision либо `CF` observation с provenance;
- временный context assembly — `OR` и удаляется по короткой policy;
- provider token/cost metadata не содержит prompt body без отдельной необходимости;
- secret handles не раскрываются модели даже при `AI_ALLOWED`.

## 12.4 Redaction

Redaction:

- создаёт outbound representation, не меняя local original;
- версионируется, если используется повторно;
- показывается в preview/audit metadata;
- не гарантирует declassification без отдельного доказательства;
- не должна оставлять обратимые identifiers/metadata вопреки заявленной policy.

---

# 13. Logs, diagnostics и temporary data

## 13.1 Logs

Обычный log — `OR`, а не `CA`.

По умолчанию log не содержит:

- note/document bodies;
- raw answers;
- full prompts/context;
- secrets;
- authorization headers;
- precise sensitive paths;
- original imported bytes.

Log MAY содержать IDs, types, durations, error codes и correlation IDs при условии sensitivity review.

## 13.2 Diagnostic bundle

Расширенный diagnostic bundle создаётся только явно и имеет:

- preview;
- redaction;
- exact scope;
- expiry/cleanup;
- destination warning;
- manifest;
- no secrets.

Если bundle сохраняется как пользовательский artifact внутри Nabla, он классифицируется отдельно; временная копия остаётся `OR`.

## 13.3 Temporary files

Temporary file наследует sensitivity источника.

Он:

- создаётся с restrictive permissions;
- имеет owner/cleanup trigger;
- не индексируется и не backup по умолчанию;
- удаляется после success, failure или timeout;
- не используется как единственная copy после canonical commit.

## 13.4 Crash remnants

Startup cleanup проверяет staging/tmp records. Неизвестный чувствительный remnant quarantined и не отправляется в diagnostics автоматически.

---

# 14. Предварительная классификация Kernel data

Эта таблица задаёт обязательный baseline для будущего Data Catalog и DDL.

| Record/type | Class | Sensitivity default | Sync | Export | Backup | Примечание |
|---|---|---|---|---|---|---|
| Command receipt | `CA` | Target-derived, min `P1` | Metadata/type-specific | Redacted | Required | Evidence actor/result; payload minimized |
| Idempotency record | `OT` | Target-derived, body hash preferred | Never | None | Required while active | Не audit и не domain fact |
| Domain event pending delivery | `OT` | Source-derived | Never as source | None | Required while pending | После consumption удаляется по policy |
| Long-term semantic observation | `CF` | Domain-derived | Global if syncable | Required | Required | Не хранить только как event payload |
| Audit event | `CA` | Target-derived | Hub-only/metadata/never | Redacted | Required by retention | Secrets forbidden |
| Transactional outbox | `OT` | Source-derived | Never | None | Required while pending | Atomic with command |
| Sync inbox/dedupe receipt | `OT` | `P1-P2` | Never | None | Required while active | Endpoint-local transport state |
| Device local sequence | `OT` | `P1` | Never | None | Required for safe restore | Monotonic per device |
| Device public identity/trust config | `CE` | `P2` | Global/Hub | Required | Required | Rename/trust via revisions |
| Device private key | `SE` | `P4` | Secret provisioning only | Prohibited | Separate | OS/secret store |
| Schema migration definition | Packaged code/spec | `P0-P1` | Release distribution | Documentation | With app | Не runtime user data |
| Applied migration evidence | `CA` | `P1` | Hub/never | Redacted | Required | Version/checksum/result |
| Migration lock/progress | `OT` | `P1` | Never | None | Required during active migration/recovery | Exclusive workflow state |
| Module manifest packaged | Packaged code/spec | `P0-P1` | Release distribution | Documentation | With app | Registry строится из manifests |
| Module activation/configuration | `CE` | `P1-P3` | Global if desired | Required | Required | Permissions/sensitivity may raise class |
| Module Registry projection | `DD` | Config-derived | Rebuild | None | Rebuild | Не source of truth |
| Capability Registry projection | `DD` | Contract-derived | Rebuild | None | Rebuild | Built from manifests/contracts |
| Loop definition/configuration | `CE` | Domain-derived | Global | Required | Required | Built-in defaults MAY originate from package |
| Loop validation result | `DD` | Inputs-derived | Rebuild | Optional | Rebuild | Validator version required |
| Relation record | `CR` | Endpoint-derived | Global | Required | Required | Typed/stable endpoints |
| Backlink index | `DD` | Endpoint-derived | Rebuild | None | Rebuild | Never canonical |
| Blob identity metadata | `CB` metadata | Content-derived | Global metadata | Required | Required | Hash/size/algorithm |
| Domain-to-blob reference | `CR` | Max domain/blob | Global | Required | Required | Например `document_version_has_blob`; blob identity отдельно `CB` |
| Blob bytes | `CB` | Content-derived | On demand | Required | If present/full Hub | Immutable |
| Blob local presence | `DL` | `P1` | Never | None | Exclude | Device-only |
| Blob verification run receipt | `CA` | Blob-derived | Hub/never | Redacted | Retention policy | Algorithm/result/run evidence |
| Blob corruption finding | `CF` | Blob-derived | Type-specific | Required | Required | Отдельное наблюдение, если имеет пользовательский/recovery consumer |
| Search index | `DD` | Source-derived | Rebuild | None | Rebuild | May expose sensitive tokens locally |
| Job durable state | `OT` | Source-derived | Never | None | While required | Prevent duplicate/continue workflow |
| Job health snapshot | `OR` | `P1` | Never | None | Exclude | Re-creatable |
| Policy definition | `CE` | `P2-P3` | Global/selected | Required | Required | Outbound/privacy/security meaning versioned |
| Backup run result | `CA` | Backup-scope-derived | Hub/never | Redacted | Required by retention | No backup secrets in body |
| Restore run result | `CA` | Backup-scope-derived | Hub/never | Redacted | Required | Verification evidence |
| Backup manifest in backup set | `CA` artifact | Max content sensitivity | N/A | N/A | Integral | Checksums/schema/module versions |
| Debug log | `OR` | `P1`, minimized | Never | None | Exclude | Short rotation |
| Temporary diagnostic bundle | `OR` | Max included sensitivity | Never | Explicit one-time transfer only | Exclude | Preview/redaction/expiry |
| User-retained diagnostic artifact | `CB` | Max included sensitivity | User policy | Required | Required if retained | Создаётся отдельной explicit command |

`Packaged code/spec` не является runtime primary state class; если его representation сохраняется в user DB как editable configuration, оно получает `CE`.

---

# 15. Предварительная классификация Platform и Knowledge v1

| Record/type | Class | Sensitivity default | Sync | Export | Backup | Примечание |
|---|---|---|---|---|---|---|
| Layout identity/revision/head | `CE` | `P1-P2` | Global | Required | Required | Layout-as-data |
| Widget instance inside layout | `CE` field | Inherits layout/query | Global with revision | Required | Required | No executable code |
| Form definition/configuration | `CE` | Input-derived | Global | Required | Required | Command binding versioned |
| Window geometry | `DL` | `P1` | Never | None | Exclude | Device-only |
| Last open panel | `DL` | `P1-P2` | Never | None | Exclude | MAY reveal activity; still local |
| Space | `CE` | `P2` default | Global | Required | Required | Container sensitivity/AI policy |
| Collection | `CE` | Inherits Space | Global | Required | Required | Stable ID |
| Collection membership | `CR` | Max endpoints | Global | Required | Required | Not path-based identity |
| Note identity/revision/head | `CE` | `P2` default | Global | Required Markdown+metadata | Required | User MAY set `P0-P3` |
| Note inline link token | `CE` field | Note-derived | With revision | Markdown | Required | Human-readable side |
| Resolved note link | `CR` | Max endpoints | Global | Relation manifest | Required | Stable target ID |
| Unresolved inline link | `CE` field in Note Revision | Note-derived | With revision | Markdown | Required | Original token preserved; `CR` появляется только после resolution |
| Tag definition | `CE` | `P1-P2` | Global | Required | Required | Tag name may be sensitive |
| Tag assignment | `CR` | Max endpoints | Global | Required | Required | Backlink/index derived |
| Property definition | `CE` | `P1-P2` | Global | Required | Required | Type/semantics versioned |
| Property scalar value | `CE` field in revision | Field/container-derived | Global | Required | Required | Raw value retained |
| Entity-reference property assignment | `CR` | Max endpoints | Global | Required | Required | Property Definition остаётся `CE` |
| Template | `CE` | `P1-P2` | Global | Required | Required | May contain sensitive defaults |
| Saved Query definition | `CE` | Sources-derived | Global | Required | Required | Query result itself derived |
| Saved Query result/cache | `DD` | Max sources | Rebuild | None | Rebuild | Freshness required |
| Full-text index | `DD` | Max indexed content | Rebuild | None | Rebuild | Local protection still required |
| Backlink/property index | `DD` | Max sources | Rebuild | None | Rebuild | No source authority |

---

# 16. Предварительная классификация Documents v1

| Record/type | Class | Sensitivity default | Sync | Export | Backup | Примечание |
|---|---|---|---|---|---|---|
| Document identity/revision/head | `CE` | `P2` default | Global | Required | Required | Title/metadata/policy revisioned; metadata edit не меняет content version |
| Document Version | `CE` immutable content-version record | Document-derived | Global | Required | Required | Ссылается на exact original blob; anchors bind к этой identity |
| Original PDF/file | `CB` | Document-derived | Metadata global, bytes on demand | Original file | Required on full Hub | Content hash identity |
| Document import provenance | `CE` fields in Document Version | Document-derived | With revision | Required | Required | Origin/source metadata; отдельный `CF` не создаётся без самостоятельного loop |
| Original local path | `DL` | `P2-P3` | Never | None | Exclude | MAY be retained only locally |
| Explicit source URI/reference | `CE` field in Document Revision | Source-derived | Global if intended | Required | Required | Отличается от technical path; связь с зарегистрированной entity оформляется отдельным `CR` |
| Extracted text layer | `DD` | Document-derived | Rebuild | None by default | Rebuild | Parser/version/provenance required |
| OCR output | `DD` | Document-derived | Rebuild | None by default | Rebuild | Confidence separate |
| User correction to extracted text | `CE` | Document-derived | Global | Required sidecar | Required | Не перезаписывает raw extraction |
| Thumbnail/page preview | `DD` | Document-derived | Rebuild | None | Rebuild | May still be sensitive locally |
| Search token/index | `DD` | Document-derived | Rebuild | None | Rebuild | No sync authority |
| Annotation identity/revision/head | `CE` | Max document/note policy | Global | Required | Required | User-editable content |
| Annotation canonical anchor | `CE` field | Document-derived | Global | Required | Required | Version/page/text quote/coordinates |
| Re-resolved anchor position | `DD` | Annotation/document-derived | Rebuild | None | Rebuild | Resolver version required |
| Bookmark | `CE` | Document-derived | Global | Required | Required | Name/order revisioned |
| Live reading cursor | `DL` | Document-derived | Never | None | Exclude | Frequent ephemeral movement |
| Durable reading checkpoint | `CF` | Document-derived | Global | Required | Required | Session end/throttled explicit observation |
| Latest resume position | `DD` | Checkpoint-derived | Rebuild | Optional | Rebuild | Query projection, not source |
| Active reading session state | `OT` | `P2`, container-derived | Never | None | While active | Durable local workflow state; не domain history |
| Completed Reading Session (inactive in v1) | `CF` if a future loop activates it | `P2`, container-derived | Not collected in v1 | Not applicable in v1 | Not applicable in v1 | Требует отдельного user-facing history/learning loop; resume не является достаточным consumer |
| Reader UI split/zoom state | `DL` | `P1-P2` | Never | None | Exclude | Unless promoted to explicit syncable preference |
| Document-note link | `CR` | Max endpoints | Global | Required | Required | Stable document version/anchor |

## 16.1 Reading position decision

Nabla не сохраняет каждый scroll/page movement как canonical fact.

Применяется трёхслойная модель:

1. **Live cursor (`DL`)** — частые device-local updates.
2. **Durable checkpoint (`CF`)** — session end, explicit bookmark-like save либо throttled meaningful checkpoint.
3. **Latest resume (`DD`)** — projection по применимым checkpoints с versioned tie-breaking policy.

Это сохраняет offline/sync semantics без бесконечного event noise и hidden overwrite.

Completed Reading Session history в v1 не создаётся. Active reader session
остаётся `OT` только для crash recovery и корректного завершения bounded
workflow; после checkpoint/cleanup она удаляется по retention policy. Если
позднее появится отдельная история чтения или Learning consumer, её summary
может быть введён как `CF` только новой versioned schema с собственным Loop
Descriptor, явным UI-потребителем, bounded collection policy и export/retention
семантикой. Одного потенциального будущего analytics consumer недостаточно.

## 16.2 Anchor decision

Canonical Annotation Revision хранит evidence, необходимую для последующего разрешения:

- document version ID;
- page;
- normalized coordinates;
- text quote/position, если доступны;
- fallback visual evidence/hash.

Конкретная текущая resolved position после изменения parser является `DD`. Parser update не переписывает canonical anchor.

---

# 17. Предварительная классификация Learning и Analytics v2

| Record/type | Class | Sensitivity default | Sync | Export | Backup | Примечание |
|---|---|---|---|---|---|---|
| Objective | `CE` | `P2` | Global | Required | Required | Criteria/deadline revisioned |
| Concept | `CE` | `P1-P2` | Global | Required | Required | Canonical name/aliases revisioned |
| Concept prerequisite | `CR` | Max endpoints | Global | Required | Required | Graph index derived |
| Source Span relation | `CR` | Max source/target | Global | Required | Required | Stable document version/anchor |
| Task definition | `CE` | `P2` | Global | Required | Required | Difficulty estimate not raw truth |
| Attempt | `CF` | `P2-P3` | Global | Required | Required | Hints/viewed solution/context explicit |
| Evaluation | `CF` | Attempt-derived | Global | Required | Required | Multiple evaluations allowed |
| Rubric definition | `CE` | `P1-P2` | Global | Required | Required | Versioned semantics |
| Error symptom observation | `CF` | `P2-P3` | Global | Required | Required | Observed evidence |
| Error cause hypothesis/status | `CE` | Symptom-derived | Global | Required | Required | Uncertainty separate; may evolve |
| Error-concept link | `CR` | Max endpoints | Global | Required | Required | Confidence field explicit |
| Review Observation | `CF` | `P2-P3` | Global | Required | Required | Raw result/lag/latency |
| Intervention | `CF` | `P2-P3` | Global | Required | Required | Не объявляет causality |
| Metric definition | `CE` | Sources-derived | Global | Required | Required | Grain/missing/transform versioned |
| Saved analytics query | `CE` | Sources-derived | Global | Required | Required | Definition canonical |
| Metric value/aggregate | `DD` | Max sources | Rebuild | None by default | Rebuild | Provenance/coverage required |
| Chart cache | `DD` | Max sources | Rebuild | None | Rebuild | UI-only projection |
| Memory model definition/config | `CE` | `P1-P2` | Global | Required | Required | Algorithm package version referenced |
| Fitted memory state/model artifact | `DD` | Max training data | Rebuild | None by default | Rebuild | Calibration/version required |
| Scheduler policy | `CE` | `P1-P2` | Global | Required | Required | Separate from memory model |
| Review recommendation | `DD` | Max inputs | Rebuild | Optional | Rebuild | Not user commitment |
| Accepted review plan | `CE` | `P2` | Global | Required | Required | User/application decision |
| Health/sleep/biometric observation | `CF` | `P3` | Explicit selected devices | Required with warning | Protected required | Cloud AI local-only default |
| Financial observation | `CF` | `P3` | Explicit selected devices | Required with warning | Protected required | Credentials remain `SE` |

## 17.1 Result vs confidence

Поля `raw_score`, `self_confidence`, `grading_confidence`, `measurement_quality`, `model_uncertainty` и `coverage` имеют отдельные field entries.

Они могут находиться в одном `CF`, но не объединяются в одно source-of-truth value.

## 17.2 Model replacement

Замена model/scheduler изменяет `CE` definition и перестраивает `DD`. Она не создаёт migration для raw `CF`, если их semantics не изменились.

---

# 18. Предварительная классификация AI Layer v3

| Record/type | Class | Sensitivity default | Sync | Export | Backup | Примечание |
|---|---|---|---|---|---|---|
| Provider non-secret configuration | `CE` | `P2-P3` | Selected/never | Required redacted | Required | Model names/scopes/endpoints |
| OAuth/API token | `SE` | `P4` | Never/secret provisioning | Prohibited | Separate | Opaque handle in config |
| Prompt/template definition | `CE` | `P2` | Global/selected | Required | Required | Versioned |
| Context assembly | `OR` | Max sources | Never | None | Exclude | Short cleanup; provenance refs retained separately |
| AI request/tool-call audit | `CA` | Max context/target | Hub/metadata/never | Redacted explicit | Retention policy | Full prompt not default requirement |
| AI response audit metadata | `CA` | Max context | Hub/metadata/never | Redacted explicit | Retention policy | Provider/model/cost/source IDs |
| AI conversation/transcript entity retained by user | `CE` | Max context | User policy | Required | Required | Explicit retention, not automatic audit body |
| AI transcript binary attachment/export retained in Nabla | `CB` | Max transcript | User policy | Required | Required | Ссылается на transcript `CE` |
| AI answer saved into note | Existing Note `CE` revision | Max sources/note | Global | Required | Required | AI provenance attached |
| AI evaluation result | `CF` | Target-derived | Global/type policy | Required | Required | Raw result/confidence/provenance |
| AI proposal | `CE` | Max inputs/target | Global/selected | Required | Required | No state effect before Apply |
| Current proposal validation projection | `DD` | Proposal-derived | Rebuild | None | Rebuild | Validator/version/provenance required |
| Proposal Apply receipt | `CA` | Target-derived | Hub/metadata | Redacted | Retention policy | Target mutation использует обычный `CF/CE/CR` contract |
| User-facing token/cost observation | `CF` | `P1-P2` | Global/Hub by type | Required | Required | Активный cost loop; no prompt body |
| Provider-call cost audit field | `CA` field | Request-derived | Audit policy | Redacted | Audit retention | Не отдельный duplicate domain fact без consumer |
| Embedding/vector | `DD` | Max sources | Rebuild | None | Rebuild | Model/version required |
| Unsaved nondeterministic AI response/summary | `OR` | Max sources | Never | None | Exclude | Short retention; explicit Save создаёт обычную `CE` revision |

## 18.1 Transcript minimization

AI Audit не обязан бессрочно хранить полный prompt/response.

Минимальный evidence может содержать:

- source IDs/versions;
- redaction/context policy version;
- provider/model;
- tool calls;
- cost/tokens;
- output hash;
- confirmation/apply result.

Полный transcript сохраняется только при активном consumer и explicit retention policy.

## 18.2 AI output promotion

Переход из временного/derived AI output в canonical state выполняется explicit command:

- save as note/revision;
- record evaluation;
- create proposal;
- attach artifact.

Promotion фиксирует provenance и effective sensitivity; provider response сам по себе не получает права стать canonical mutation.

---

# 19. Data Catalog и validators

## 19.1 Catalog ownership

Каждый module поставляет собственные catalog entries. Kernel агрегирует их и проверяет global invariants.

Data Catalog является version-controlled specification и runtime-readable manifest, но не должен иметь две независимо редактируемые истины. Генерируемая runtime representation строится из нормативного source.

## 19.2 Activation validation

Module/schema activation отклоняется, если:

- record/field class отсутствует;
- owner отсутствует;
- writer не соответствует class;
- canonical field не имеет export/backup policy;
- subject field не имеет loop;
- service field не имеет technical purpose/consumer/retention;
- `DD` не имеет rebuild/provenance;
- `SE` объявлен в canonical DB;
- `DL` помечен global sync;
- `P4` допускает ordinary export/AI;
- derived sensitivity ниже sources без declassification proof;
- correction/revision semantics не соответствуют class;
- purge behavior не определён для canonical type.

## 19.3 Query validation

Query contract перечисляет classes/sensitivity, которые он может вернуть.

Runtime:

- применяет read scopes;
- вычисляет effective policy;
- не раскрывает forbidden fields через projection;
- возвращает provenance/freshness для `DD`;
- ограничивает aggregation side channels;
- журналирует security-relevant reads согласно policy.

## 19.4 Command validation

Command contract перечисляет classes, которые может создавать или изменять.

Handler не может:

- создать record class, отсутствующий в manifest;
- обновить `CF/CA/CB` in place;
- записать `DD` как canonical effect;
- записать `SE` в payload/audit body;
- понизить sensitivity без declassification command;
- обойти loop/retention/export policies.

## 19.5 Processor validation

Processor объявляет:

- canonical inputs;
- output `DD/OR` types;
- algorithm/model version;
- rebuild entry point;
- sensitivity inheritance;
- checkpoint/retry semantics;
- resource limits;
- deletion/reset behavior.

Processor, создающий исторически значимый невоспроизводимый результат, должен отправить отдельную Command для `CF/CE/CA` promotion.

---

# 20. Проверочные сценарии

| Сценарий | Ожидаемая классификация | Запрещённая ошибка |
|---|---|---|
| Reindex всех notes | Index `DD`, note revisions `CE` | Считать index единственной копией text |
| Новый PDF parser | Extraction `DD`, user corrections `CE` | Перезаписать corrections новым OCR |
| Scroll на каждой странице | Live cursor `DL`, checkpoint `CF`, latest `DD` | Sync каждого pixel movement либо mutable global row без history |
| Retry import command | Idempotency `OT`, import fact `CF`, blob `CB` | Создать второй Document/blob reference |
| AI анализ private note | Note `P2`, context `OR`, audit `CA` | Сохранить full prompt в debug log |
| Health analytics | Observation `CF/P3`, metric `DD/P3` | Понизить aggregate до `P1` автоматически |
| Disable module | Canonical types остаются; registry projection rebuild | Удалить data вместе с module |
| Purge document | `CE/CB/CR/CA` policies + receipt | Использовать обычный cache GC |
| Device revoked | Trust config `CE`, private key `SE`, evidence `CA` | Отправить credentials обычным sync |
| Backup without encryption | Data class не меняется; risk warning | Объявить backup безопасным из-за compression |
| Relation to restricted note | Relation sensitivity `P3` | Раскрыть backlink пользователю/query без endpoint permission |
| Model replacement | Definition `CE`, state `DD`, observations `CF` | Мигрировать raw scores под новую формулу |

---

# 21. Constitutional Conformance Matrix

| Инвариант | Data-classification mechanism |
|---|---|
| I1 | Class-specific allowed writers; Command for `CF/CE/CR/CB`, Audit Service for `CA` |
| I2 | `CF` append/correction-only profile |
| I3 | `CE` entity/revision/head/tombstone profile |
| I4 | `DD` rebuild/provenance/version requirements |
| I5 | Semantic version in every catalog entry |
| I6 | Module-owned catalog entries validated through manifests |
| I7 | Loop or technical-purpose requirement per field |
| I8 | Consumers/outcomes in catalog descriptor |
| I9 | Independent field classification for raw/confidence/quality/uncertainty |
| I10 | `CA` receipts separated from `OT` idempotency/outbox |
| I11 | Class-specific delete modes and isolated purge behavior |
| I12 | `DL`, local canonical storage и explicit external policies |
| I13 | Sensitivity + effective outbound AI lattice; `SE/P4` forbidden |
| I14 | Raw canonical vs transformed `DD`, canonical correction layers |
| I15 | Independent reset/rebuild/failure behavior by class |
| I16 | Mandatory export for `CF/CE/CR/CB`, redacted evidence, forbidden secrets |

---

# 22. Зависимые ADR и открытые параметры

Классы и базовые policy semantics зафиксированы настоящим документом. Следующие параметры остаются в ADR/specifications:

| Решение | Документ |
|---|---|
| Exact retention windows, audit expiry, tombstone proof | ADR-008 |
| Encryption DB/blob/backup, key recovery | ADR-005 |
| Global ID/device sequence/logical time formats | ADR-009 |
| Migration records/recovery framework | ADR-012 |
| Stable PDF anchor fields | ADR-006 + `DOCUMENT-MODULE.md` |
| Module catalog/manifest serialization | `MODULE-MANIFEST.md` |
| Capability read/write class declarations | `CAPABILITY-CONTRACT.md` |
| Loop descriptor/validator | `LOOP-SPEC.md` |
| Exact v1 entity fields | Module specifications + Data Catalog + DDL |

Open parameter не разрешает использовать `unclassified` либо временно ослаблять fail-closed defaults.

---

# 23. Acceptance criteria

`DATA-CLASSIFICATION.md` v0.1 готов к утверждению, если:

1. классы `CF/CE/CR/CB/CA/DD/OT/OR/DL/SE` взаимно различимы;
2. для любого persistent value существует однозначная процедура выбора primary class;
3. sensitivity не смешана с state class;
4. effective policy вычисляется fail-closed;
5. derived data наследуют sensitivity и имеют rebuild proof;
6. secrets физически исключены из canonical DB и обычных flows;
7. sync/export/backup/retention/purge/AI policies заданы независимо;
8. Kernel v1 records предварительно классифицированы;
9. Knowledge/Document records предварительно классифицированы;
10. пограничные случаи reading position, PDF extraction, events/audit/idempotency и AI outputs разрешены;
11. Conformance Matrix покрывает I1-I16;
12. владелец проекта явно утверждает документ.

После утверждения следующий документ — `CAPABILITY-CONTRACT.md`.
