"""Durable, approval-gated scheduling for social write actions.

The queue stores only the typed request needed to resume a scheduled action and
its safe receipt. Provider credentials stay outside the queue. A worker must
provide the authorization scope again after restart, so scope cannot silently
be widened by a persisted job.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import sqlite3
from pathlib import Path
from threading import Lock
from time import time
from typing import Any, Mapping

from integrations.providers.social import SocialReceipt, SocialRequest
from integrations.providers.social_approval import SocialReleaseService, _scope_hash
from integrations.providers.social_cache import sanitize_social_mapping


class SocialScheduleConflict(RuntimeError):
    """Raised when a scheduled social action cannot safely transition."""


@dataclass(frozen=True, slots=True)
class SocialScheduleRecord:
    schedule_id: str
    approval_id: str
    provider: str
    target_ref: str
    idempotency_key: str
    status: str
    scheduled_at: float
    attempts: int
    next_attempt_at: float | None
    last_error: str | None
    receipt: Mapping[str, Any] | None
    created_at: float
    updated_at: float


class SocialScheduleStore:
    """SQLite queue with atomic due-job claims and restart-safe state."""

    def __init__(self, db_path: str = "artifacts/.state/social_schedules.db") -> None:
        self.db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = Lock()
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS social_schedules (
                schedule_id TEXT PRIMARY KEY,
                approval_id TEXT NOT NULL UNIQUE,
                scope_hash TEXT NOT NULL,
                provider TEXT NOT NULL,
                target_ref TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                request_json TEXT NOT NULL,
                scheduled_at REAL NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at REAL,
                last_error TEXT,
                receipt_json TEXT,
                lease_owner TEXT,
                lease_expires_at REAL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_social_schedules_due
                ON social_schedules(status, next_attempt_at, scheduled_at);
            """
        )
        for column, definition in (("lease_owner", "TEXT"), ("lease_expires_at", "REAL")):
            if column not in {str(row[1]) for row in self._connection.execute("PRAGMA table_info(social_schedules)")}:
                self._connection.execute(f"ALTER TABLE social_schedules ADD COLUMN {column} {definition}")
        self._connection.commit()

    def create_or_get(
        self,
        request: SocialRequest,
        *,
        approval_id: str,
        authorization_scope: Mapping[str, Any],
    ) -> SocialScheduleRecord:
        scheduled_at = normalize_scheduled_time(request.scheduled_for)
        if request.operation != "schedule_post":
            raise SocialScheduleConflict("only schedule_post requests can enter the schedule queue")
        scope_hash = _scope_hash(authorization_scope)
        request_json = json.dumps(_request_to_dict(request), ensure_ascii=False, sort_keys=True)
        now = time()
        with self._lock:
            existing = self._connection.execute(
                "SELECT * FROM social_schedules WHERE approval_id = ?", (approval_id,)
            ).fetchone()
            if existing is not None:
                if existing["request_json"] != request_json or existing["scope_hash"] != scope_hash:
                    raise SocialScheduleConflict("schedule idempotency key does not match the existing action")
                return _row_to_record(existing)
            schedule_id = f"schedule-{approval_id.removeprefix('approval-')}"
            self._connection.execute(
                """
                INSERT INTO social_schedules
                    (schedule_id, approval_id, scope_hash, provider, target_ref,
                     idempotency_key, request_json, scheduled_at, status,
                     next_attempt_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending_approval', ?, ?, ?)
                """,
                (
                    schedule_id, approval_id, scope_hash, request.provider,
                    request.target_ref, request.idempotency_key, request_json,
                    scheduled_at, scheduled_at, now, now,
                ),
            )
            self._connection.commit()
            return self._get_locked(schedule_id)  # type: ignore[return-value]

    def get(self, schedule_id: str) -> SocialScheduleRecord | None:
        with self._lock:
            return self._get_locked(schedule_id)

    def mark_scheduled(self, schedule_id: str) -> SocialScheduleRecord:
        with self._lock:
            record = self._get_locked(schedule_id)
            if record is None:
                raise SocialScheduleConflict("schedule not found")
            if record.status == "scheduled":
                return record
            if record.status != "pending_approval":
                raise SocialScheduleConflict(f"schedule cannot be approved from {record.status}")
            now = time()
            self._connection.execute(
                "UPDATE social_schedules SET status = 'scheduled', next_attempt_at = scheduled_at, updated_at = ? WHERE schedule_id = ?",
                (now, schedule_id),
            )
            self._connection.commit()
            return self._get_locked(schedule_id)  # type: ignore[return-value]

    def cancel(self, schedule_id: str) -> SocialScheduleRecord:
        with self._lock:
            record = self._get_locked(schedule_id)
            if record is None:
                raise SocialScheduleConflict("schedule not found")
            if record.status == "cancelled":
                return record
            if record.status not in {"pending_approval", "scheduled"}:
                raise SocialScheduleConflict(f"schedule cannot be cancelled from {record.status}")
            now = time()
            self._connection.execute(
                "UPDATE social_schedules SET status = 'cancelled', next_attempt_at = NULL, updated_at = ? WHERE schedule_id = ?",
                (now, schedule_id),
            )
            self._connection.commit()
            return self._get_locked(schedule_id)  # type: ignore[return-value]

    def claim_due(
        self,
        *,
        worker_id: str = "schedule-worker",
        lease_seconds: float = 300.0,
        now: float | None = None,
    ) -> SocialScheduleRecord | None:
        if not str(worker_id).strip():
            raise SocialScheduleConflict("worker_id is required")
        if lease_seconds <= 0:
            raise SocialScheduleConflict("lease_seconds must be positive")
        current = time() if now is None else float(now)
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            row = self._connection.execute(
                """
                SELECT * FROM social_schedules
                WHERE scheduled_at <= ?
                  AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                  AND (
                    status IN ('scheduled', 'provider_pending')
                    OR (status = 'running' AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?)
                  )
                ORDER BY COALESCE(next_attempt_at, scheduled_at), schedule_id
                LIMIT 1
                """,
                (current, current, current),
            ).fetchone()
            if row is None:
                self._connection.commit()
                return None
            self._connection.execute(
                "UPDATE social_schedules SET status = 'running', attempts = attempts + 1, lease_owner = ?, lease_expires_at = ?, updated_at = ? WHERE schedule_id = ?",
                (str(worker_id).strip(), current + float(lease_seconds), current, row["schedule_id"]),
            )
            self._connection.commit()
            return self._get_locked(str(row["schedule_id"]))

    def finish(
        self,
        schedule_id: str,
        *,
        status: str,
        receipt: SocialReceipt,
        worker_id: str = "schedule-worker",
        next_attempt_at: float | None = None,
        last_error: str | None = None,
    ) -> SocialScheduleRecord:
        if status not in {"provider_pending", "succeeded", "failed", "cancelled", "draft_only"}:
            raise SocialScheduleConflict(f"unsupported schedule terminal state: {status}")
        safe_receipt = receipt.to_dict()
        safe_receipt["data"] = sanitize_social_mapping(receipt.data)
        safe_receipt["metadata"] = sanitize_social_mapping(receipt.metadata)
        now = time()
        with self._lock:
            record = self._get_locked(schedule_id)
            if record is None:
                raise SocialScheduleConflict("schedule not found")
            if record.status not in {"running", "provider_pending"}:
                if record.receipt:
                    return record
                raise SocialScheduleConflict(f"schedule is not running: {record.status}")
            row = self._connection.execute(
                "SELECT lease_owner FROM social_schedules WHERE schedule_id = ?", (schedule_id,)
            ).fetchone()
            if row["lease_owner"] not in {None, str(worker_id).strip()}:
                raise SocialScheduleConflict("schedule lease is owned by another worker")
            self._connection.execute(
                "UPDATE social_schedules SET status = ?, next_attempt_at = ?, last_error = ?, receipt_json = ?, lease_owner = NULL, lease_expires_at = NULL, updated_at = ? WHERE schedule_id = ?",
                (status, next_attempt_at, last_error, json.dumps(safe_receipt, sort_keys=True), now, schedule_id),
            )
            self._connection.commit()
            return self._get_locked(schedule_id)  # type: ignore[return-value]

    def request_json(self, schedule_id: str) -> str:
        with self._lock:
            row = self._connection.execute(
                "SELECT request_json FROM social_schedules WHERE schedule_id = ?", (schedule_id,)
            ).fetchone()
            if row is None:
                raise SocialScheduleConflict("schedule not found")
            return str(row["request_json"])

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _get_locked(self, schedule_id: str) -> SocialScheduleRecord | None:
        row = self._connection.execute(
            "SELECT * FROM social_schedules WHERE schedule_id = ?", (schedule_id,)
        ).fetchone()
        return _row_to_record(row) if row is not None else None


class SocialScheduleService:
    """Coordinate approval, durable scheduling, and provider release."""

    def __init__(
        self,
        release_service: SocialReleaseService,
        store: SocialScheduleStore,
        *,
        max_attempts: int = 3,
        retry_delay_seconds: float = 30.0,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if retry_delay_seconds <= 0:
            raise ValueError("retry_delay_seconds must be positive")
        self.release_service = release_service
        self.store = store
        self.max_attempts = max_attempts
        self.retry_delay_seconds = retry_delay_seconds

    def submit(
        self,
        request: SocialRequest,
        *,
        authorization_scope: Mapping[str, Any],
        actor_id: str,
    ) -> SocialScheduleRecord:
        normalize_scheduled_time(request.scheduled_for)
        approval = self.release_service.submit_schedule(
            request, authorization_scope=authorization_scope, actor_id=actor_id
        )
        return self.store.create_or_get(
            request, approval_id=approval.approval_id, authorization_scope=authorization_scope
        )

    def approve(self, schedule_id: str, *, actor_id: str) -> SocialScheduleRecord:
        record = self.store.get(schedule_id)
        if record is None:
            raise SocialScheduleConflict("schedule not found")
        self.release_service.approve(record.approval_id, actor_id=actor_id)
        return self.store.mark_scheduled(schedule_id)

    def cancel(self, schedule_id: str, *, actor_id: str) -> SocialScheduleRecord:
        record = self.store.get(schedule_id)
        if record is None:
            raise SocialScheduleConflict("schedule not found")
        self.release_service.store.cancel(record.approval_id, actor_id=actor_id)
        return self.store.cancel(schedule_id)

    def release_due(
        self,
        *,
        authorization_scope: Mapping[str, Any],
        worker_id: str,
        now: float | None = None,
    ) -> SocialScheduleRecord | None:
        claimed = self.store.claim_due(worker_id=worker_id, now=now)
        if claimed is None:
            return None
        request = _request_from_dict(json.loads(self.store.request_json(claimed.schedule_id)))
        receipt = self.release_service.release(
            claimed.approval_id,
            request,
            authorization_scope=authorization_scope,
            worker_id=worker_id,
        )
        if receipt.status == "pending":
            delay = receipt.retry_after_seconds or self.retry_delay_seconds
            return self.store.finish(
                claimed.schedule_id,
                status="provider_pending",
                receipt=receipt,
                worker_id=worker_id,
                next_attempt_at=(time() + delay),
                last_error=receipt.error_code,
            )
        if receipt.status == "failed" and receipt.failure_class in {"transient", "timeout", "rate_limit"} and claimed.attempts < self.max_attempts:
            delay = receipt.retry_after_seconds or self.retry_delay_seconds
            return self.store.finish(
                claimed.schedule_id,
                status="provider_pending",
                receipt=receipt,
                worker_id=worker_id,
                next_attempt_at=(time() + delay),
                last_error=receipt.error_code,
            )
        return self.store.finish(
            claimed.schedule_id,
            status=receipt.status if receipt.status in {"succeeded", "failed", "cancelled", "draft_only"} else "failed",
            receipt=receipt,
            worker_id=worker_id,
            last_error=receipt.error_code,
        )


def normalize_scheduled_time(value: datetime | None) -> float:
    if value is None:
        raise SocialScheduleConflict("scheduled_for is required")
    if value.tzinfo is None or value.utcoffset() is None:
        raise SocialScheduleConflict("scheduled_for must include a timezone")
    return value.astimezone(timezone.utc).timestamp()


def _request_to_dict(request: SocialRequest) -> dict[str, Any]:
    return {
        "operation": request.operation,
        "target_ref": request.target_ref,
        "payload": dict(request.payload),
        "provider": request.provider,
        "case_id": request.case_id,
        "run_id": request.run_id,
        "skill_id": request.skill_id,
        "approval_id": request.approval_id,
        "idempotency_key": request.idempotency_key,
        "timeout_seconds": request.timeout_seconds,
        "scheduled_for": request.scheduled_for.isoformat() if request.scheduled_for else None,
    }


def _request_from_dict(value: Mapping[str, Any]) -> SocialRequest:
    raw_scheduled = value.get("scheduled_for")
    scheduled_for = datetime.fromisoformat(str(raw_scheduled)) if raw_scheduled else None
    payload = value.get("payload")
    return SocialRequest(
        operation=str(value.get("operation", "schedule_post")),
        target_ref=str(value.get("target_ref", "")),
        payload=dict(payload) if isinstance(payload, Mapping) else {},
        provider=str(value.get("provider", "manual")),
        case_id=str(value.get("case_id", "")),
        run_id=str(value.get("run_id", "")),
        skill_id=str(value.get("skill_id", "linkedin.post")),
        approval_id=str(value["approval_id"]) if value.get("approval_id") else None,
        idempotency_key=str(value.get("idempotency_key", "")),
        timeout_seconds=float(value.get("timeout_seconds", 30.0)),
        scheduled_for=scheduled_for,
    )


def _row_to_record(row: sqlite3.Row) -> SocialScheduleRecord:
    raw_receipt = row["receipt_json"]
    receipt = json.loads(raw_receipt) if raw_receipt else None
    return SocialScheduleRecord(
        schedule_id=str(row["schedule_id"]), approval_id=str(row["approval_id"]),
        provider=str(row["provider"]), target_ref=str(row["target_ref"]),
        idempotency_key=str(row["idempotency_key"]), status=str(row["status"]),
        scheduled_at=float(row["scheduled_at"]), attempts=int(row["attempts"]),
        next_attempt_at=float(row["next_attempt_at"]) if row["next_attempt_at"] is not None else None,
        last_error=str(row["last_error"]) if row["last_error"] else None,
        receipt=receipt, created_at=float(row["created_at"]), updated_at=float(row["updated_at"]),
    )


__all__ = [
    "SocialScheduleConflict",
    "SocialScheduleRecord",
    "SocialScheduleService",
    "SocialScheduleStore",
    "normalize_scheduled_time",
]
