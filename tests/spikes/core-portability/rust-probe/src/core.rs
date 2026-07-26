use rusqlite::{
    Connection, Error as SqliteError, ErrorCode, OptionalExtension, TransactionBehavior, params,
};
use serde::{Deserialize, Serialize};
use std::path::Path;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

pub const MAX_REQUEST_BYTES: usize = 64 * 1024;
pub const MAX_VALUE_BYTES: usize = 4 * 1024;
pub const MAX_IDENTIFIER_BYTES: usize = 128;
pub const BUSY_TIMEOUT_MS: u64 = 250;

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum FailureStage {
    AfterFact,
    AfterIdempotency,
    AfterAudit,
    AfterOutbox,
}

impl FailureStage {
    fn label(self) -> &'static str {
        match self {
            Self::AfterFact => "after_fact",
            Self::AfterIdempotency => "after_idempotency",
            Self::AfterAudit => "after_audit",
            Self::AfterOutbox => "after_outbox",
        }
    }
}

#[derive(Debug, Deserialize)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
enum Request {
    Apply {
        request_id: String,
        fact_id: String,
        value: String,
        #[serde(default)]
        deadline_unix_ms: Option<u64>,
        #[serde(default)]
        inject_failure: Option<FailureStage>,
    },
    Inspect,
    Integrity,
    PanicProbe,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Counts {
    pub facts: i64,
    pub idempotency: i64,
    pub audit: i64,
    pub outbox: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Response {
    pub status: String,
    pub code: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub message: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub request_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub fact_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub replayed: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub counts: Option<Counts>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub integrity: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub journal_mode: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub busy_timeout_ms: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub sqlite_version: Option<String>,
}

impl Response {
    fn applied(request_id: &str, fact_id: &str) -> Self {
        Self {
            status: "ok".into(),
            code: "APPLIED".into(),
            message: None,
            request_id: Some(request_id.into()),
            fact_id: Some(fact_id.into()),
            replayed: Some(false),
            counts: None,
            integrity: None,
            journal_mode: None,
            busy_timeout_ms: None,
            sqlite_version: None,
        }
    }

    fn error(code: &str, message: &str) -> Self {
        Self {
            status: "error".into(),
            code: code.into(),
            message: Some(message.into()),
            request_id: None,
            fact_id: None,
            replayed: None,
            counts: None,
            integrity: None,
            journal_mode: None,
            busy_timeout_ms: None,
            sqlite_version: None,
        }
    }
}

#[derive(Debug)]
enum CoreError {
    Injected(FailureStage),
    Sqlite(SqliteError),
    CorruptReceipt,
}

#[derive(Debug, Deserialize)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
enum ServiceProbeRequest {
    CrashProbe {
        request_id: String,
        fact_id: String,
        value: String,
        crash_after: FailureStage,
    },
}

impl From<SqliteError> for CoreError {
    fn from(value: SqliteError) -> Self {
        Self::Sqlite(value)
    }
}

pub struct Core {
    connection: Connection,
}

impl Core {
    pub fn open(path: &Path) -> rusqlite::Result<Self> {
        let connection = Connection::open(path)?;
        connection.busy_timeout(Duration::from_millis(BUSY_TIMEOUT_MS))?;
        connection.pragma_update(None, "foreign_keys", "ON")?;
        connection.pragma_update(None, "journal_mode", "WAL")?;
        connection.pragma_update(None, "synchronous", "FULL")?;
        connection.execute_batch(
            "
            CREATE TABLE IF NOT EXISTS probe_facts (
                fact_id TEXT PRIMARY KEY NOT NULL,
                value TEXT NOT NULL,
                request_id TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS probe_idempotency (
                request_id TEXT PRIMARY KEY NOT NULL,
                canonical_payload TEXT NOT NULL,
                response_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS probe_audit (
                audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL UNIQUE,
                action TEXT NOT NULL,
                fact_id TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS probe_outbox (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL UNIQUE,
                event_json TEXT NOT NULL
            );
            ",
        )?;
        Ok(Self { connection })
    }

    pub fn execute_json(&mut self, input: &[u8]) -> Vec<u8> {
        if input.len() > MAX_REQUEST_BYTES {
            return encode_response(&request_too_large_response());
        }

        let request = match serde_json::from_slice::<Request>(input) {
            Ok(request) => request,
            Err(_) => {
                return encode_response(&Response::error(
                    "INVALID_JSON",
                    "request must be valid UTF-8 JSON matching the probe contract",
                ));
            }
        };

        let response = match self.execute_request(request) {
            Ok(response) => response,
            Err(error) => map_core_error(error),
        };
        encode_response(&response)
    }

    pub fn execute_service_json(&mut self, input: &[u8]) -> Vec<u8> {
        if input.len() > MAX_REQUEST_BYTES {
            return encode_response(&request_too_large_response());
        }
        if let Ok(ServiceProbeRequest::CrashProbe {
            request_id,
            fact_id,
            value,
            crash_after,
        }) = serde_json::from_slice::<ServiceProbeRequest>(input)
        {
            let response =
                match self.apply(&request_id, &fact_id, &value, None, None, Some(crash_after)) {
                    Ok(response) => response,
                    Err(error) => map_core_error(error),
                };
            return encode_response(&response);
        }
        self.execute_json(input)
    }

    fn execute_request(&mut self, request: Request) -> Result<Response, CoreError> {
        match request {
            Request::Apply {
                request_id,
                fact_id,
                value,
                deadline_unix_ms,
                inject_failure,
            } => self.apply(
                &request_id,
                &fact_id,
                &value,
                deadline_unix_ms,
                inject_failure,
                None,
            ),
            Request::Inspect => self.inspect().map_err(Into::into),
            Request::Integrity => {
                let integrity = self.integrity_check()?;
                Ok(Response {
                    status: "ok".into(),
                    code: "INTEGRITY".into(),
                    message: None,
                    request_id: None,
                    fact_id: None,
                    replayed: None,
                    counts: None,
                    integrity: Some(integrity),
                    journal_mode: None,
                    busy_timeout_ms: None,
                    sqlite_version: None,
                })
            }
            Request::PanicProbe => {
                panic!("intentional SPIKE-CORE-PORTABILITY-001 panic probe")
            }
        }
    }

    fn apply(
        &mut self,
        request_id: &str,
        fact_id: &str,
        value: &str,
        deadline_unix_ms: Option<u64>,
        inject_failure: Option<FailureStage>,
        crash_after: Option<FailureStage>,
    ) -> Result<Response, CoreError> {
        if request_id.is_empty()
            || request_id.len() > MAX_IDENTIFIER_BYTES
            || fact_id.is_empty()
            || fact_id.len() > MAX_IDENTIFIER_BYTES
        {
            return Ok(Response::error(
                "INVALID_ARGUMENT",
                "request_id and fact_id must contain 1..=128 UTF-8 bytes",
            ));
        }
        if value.len() > MAX_VALUE_BYTES {
            return Ok(Response::error(
                "RESOURCE_EXHAUSTED",
                "value exceeds the 4096-byte probe limit",
            ));
        }
        if deadline_elapsed(deadline_unix_ms) {
            return Ok(Response::error(
                "DEADLINE_EXCEEDED",
                "request deadline elapsed before commit",
            ));
        }

        let canonical_payload = serde_json::to_string(&serde_json::json!({
            "fact_id": fact_id,
            "value": value,
        }))
        .expect("serializing strings to JSON cannot fail");

        let transaction = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        if deadline_elapsed(deadline_unix_ms) {
            return Ok(Response::error(
                "DEADLINE_EXCEEDED",
                "request deadline elapsed before commit",
            ));
        }

        let existing = transaction
            .query_row(
                "
                SELECT canonical_payload, response_json
                FROM probe_idempotency
                WHERE request_id = ?1
                ",
                params![request_id],
                |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)),
            )
            .optional()?;

        if let Some((stored_payload, stored_response)) = existing {
            if stored_payload != canonical_payload {
                return Ok(Response::error(
                    "IDEMPOTENCY_CONFLICT",
                    "request_id was already committed with a different payload",
                ));
            }

            let mut response: Response =
                serde_json::from_str(&stored_response).map_err(|_| CoreError::CorruptReceipt)?;
            response.code = "REPLAYED".into();
            response.replayed = Some(true);
            if deadline_elapsed(deadline_unix_ms) {
                return Ok(Response::error(
                    "DEADLINE_EXCEEDED",
                    "request deadline elapsed before commit",
                ));
            }
            transaction.commit()?;
            return Ok(response);
        }

        transaction.execute(
            "
            INSERT INTO probe_facts (fact_id, value, request_id)
            VALUES (?1, ?2, ?3)
            ",
            params![fact_id, value, request_id],
        )?;
        fault_if_requested(inject_failure, crash_after, FailureStage::AfterFact)?;

        let applied_response = Response::applied(request_id, fact_id);
        let stored_response = serde_json::to_string(&applied_response)
            .expect("serializing the stable response cannot fail");
        transaction.execute(
            "
            INSERT INTO probe_idempotency
                (request_id, canonical_payload, response_json)
            VALUES (?1, ?2, ?3)
            ",
            params![request_id, canonical_payload, stored_response],
        )?;
        fault_if_requested(inject_failure, crash_after, FailureStage::AfterIdempotency)?;

        transaction.execute(
            "
            INSERT INTO probe_audit (request_id, action, fact_id)
            VALUES (?1, 'apply_fact', ?2)
            ",
            params![request_id, fact_id],
        )?;
        fault_if_requested(inject_failure, crash_after, FailureStage::AfterAudit)?;

        let event_json = serde_json::to_string(&serde_json::json!({
            "event": "fact_applied",
            "fact_id": fact_id,
            "request_id": request_id,
        }))
        .expect("serializing strings to JSON cannot fail");
        transaction.execute(
            "
            INSERT INTO probe_outbox (request_id, event_json)
            VALUES (?1, ?2)
            ",
            params![request_id, event_json],
        )?;
        fault_if_requested(inject_failure, crash_after, FailureStage::AfterOutbox)?;

        if deadline_elapsed(deadline_unix_ms) {
            return Ok(Response::error(
                "DEADLINE_EXCEEDED",
                "request deadline elapsed before commit",
            ));
        }
        transaction.commit()?;
        Ok(applied_response)
    }

    fn inspect(&self) -> rusqlite::Result<Response> {
        let counts = Counts {
            facts: row_count(&self.connection, "probe_facts")?,
            idempotency: row_count(&self.connection, "probe_idempotency")?,
            audit: row_count(&self.connection, "probe_audit")?,
            outbox: row_count(&self.connection, "probe_outbox")?,
        };
        let journal_mode = self
            .connection
            .query_row("PRAGMA journal_mode", [], |row| row.get::<_, String>(0))?;
        let busy_timeout_ms = self
            .connection
            .query_row("PRAGMA busy_timeout", [], |row| row.get::<_, u64>(0))?;
        let integrity = self.integrity_check()?;
        let sqlite_version = self
            .connection
            .query_row("SELECT sqlite_version()", [], |row| row.get::<_, String>(0))?;

        Ok(Response {
            status: "ok".into(),
            code: "INSPECT".into(),
            message: None,
            request_id: None,
            fact_id: None,
            replayed: None,
            counts: Some(counts),
            integrity: Some(integrity),
            journal_mode: Some(journal_mode),
            busy_timeout_ms: Some(busy_timeout_ms),
            sqlite_version: Some(sqlite_version),
        })
    }

    fn integrity_check(&self) -> rusqlite::Result<String> {
        self.connection
            .query_row("PRAGMA integrity_check", [], |row| row.get::<_, String>(0))
    }
}

pub fn request_too_large_response() -> Response {
    Response::error(
        "REQUEST_TOO_LARGE",
        "NDJSON request exceeds the 65536-byte probe limit",
    )
}

pub fn panic_contained_response() -> Response {
    Response::error(
        "PANIC_CONTAINED",
        "handler panic was contained at the adapter boundary",
    )
}

pub fn encode_response(response: &Response) -> Vec<u8> {
    serde_json::to_vec(response).unwrap_or_else(|_| {
        br#"{"status":"error","code":"SERIALIZATION_FAILURE","message":"response serialization failed"}"#
            .to_vec()
    })
}

fn row_count(connection: &Connection, table: &str) -> rusqlite::Result<i64> {
    let sql = format!("SELECT COUNT(*) FROM {table}");
    connection.query_row(&sql, [], |row| row.get(0))
}

fn fault_if_requested(
    rollback_requested: Option<FailureStage>,
    crash_requested: Option<FailureStage>,
    current: FailureStage,
) -> Result<(), CoreError> {
    if crash_requested.is_some_and(|stage| stage.label() == current.label()) {
        std::process::abort();
    }
    if rollback_requested.is_some_and(|stage| stage.label() == current.label()) {
        return Err(CoreError::Injected(current));
    }
    Ok(())
}

fn map_core_error(error: CoreError) -> Response {
    match error {
        CoreError::Injected(stage) => Response::error(
            "INJECTED_FAILURE",
            &format!("probe failure injected at {}", stage.label()),
        ),
        CoreError::Sqlite(error)
            if matches!(
                error.sqlite_error_code(),
                Some(ErrorCode::DatabaseBusy | ErrorCode::DatabaseLocked)
            ) =>
        {
            Response::error(
                "SQLITE_BUSY",
                "writer lock was not acquired within the finite busy timeout",
            )
        }
        CoreError::Sqlite(_) => Response::error("STORAGE_ERROR", "SQLite operation failed"),
        CoreError::CorruptReceipt => Response::error(
            "CORRUPT_IDEMPOTENCY_RECEIPT",
            "stored idempotency response is not valid probe JSON",
        ),
    }
}

fn now_unix_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .try_into()
        .unwrap_or(u64::MAX)
}

fn deadline_elapsed(deadline_unix_ms: Option<u64>) -> bool {
    deadline_unix_ms.is_some_and(|deadline| now_unix_ms() > deadline)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Value;
    use std::fs;
    use std::path::PathBuf;
    use std::sync::atomic::{AtomicU64, Ordering};
    use std::time::{Duration, Instant};

    static NEXT_TEMP_ID: AtomicU64 = AtomicU64::new(1);

    struct TempDatabase {
        path: PathBuf,
    }

    impl TempDatabase {
        fn new(label: &str) -> Self {
            let unique = NEXT_TEMP_ID.fetch_add(1, Ordering::Relaxed);
            let path = std::env::temp_dir().join(format!(
                "nabla-core-portability-{label}-{}-{unique}.sqlite3",
                std::process::id()
            ));
            Self { path }
        }
    }

    impl Drop for TempDatabase {
        fn drop(&mut self) {
            for suffix in ["", "-wal", "-shm"] {
                let candidate = PathBuf::from(format!("{}{suffix}", self.path.display()));
                let _ = fs::remove_file(candidate);
            }
        }
    }

    fn response(core: &mut Core, request: &str) -> Value {
        serde_json::from_slice(&core.execute_json(request.as_bytes())).unwrap()
    }

    fn counts(core: &mut Core) -> Counts {
        serde_json::from_value(response(core, r#"{"op":"inspect"}"#)["counts"].clone()).unwrap()
    }

    #[test]
    fn apply_replay_and_conflict_have_stable_semantics() {
        let database = TempDatabase::new("replay");
        let mut core = Core::open(&database.path).unwrap();
        let apply = r#"{"op":"apply","request_id":"request-1","fact_id":"fact-1","value":"alpha"}"#;

        let first = response(&mut core, apply);
        assert_eq!(first["code"], "APPLIED");
        assert_eq!(first["replayed"], false);

        let replay = response(&mut core, apply);
        assert_eq!(replay["code"], "REPLAYED");
        assert_eq!(replay["replayed"], true);

        let conflict = response(
            &mut core,
            r#"{"op":"apply","request_id":"request-1","fact_id":"fact-1","value":"different"}"#,
        );
        assert_eq!(conflict["code"], "IDEMPOTENCY_CONFLICT");
        assert_eq!(
            counts(&mut core),
            Counts {
                facts: 1,
                idempotency: 1,
                audit: 1,
                outbox: 1,
            }
        );
    }

    #[test]
    fn every_injected_stage_rolls_back_the_whole_command() {
        for stage in [
            "after_fact",
            "after_idempotency",
            "after_audit",
            "after_outbox",
        ] {
            let database = TempDatabase::new(stage);
            let mut core = Core::open(&database.path).unwrap();
            let request = format!(
                r#"{{"op":"apply","request_id":"request-{stage}","fact_id":"fact-{stage}","value":"alpha","inject_failure":"{stage}"}}"#
            );

            let failed = response(&mut core, &request);
            assert_eq!(failed["code"], "INJECTED_FAILURE");
            assert_eq!(
                counts(&mut core),
                Counts {
                    facts: 0,
                    idempotency: 0,
                    audit: 0,
                    outbox: 0,
                }
            );
        }
    }

    #[test]
    fn sqlite_writer_contention_has_a_finite_timeout() {
        let database = TempDatabase::new("busy");
        let mut core = Core::open(&database.path).unwrap();
        let blocker = Connection::open(&database.path).unwrap();
        blocker.execute_batch("BEGIN IMMEDIATE").unwrap();

        let started = Instant::now();
        let busy = response(
            &mut core,
            r#"{"op":"apply","request_id":"request-busy","fact_id":"fact-busy","value":"alpha"}"#,
        );
        let elapsed = started.elapsed();

        assert_eq!(busy["code"], "SQLITE_BUSY");
        assert!(elapsed < Duration::from_secs(3));
        assert_eq!(counts(&mut core).facts, 0);

        blocker.execute_batch("ROLLBACK").unwrap();
        let applied = response(
            &mut core,
            r#"{"op":"apply","request_id":"request-busy","fact_id":"fact-busy","value":"alpha"}"#,
        );
        assert_eq!(applied["code"], "APPLIED");
    }

    #[test]
    fn inspect_reports_integrity_limits_and_consistent_idle_counts() {
        let database = TempDatabase::new("inspect");
        let mut core = Core::open(&database.path).unwrap();
        let inspect = response(&mut core, r#"{"op":"inspect"}"#);

        assert_eq!(inspect["code"], "INSPECT");
        assert_eq!(inspect["integrity"], "ok");
        assert_eq!(inspect["journal_mode"], "wal");
        assert_eq!(inspect["busy_timeout_ms"], BUSY_TIMEOUT_MS);
        assert!(
            inspect["sqlite_version"]
                .as_str()
                .is_some_and(|value| !value.is_empty())
        );
        assert_eq!(inspect["counts"]["facts"], 0);

        let integrity = response(&mut core, r#"{"op":"integrity"}"#);
        assert_eq!(integrity["code"], "INTEGRITY");
        assert_eq!(integrity["integrity"], "ok");
    }

    #[test]
    fn malformed_expired_and_oversized_requests_are_bounded() {
        let database = TempDatabase::new("limits");
        let mut core = Core::open(&database.path).unwrap();

        let malformed = response(&mut core, "not-json");
        assert_eq!(malformed["code"], "INVALID_JSON");

        let expired = response(
            &mut core,
            r#"{"op":"apply","request_id":"expired","fact_id":"fact","value":"alpha","deadline_unix_ms":0}"#,
        );
        assert_eq!(expired["code"], "DEADLINE_EXCEEDED");

        let oversized = core.execute_json(&vec![b'x'; MAX_REQUEST_BYTES + 1]);
        let oversized: Value = serde_json::from_slice(&oversized).unwrap();
        assert_eq!(oversized["code"], "REQUEST_TOO_LARGE");
        assert_eq!(counts(&mut core).facts, 0);
    }

    #[test]
    fn deadline_is_rechecked_after_waiting_for_the_writer_lock() {
        let database = TempDatabase::new("deadline-after-lock");
        let mut core = Core::open(&database.path).unwrap();
        let blocker_path = database.path.clone();
        let (ready_sender, ready_receiver) = std::sync::mpsc::channel();
        let blocker = std::thread::spawn(move || {
            let connection = Connection::open(blocker_path).unwrap();
            connection.execute_batch("BEGIN IMMEDIATE").unwrap();
            ready_sender.send(()).unwrap();
            std::thread::sleep(Duration::from_millis(100));
            connection.execute_batch("ROLLBACK").unwrap();
        });
        ready_receiver.recv().unwrap();

        let deadline = now_unix_ms() + 25;
        let request = format!(
            r#"{{"op":"apply","request_id":"late","fact_id":"late","value":"alpha","deadline_unix_ms":{deadline}}}"#
        );
        let response = response(&mut core, &request);
        blocker.join().unwrap();

        assert_eq!(response["code"], "DEADLINE_EXCEEDED");
        assert_eq!(counts(&mut core).facts, 0);
    }

    #[test]
    fn process_crash_hook_is_not_part_of_the_common_core_contract() {
        let database = TempDatabase::new("fault-modes");
        let mut core = Core::open(&database.path).unwrap();
        let response = response(
            &mut core,
            r#"{"op":"crash_probe","request_id":"request-1","fact_id":"fact-1","value":"alpha","crash_after":"after_fact"}"#,
        );
        assert_eq!(response["code"], "INVALID_JSON");
        assert_eq!(counts(&mut core).facts, 0);
    }

    #[test]
    fn invalid_json_response_is_byte_stable() {
        let database = TempDatabase::new("stable-json");
        let mut core = Core::open(&database.path).unwrap();
        assert_eq!(
            core.execute_json(b"{"),
            br#"{"status":"error","code":"INVALID_JSON","message":"request must be valid UTF-8 JSON matching the probe contract"}"#
        );
    }
}
