"""Test-only mechanics for the bounded revision/outbox/replay spike.

Nothing in this module is a production persistence, ID, or synchronization
choice. The deliberately small model exists only to make the task's semantic
claims executable and reproducible.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence


EVENT_TYPE = "nabla.entity.revision-committed"
EVENT_VERSION = 1


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_text(canonical_json(value))


def stable_id(kind: str, origin_device: str, local_sequence: int) -> str:
    """Return a deterministic fixture ID, not a proposed production encoding."""

    material = canonical_json(
        {
            "fixture_encoding": "test-sha256-prefix-v1",
            "kind": kind,
            "local_sequence": local_sequence,
            "origin_device": origin_device,
        }
    )
    return f"{kind}_{sha256_text(material)[:32]}"


def command_fingerprint(
    *,
    entity_id: str,
    exact_version: str,
    contract_hash: str,
    payload: dict[str, Any],
    expected_revisions: Sequence[str],
    merge_intent: bool,
    tombstone: bool,
    stable_options: dict[str, Any],
) -> str:
    return sha256_json(
        {
            "contract_hash": contract_hash,
            "entity_id": entity_id,
            "exact_version": exact_version,
            "expected_revisions": sorted(expected_revisions),
            "merge_intent": merge_intent,
            "payload": payload,
            "stable_options": stable_options,
            "tombstone": tombstone,
        }
    )


class RevisionConflict(RuntimeError):
    code = "REVISION_CONFLICT"

    def __init__(self, current_heads: Sequence[str]):
        super().__init__(self.code)
        self.current_heads = tuple(sorted(current_heads))


class IdempotencyConflict(RuntimeError):
    code = "IDEMPOTENCY_CONFLICT"

    def __init__(self, committed_command_id: str):
        super().__init__(self.code)
        self.committed_command_id = committed_command_id


class EventConflict(RuntimeError):
    code = "EVENT_CONFLICT"


@dataclass(frozen=True)
class CommitResult:
    receipt: dict[str, Any]
    replayed: bool


@dataclass(frozen=True)
class DeliveryResult:
    code: str
    event_id: str
    revision_id: str
    missing_parents: tuple[str, ...] = ()
    effect_digest: str | None = None


class ExperimentStore:
    """A deliberately narrow SQLite adapter used only by the spike."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.connection = sqlite3.connect(str(self.path), isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA synchronous = FULL")
        self.connection.execute("PRAGMA busy_timeout = 5000")
        self._create_schema()

    def __enter__(self) -> "ExperimentStore":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS device_counters (
                device_id TEXT PRIMARY KEY,
                last_sequence INTEGER NOT NULL CHECK (last_sequence > 0)
            );

            CREATE TABLE IF NOT EXISTS revisions (
                revision_id TEXT PRIMARY KEY,
                entity_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                tombstone INTEGER NOT NULL CHECK (tombstone IN (0, 1)),
                origin_device TEXT NOT NULL,
                device_sequence INTEGER NOT NULL CHECK (device_sequence > 0),
                logical_sequence INTEGER NOT NULL CHECK (logical_sequence > 0),
                exact_version TEXT NOT NULL,
                contract_hash TEXT NOT NULL,
                parentage_sealed INTEGER NOT NULL DEFAULT 0
                    CHECK (parentage_sealed IN (0, 1)),
                UNIQUE (origin_device, device_sequence)
            );

            CREATE TABLE IF NOT EXISTS revision_parents (
                revision_id TEXT NOT NULL,
                parent_revision_id TEXT NOT NULL,
                parent_ordinal INTEGER NOT NULL,
                PRIMARY KEY (revision_id, parent_revision_id),
                UNIQUE (revision_id, parent_ordinal),
                FOREIGN KEY (revision_id) REFERENCES revisions(revision_id)
            );

            CREATE TABLE IF NOT EXISTS heads (
                entity_id TEXT NOT NULL,
                revision_id TEXT NOT NULL,
                PRIMARY KEY (entity_id, revision_id),
                FOREIGN KEY (revision_id) REFERENCES revisions(revision_id)
            );

            CREATE TABLE IF NOT EXISTS command_receipts (
                command_id TEXT PRIMARY KEY,
                verified_actor TEXT NOT NULL,
                origin_device TEXT NOT NULL,
                capability_id TEXT NOT NULL,
                major_version INTEGER NOT NULL,
                idempotency_key TEXT NOT NULL,
                initial_request_id TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                exact_version TEXT NOT NULL,
                contract_hash TEXT NOT NULL,
                receipt_json TEXT NOT NULL,
                UNIQUE (
                    verified_actor,
                    origin_device,
                    capability_id,
                    major_version,
                    idempotency_key
                )
            );

            CREATE TABLE IF NOT EXISTS outbox (
                event_id TEXT PRIMARY KEY,
                origin_device TEXT NOT NULL,
                device_sequence INTEGER NOT NULL,
                entity_id TEXT NOT NULL,
                revision_id TEXT NOT NULL UNIQUE,
                event_type TEXT NOT NULL,
                event_version INTEGER NOT NULL,
                envelope_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('pending', 'acknowledged')),
                delivery_attempts INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (revision_id) REFERENCES revisions(revision_id),
                UNIQUE (origin_device, device_sequence)
            );

            CREATE TABLE IF NOT EXISTS consumer_revisions (
                consumer_id TEXT NOT NULL,
                revision_id TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                tombstone INTEGER NOT NULL CHECK (tombstone IN (0, 1)),
                origin_device TEXT NOT NULL,
                device_sequence INTEGER NOT NULL,
                logical_sequence INTEGER NOT NULL,
                parentage_sealed INTEGER NOT NULL DEFAULT 0
                    CHECK (parentage_sealed IN (0, 1)),
                PRIMARY KEY (consumer_id, revision_id)
            );

            CREATE TABLE IF NOT EXISTS consumer_parents (
                consumer_id TEXT NOT NULL,
                revision_id TEXT NOT NULL,
                parent_revision_id TEXT NOT NULL,
                parent_ordinal INTEGER NOT NULL,
                PRIMARY KEY (consumer_id, revision_id, parent_revision_id)
            );

            CREATE TABLE IF NOT EXISTS consumer_heads (
                consumer_id TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                revision_id TEXT NOT NULL,
                PRIMARY KEY (consumer_id, entity_id, revision_id)
            );

            CREATE TABLE IF NOT EXISTS consumer_effects (
                consumer_id TEXT NOT NULL,
                revision_id TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                tombstone INTEGER NOT NULL CHECK (tombstone IN (0, 1)),
                effect_digest TEXT NOT NULL,
                PRIMARY KEY (consumer_id, revision_id)
            );

            CREATE TABLE IF NOT EXISTS consumer_receipts (
                consumer_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                revision_id TEXT NOT NULL,
                envelope_hash TEXT NOT NULL,
                effect_digest TEXT NOT NULL,
                delivery_count INTEGER NOT NULL CHECK (delivery_count > 0),
                PRIMARY KEY (consumer_id, event_id)
            );

            CREATE TABLE IF NOT EXISTS consumer_pending (
                consumer_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                revision_id TEXT NOT NULL,
                envelope_json TEXT NOT NULL,
                reason TEXT NOT NULL,
                missing_parents_json TEXT NOT NULL,
                attempt_count INTEGER NOT NULL CHECK (attempt_count > 0),
                PRIMARY KEY (consumer_id, event_id)
            );

            CREATE TRIGGER IF NOT EXISTS revisions_reject_update
            BEFORE UPDATE ON revisions
            WHEN NOT (
                OLD.parentage_sealed = 0
                AND NEW.parentage_sealed = 1
                AND OLD.revision_id = NEW.revision_id
                AND OLD.entity_id = NEW.entity_id
                AND OLD.payload_json = NEW.payload_json
                AND OLD.tombstone = NEW.tombstone
                AND OLD.origin_device = NEW.origin_device
                AND OLD.device_sequence = NEW.device_sequence
                AND OLD.logical_sequence = NEW.logical_sequence
                AND OLD.exact_version = NEW.exact_version
                AND OLD.contract_hash = NEW.contract_hash
            )
            BEGIN
                SELECT RAISE(ABORT, 'immutable revision');
            END;

            CREATE TRIGGER IF NOT EXISTS revisions_reject_delete
            BEFORE DELETE ON revisions
            BEGIN
                SELECT RAISE(ABORT, 'immutable revision');
            END;

            CREATE TRIGGER IF NOT EXISTS revision_parents_reject_update
            BEFORE UPDATE ON revision_parents
            BEGIN
                SELECT RAISE(ABORT, 'immutable revision parentage');
            END;

            CREATE TRIGGER IF NOT EXISTS revision_parents_reject_insert
            BEFORE INSERT ON revision_parents
            WHEN COALESCE(
                (
                    SELECT parentage_sealed
                    FROM revisions
                    WHERE revision_id = NEW.revision_id
                ),
                1
            ) != 0
            BEGIN
                SELECT RAISE(ABORT, 'immutable revision parentage');
            END;

            CREATE TRIGGER IF NOT EXISTS revision_parents_reject_delete
            BEFORE DELETE ON revision_parents
            BEGIN
                SELECT RAISE(ABORT, 'immutable revision parentage');
            END;

            CREATE TRIGGER IF NOT EXISTS consumer_revisions_reject_update
            BEFORE UPDATE ON consumer_revisions
            WHEN NOT (
                OLD.parentage_sealed = 0
                AND NEW.parentage_sealed = 1
                AND OLD.consumer_id = NEW.consumer_id
                AND OLD.revision_id = NEW.revision_id
                AND OLD.entity_id = NEW.entity_id
                AND OLD.payload_json = NEW.payload_json
                AND OLD.tombstone = NEW.tombstone
                AND OLD.origin_device = NEW.origin_device
                AND OLD.device_sequence = NEW.device_sequence
                AND OLD.logical_sequence = NEW.logical_sequence
            )
            BEGIN
                SELECT RAISE(ABORT, 'immutable consumer revision');
            END;

            CREATE TRIGGER IF NOT EXISTS consumer_revisions_reject_delete
            BEFORE DELETE ON consumer_revisions
            BEGIN
                SELECT RAISE(ABORT, 'immutable consumer revision');
            END;

            CREATE TRIGGER IF NOT EXISTS consumer_parents_reject_update
            BEFORE UPDATE ON consumer_parents
            BEGIN
                SELECT RAISE(ABORT, 'immutable consumer parentage');
            END;

            CREATE TRIGGER IF NOT EXISTS consumer_parents_reject_insert
            BEFORE INSERT ON consumer_parents
            WHEN COALESCE(
                (
                    SELECT parentage_sealed
                    FROM consumer_revisions
                    WHERE consumer_id = NEW.consumer_id
                      AND revision_id = NEW.revision_id
                ),
                1
            ) != 0
            BEGIN
                SELECT RAISE(ABORT, 'immutable consumer parentage');
            END;

            CREATE TRIGGER IF NOT EXISTS consumer_parents_reject_delete
            BEFORE DELETE ON consumer_parents
            BEGIN
                SELECT RAISE(ABORT, 'immutable consumer parentage');
            END;
            """
        )

    def _next_sequence(self, origin_device: str) -> int:
        row = self.connection.execute(
            "SELECT last_sequence FROM device_counters WHERE device_id = ?",
            (origin_device,),
        ).fetchone()
        if row is None:
            sequence = 1
            self.connection.execute(
                "INSERT INTO device_counters(device_id, last_sequence) VALUES (?, ?)",
                (origin_device, sequence),
            )
        else:
            sequence = int(row["last_sequence"]) + 1
            self.connection.execute(
                "UPDATE device_counters SET last_sequence = ? WHERE device_id = ?",
                (sequence, origin_device),
            )
        return sequence

    def current_heads(self, entity_id: str) -> list[str]:
        return [
            str(row["revision_id"])
            for row in self.connection.execute(
                """
                SELECT revision_id
                FROM heads
                WHERE entity_id = ?
                ORDER BY revision_id
                """,
                (entity_id,),
            )
        ]

    def commit_command(
        self,
        *,
        verified_actor: str,
        origin_device: str,
        capability_id: str,
        major_version: int,
        exact_version: str,
        contract_hash: str,
        idempotency_key: str,
        command_id: str,
        request_id: str,
        entity_id: str,
        payload: dict[str, Any],
        expected_revisions: Sequence[str],
        merge_intent: bool = False,
        tombstone: bool = False,
        stable_options: dict[str, Any] | None = None,
        before_commit: Callable[[], None] | None = None,
    ) -> CommitResult:
        options = stable_options or {}
        expected = sorted(expected_revisions)
        fingerprint = command_fingerprint(
            entity_id=entity_id,
            exact_version=exact_version,
            contract_hash=contract_hash,
            payload=payload,
            expected_revisions=expected,
            merge_intent=merge_intent,
            tombstone=tombstone,
            stable_options=options,
        )
        scope = (
            verified_actor,
            origin_device,
            capability_id,
            major_version,
            idempotency_key,
        )

        self.connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self.connection.execute(
                """
                SELECT command_id, fingerprint, receipt_json
                FROM command_receipts
                WHERE verified_actor = ?
                  AND origin_device = ?
                  AND capability_id = ?
                  AND major_version = ?
                  AND idempotency_key = ?
                """,
                scope,
            ).fetchone()
            if existing is not None:
                if str(existing["fingerprint"]) != fingerprint:
                    raise IdempotencyConflict(str(existing["command_id"]))
                receipt = json.loads(str(existing["receipt_json"]))
                self.connection.execute("COMMIT")
                return CommitResult(receipt=receipt, replayed=True)

            heads = self.current_heads(entity_id)
            if merge_intent:
                valid_expectation = len(expected) >= 2 and expected == heads
            elif heads:
                valid_expectation = len(heads) == 1 and expected == heads
            else:
                valid_expectation = expected == []
            if not valid_expectation:
                raise RevisionConflict(heads)

            sequence = self._next_sequence(origin_device)
            if expected:
                placeholders = ",".join("?" for _ in expected)
                parent_rows = self.connection.execute(
                    f"""
                    SELECT logical_sequence
                    FROM revisions
                    WHERE revision_id IN ({placeholders})
                    ORDER BY revision_id
                    """,
                    tuple(expected),
                ).fetchall()
                if len(parent_rows) != len(expected):
                    raise RevisionConflict(heads)
                logical_sequence = max(
                    int(row["logical_sequence"]) for row in parent_rows
                ) + 1
            else:
                logical_sequence = 1
            revision_id = stable_id("revision", origin_device, sequence)
            event_id = stable_id("event", origin_device, sequence)
            payload_json = canonical_json(payload)

            self.connection.execute(
                """
                INSERT INTO revisions(
                    revision_id, entity_id, payload_json, tombstone,
                    origin_device, device_sequence, logical_sequence,
                    exact_version, contract_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revision_id,
                    entity_id,
                    payload_json,
                    int(tombstone),
                    origin_device,
                    sequence,
                    logical_sequence,
                    exact_version,
                    contract_hash,
                ),
            )
            for ordinal, parent in enumerate(expected):
                self.connection.execute(
                    """
                    INSERT INTO revision_parents(
                        revision_id, parent_revision_id, parent_ordinal
                    ) VALUES (?, ?, ?)
                    """,
                    (revision_id, parent, ordinal),
                )
                self.connection.execute(
                    "DELETE FROM heads WHERE entity_id = ? AND revision_id = ?",
                    (entity_id, parent),
                )
            self.connection.execute(
                "UPDATE revisions SET parentage_sealed = 1 WHERE revision_id = ?",
                (revision_id,),
            )
            self.connection.execute(
                "INSERT INTO heads(entity_id, revision_id) VALUES (?, ?)",
                (entity_id, revision_id),
            )

            envelope = {
                "contract_hash": contract_hash,
                "device_sequence": sequence,
                "entity_id": entity_id,
                "event_id": event_id,
                "event_type": EVENT_TYPE,
                "event_version": EVENT_VERSION,
                "exact_version": exact_version,
                "logical_sequence": logical_sequence,
                "origin_device": origin_device,
                "parents": expected,
                "payload": payload,
                "revision_id": revision_id,
                "tombstone": tombstone,
            }
            self.connection.execute(
                """
                INSERT INTO outbox(
                    event_id, origin_device, device_sequence, entity_id,
                    revision_id, event_type, event_version, envelope_json,
                    status, delivery_attempts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0)
                """,
                (
                    event_id,
                    origin_device,
                    sequence,
                    entity_id,
                    revision_id,
                    EVENT_TYPE,
                    EVENT_VERSION,
                    canonical_json(envelope),
                ),
            )
            receipt = {
                "command_id": command_id,
                "contract_hash": contract_hash,
                "entity_id": entity_id,
                "event_id": event_id,
                "exact_version": exact_version,
                "heads": [revision_id],
                "revision_id": revision_id,
                "status": "COMMITTED",
            }
            self.connection.execute(
                """
                INSERT INTO command_receipts(
                    command_id, verified_actor, origin_device, capability_id,
                    major_version, idempotency_key, initial_request_id,
                    fingerprint, exact_version, contract_hash, receipt_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    command_id,
                    verified_actor,
                    origin_device,
                    capability_id,
                    major_version,
                    idempotency_key,
                    request_id,
                    fingerprint,
                    exact_version,
                    contract_hash,
                    canonical_json(receipt),
                ),
            )
            if before_commit is not None:
                before_commit()
            self.connection.execute("COMMIT")
            return CommitResult(receipt=receipt, replayed=False)
        except BaseException:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise

    def seed_source_event(self, event: dict[str, Any]) -> None:
        """Seed an already accepted causal event into another offline store."""

        self.connection.execute("BEGIN IMMEDIATE")
        try:
            revision_id = str(event["revision_id"])
            if self.connection.execute(
                "SELECT 1 FROM revisions WHERE revision_id = ?", (revision_id,)
            ).fetchone():
                self.connection.execute("COMMIT")
                return
            parents = [str(value) for value in event["parents"]]
            missing = [
                parent
                for parent in parents
                if self.connection.execute(
                    "SELECT 1 FROM revisions WHERE revision_id = ?", (parent,)
                ).fetchone()
                is None
            ]
            if missing:
                raise ValueError(f"seed requires causal parents: {sorted(missing)}")
            self.connection.execute(
                """
                INSERT INTO revisions(
                    revision_id, entity_id, payload_json, tombstone,
                    origin_device, device_sequence, logical_sequence,
                    exact_version, contract_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revision_id,
                    event["entity_id"],
                    canonical_json(event["payload"]),
                    int(bool(event["tombstone"])),
                    event["origin_device"],
                    int(event["device_sequence"]),
                    int(event["logical_sequence"]),
                    event["exact_version"],
                    event["contract_hash"],
                ),
            )
            for ordinal, parent in enumerate(sorted(parents)):
                self.connection.execute(
                    """
                    INSERT INTO revision_parents(
                        revision_id, parent_revision_id, parent_ordinal
                    ) VALUES (?, ?, ?)
                    """,
                    (revision_id, parent, ordinal),
                )
                self.connection.execute(
                    "DELETE FROM heads WHERE entity_id = ? AND revision_id = ?",
                    (event["entity_id"], parent),
                )
            self.connection.execute(
                "UPDATE revisions SET parentage_sealed = 1 WHERE revision_id = ?",
                (revision_id,),
            )
            self.connection.execute(
                "INSERT INTO heads(entity_id, revision_id) VALUES (?, ?)",
                (event["entity_id"], revision_id),
            )
            self.connection.execute("COMMIT")
        except BaseException:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise

    def outbox_event(self, event_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT envelope_json FROM outbox WHERE event_id = ?", (event_id,)
        ).fetchone()
        if row is None:
            raise KeyError(event_id)
        return json.loads(str(row["envelope_json"]))

    def first_pending_outbox_event(self) -> dict[str, Any]:
        row = self.connection.execute(
            """
            SELECT envelope_json
            FROM outbox
            WHERE status = 'pending'
            ORDER BY origin_device, device_sequence, event_id
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            raise LookupError("no pending outbox event")
        return json.loads(str(row["envelope_json"]))

    def record_outbox_attempt(self, event_id: str) -> None:
        self.connection.execute(
            """
            UPDATE outbox
            SET delivery_attempts = delivery_attempts + 1
            WHERE event_id = ?
            """,
            (event_id,),
        )

    def acknowledge_outbox(self, event_id: str) -> None:
        self.connection.execute(
            "UPDATE outbox SET status = 'acknowledged' WHERE event_id = ?",
            (event_id,),
        )

    def outbox_row(self, event_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            """
            SELECT event_id, status, delivery_attempts
            FROM outbox
            WHERE event_id = ?
            """,
            (event_id,),
        ).fetchone()
        if row is None:
            raise KeyError(event_id)
        return dict(row)

    def apply_event(
        self, consumer_id: str, event: dict[str, Any]
    ) -> DeliveryResult:
        event_id = str(event["event_id"])
        revision_id = str(event["revision_id"])
        envelope_json = canonical_json(event)
        envelope_hash = sha256_text(envelope_json)
        parents = sorted(str(value) for value in event["parents"])

        self.connection.execute("BEGIN IMMEDIATE")
        try:
            receipt = self.connection.execute(
                """
                SELECT revision_id, envelope_hash, effect_digest
                FROM consumer_receipts
                WHERE consumer_id = ? AND event_id = ?
                """,
                (consumer_id, event_id),
            ).fetchone()
            if receipt is not None:
                if (
                    str(receipt["revision_id"]) != revision_id
                    or str(receipt["envelope_hash"]) != envelope_hash
                ):
                    raise EventConflict(event_id)
                self.connection.execute(
                    """
                    UPDATE consumer_receipts
                    SET delivery_count = delivery_count + 1
                    WHERE consumer_id = ? AND event_id = ?
                    """,
                    (consumer_id, event_id),
                )
                self.connection.execute("COMMIT")
                return DeliveryResult(
                    code="DUPLICATE_SUPPRESSED",
                    event_id=event_id,
                    revision_id=revision_id,
                    effect_digest=str(receipt["effect_digest"]),
                )

            missing = [
                parent
                for parent in parents
                if self.connection.execute(
                    """
                    SELECT 1
                    FROM consumer_revisions
                    WHERE consumer_id = ? AND revision_id = ?
                    """,
                    (consumer_id, parent),
                ).fetchone()
                is None
            ]
            if missing:
                self.connection.execute(
                    """
                    INSERT INTO consumer_pending(
                        consumer_id, event_id, revision_id, envelope_json,
                        reason, missing_parents_json, attempt_count
                    ) VALUES (?, ?, ?, ?, 'MISSING_PARENT', ?, 1)
                    ON CONFLICT(consumer_id, event_id) DO UPDATE SET
                        reason = excluded.reason,
                        missing_parents_json = excluded.missing_parents_json,
                        attempt_count = consumer_pending.attempt_count + 1
                    """,
                    (
                        consumer_id,
                        event_id,
                        revision_id,
                        envelope_json,
                        canonical_json(sorted(missing)),
                    ),
                )
                self.connection.execute("COMMIT")
                return DeliveryResult(
                    code="MISSING_PARENT",
                    event_id=event_id,
                    revision_id=revision_id,
                    missing_parents=tuple(sorted(missing)),
                )

            existing_revision = self.connection.execute(
                """
                SELECT payload_json, tombstone, origin_device, device_sequence
                FROM consumer_revisions
                WHERE consumer_id = ? AND revision_id = ?
                """,
                (consumer_id, revision_id),
            ).fetchone()
            if existing_revision is not None:
                raise EventConflict(event_id)

            payload_json = canonical_json(event["payload"])
            effect_digest = sha256_json(
                {
                    "consumer_id": consumer_id,
                    "entity_id": event["entity_id"],
                    "payload": event["payload"],
                    "revision_id": revision_id,
                    "tombstone": bool(event["tombstone"]),
                }
            )
            self.connection.execute(
                """
                INSERT INTO consumer_revisions(
                    consumer_id, revision_id, entity_id, payload_json,
                    tombstone, origin_device, device_sequence, logical_sequence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    consumer_id,
                    revision_id,
                    event["entity_id"],
                    payload_json,
                    int(bool(event["tombstone"])),
                    event["origin_device"],
                    int(event["device_sequence"]),
                    int(event["logical_sequence"]),
                ),
            )
            for ordinal, parent in enumerate(parents):
                self.connection.execute(
                    """
                    INSERT INTO consumer_parents(
                        consumer_id, revision_id, parent_revision_id,
                        parent_ordinal
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (consumer_id, revision_id, parent, ordinal),
                )
                self.connection.execute(
                    """
                    DELETE FROM consumer_heads
                    WHERE consumer_id = ?
                      AND entity_id = ?
                      AND revision_id = ?
                    """,
                    (consumer_id, event["entity_id"], parent),
                )
            self.connection.execute(
                """
                UPDATE consumer_revisions
                SET parentage_sealed = 1
                WHERE consumer_id = ? AND revision_id = ?
                """,
                (consumer_id, revision_id),
            )
            self.connection.execute(
                """
                INSERT INTO consumer_heads(consumer_id, entity_id, revision_id)
                VALUES (?, ?, ?)
                """,
                (consumer_id, event["entity_id"], revision_id),
            )
            self.connection.execute(
                """
                INSERT INTO consumer_effects(
                    consumer_id, revision_id, entity_id, payload_json,
                    tombstone, effect_digest
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    consumer_id,
                    revision_id,
                    event["entity_id"],
                    payload_json,
                    int(bool(event["tombstone"])),
                    effect_digest,
                ),
            )
            self.connection.execute(
                """
                INSERT INTO consumer_receipts(
                    consumer_id, event_id, revision_id, envelope_hash,
                    effect_digest, delivery_count
                ) VALUES (?, ?, ?, ?, ?, 1)
                """,
                (
                    consumer_id,
                    event_id,
                    revision_id,
                    envelope_hash,
                    effect_digest,
                ),
            )
            self.connection.execute(
                "DELETE FROM consumer_pending WHERE consumer_id = ? AND event_id = ?",
                (consumer_id, event_id),
            )
            self.connection.execute("COMMIT")
            return DeliveryResult(
                code="APPLIED",
                event_id=event_id,
                revision_id=revision_id,
                effect_digest=effect_digest,
            )
        except BaseException:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise

    def source_counts(self) -> dict[str, int]:
        tables = ["command_receipts", "heads", "outbox", "revisions"]
        return {
            table: int(
                self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            )
            for table in tables
        }

    def consumer_counts(self, consumer_id: str) -> dict[str, int]:
        tables = [
            "consumer_effects",
            "consumer_heads",
            "consumer_pending",
            "consumer_receipts",
            "consumer_revisions",
        ]
        return {
            table: int(
                self.connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE consumer_id = ?",
                    (consumer_id,),
                ).fetchone()[0]
            )
            for table in tables
        }

    def command_rows(self) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.connection.execute(
                """
                SELECT command_id, verified_actor, origin_device,
                       capability_id, major_version, idempotency_key,
                       initial_request_id, fingerprint, exact_version,
                       contract_hash, receipt_json
                FROM command_receipts
                ORDER BY verified_actor, origin_device, capability_id,
                         major_version, idempotency_key
                """
            )
        ]

    def revision_payload(self, revision_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT payload_json FROM revisions WHERE revision_id = ?",
            (revision_id,),
        ).fetchone()
        if row is None:
            raise KeyError(revision_id)
        return json.loads(str(row["payload_json"]))

    def attempt_revision_update(self, revision_id: str) -> str:
        try:
            self.connection.execute(
                "UPDATE revisions SET payload_json = '{}' WHERE revision_id = ?",
                (revision_id,),
            )
        except sqlite3.IntegrityError as error:
            return str(error)
        raise AssertionError("revision update unexpectedly succeeded")

    def attempt_parent_delete(self, revision_id: str) -> str:
        try:
            self.connection.execute(
                "DELETE FROM revision_parents WHERE revision_id = ?",
                (revision_id,),
            )
        except sqlite3.IntegrityError as error:
            return str(error)
        raise AssertionError("revision parent delete unexpectedly succeeded")

    def attempt_parent_insert(self, revision_id: str) -> str:
        try:
            self.connection.execute(
                """
                INSERT INTO revision_parents(
                    revision_id, parent_revision_id, parent_ordinal
                ) VALUES (?, 'fabricated-parent', 99)
                """,
                (revision_id,),
            )
        except sqlite3.IntegrityError as error:
            return str(error)
        raise AssertionError("revision parent insert unexpectedly succeeded")

    def pending_rows(self, consumer_id: str) -> list[dict[str, Any]]:
        return [
            {
                "attempt_count": int(row["attempt_count"]),
                "event_id": str(row["event_id"]),
                "missing_parents": json.loads(str(row["missing_parents_json"])),
                "reason": str(row["reason"]),
                "revision_id": str(row["revision_id"]),
            }
            for row in self.connection.execute(
                """
                SELECT event_id, revision_id, reason, missing_parents_json,
                       attempt_count
                FROM consumer_pending
                WHERE consumer_id = ?
                ORDER BY event_id
                """,
                (consumer_id,),
            )
        ]

    def consumer_heads(self, consumer_id: str, entity_id: str) -> list[str]:
        return [
            str(row["revision_id"])
            for row in self.connection.execute(
                """
                SELECT revision_id
                FROM consumer_heads
                WHERE consumer_id = ? AND entity_id = ?
                ORDER BY revision_id
                """,
                (consumer_id, entity_id),
            )
        ]

    def source_semantic_state(self) -> dict[str, Any]:
        revisions = [
            {
                "contract_hash": str(row["contract_hash"]),
                "device_sequence": int(row["device_sequence"]),
                "entity_id": str(row["entity_id"]),
                "exact_version": str(row["exact_version"]),
                "logical_sequence": int(row["logical_sequence"]),
                "origin_device": str(row["origin_device"]),
                "payload": json.loads(str(row["payload_json"])),
                "revision_id": str(row["revision_id"]),
                "tombstone": bool(row["tombstone"]),
            }
            for row in self.connection.execute(
                """
                SELECT revision_id, entity_id, payload_json, tombstone,
                       origin_device, device_sequence, exact_version,
                       contract_hash, logical_sequence
                FROM revisions
                ORDER BY revision_id
                """
            )
        ]
        parents = [
            {
                "parent_revision_id": str(row["parent_revision_id"]),
                "revision_id": str(row["revision_id"]),
            }
            for row in self.connection.execute(
                """
                SELECT revision_id, parent_revision_id
                FROM revision_parents
                ORDER BY revision_id, parent_revision_id
                """
            )
        ]
        heads = [
            {
                "entity_id": str(row["entity_id"]),
                "revision_id": str(row["revision_id"]),
            }
            for row in self.connection.execute(
                "SELECT entity_id, revision_id FROM heads ORDER BY entity_id, revision_id"
            )
        ]
        return {"heads": heads, "parents": parents, "revisions": revisions}

    def source_semantic_digest(self) -> str:
        return sha256_json(self.source_semantic_state())

    def consumer_semantic_state(self, consumer_id: str) -> dict[str, Any]:
        revisions = [
            {
                "device_sequence": int(row["device_sequence"]),
                "entity_id": str(row["entity_id"]),
                "logical_sequence": int(row["logical_sequence"]),
                "origin_device": str(row["origin_device"]),
                "payload": json.loads(str(row["payload_json"])),
                "revision_id": str(row["revision_id"]),
                "tombstone": bool(row["tombstone"]),
            }
            for row in self.connection.execute(
                """
                SELECT revision_id, entity_id, payload_json, tombstone,
                       origin_device, device_sequence, logical_sequence
                FROM consumer_revisions
                WHERE consumer_id = ?
                ORDER BY revision_id
                """,
                (consumer_id,),
            )
        ]
        parents = [
            {
                "parent_revision_id": str(row["parent_revision_id"]),
                "revision_id": str(row["revision_id"]),
            }
            for row in self.connection.execute(
                """
                SELECT revision_id, parent_revision_id
                FROM consumer_parents
                WHERE consumer_id = ?
                ORDER BY revision_id, parent_revision_id
                """,
                (consumer_id,),
            )
        ]
        heads = [
            {
                "entity_id": str(row["entity_id"]),
                "revision_id": str(row["revision_id"]),
            }
            for row in self.connection.execute(
                """
                SELECT entity_id, revision_id
                FROM consumer_heads
                WHERE consumer_id = ?
                ORDER BY entity_id, revision_id
                """,
                (consumer_id,),
            )
        ]
        effects = [
            {
                "effect_digest": str(row["effect_digest"]),
                "entity_id": str(row["entity_id"]),
                "revision_id": str(row["revision_id"]),
                "tombstone": bool(row["tombstone"]),
            }
            for row in self.connection.execute(
                """
                SELECT revision_id, entity_id, tombstone, effect_digest
                FROM consumer_effects
                WHERE consumer_id = ?
                ORDER BY revision_id
                """,
                (consumer_id,),
            )
        ]
        return {
            "effects": effects,
            "heads": heads,
            "parents": parents,
            "revisions": revisions,
        }

    def consumer_semantic_digest(self, consumer_id: str) -> str:
        return sha256_json(self.consumer_semantic_state(consumer_id))


def replay_until_fixed_point(
    store: ExperimentStore,
    consumer_id: str,
    events: Iterable[dict[str, Any]],
    *,
    max_passes: int,
) -> dict[str, Any]:
    queue = list(events)
    counts = {
        "APPLIED": 0,
        "DUPLICATE_SUPPRESSED": 0,
        "MISSING_PARENT": 0,
    }
    passes = 0
    for pass_number in range(1, max_passes + 1):
        passes = pass_number
        applied_this_pass = 0
        for event in queue:
            result = store.apply_event(consumer_id, event)
            counts[result.code] = counts.get(result.code, 0) + 1
            if result.code == "APPLIED":
                applied_this_pass += 1
        if not store.pending_rows(consumer_id):
            break
        if applied_this_pass == 0:
            break
    return {
        "codes": counts,
        "passes": passes,
        "pending": store.pending_rows(consumer_id),
    }
