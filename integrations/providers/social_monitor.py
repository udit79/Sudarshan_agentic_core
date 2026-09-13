"""Opt-in, read-only social thread monitoring lifecycle.

Monitoring owns only durable polling state and safe read receipts. It never
generates or publishes a reply; any suggestion/approval workflow remains an
application-owned step after an operator reviews the untrusted thread data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import sqlite3
from pathlib import Path
from threading import Lock
from time import time
from typing import Any, Mapping, Protocol
from uuid import uuid4

from integrations.providers.social import SocialReceipt
from integrations.providers.social_approval import _scope_hash
from integrations.providers.social_cache import sanitize_social_mapping


class SocialMonitorConflict(RuntimeError):
    """Raised when a monitor cannot safely transition or poll."""


@dataclass(frozen=True, slots=True)
class SocialMonitorRecord:
    monitor_id: str
    provider: str
    target_ref: str
    scope_hash: str
    interval_seconds: float
    status: str
    next_poll_at: float | None
    last_poll_at: float | None
    non_actionable: bool
    last_receipt: Mapping[str, Any] | None
    created_at: float
    updated_at: float


class SocialMonitorStore:
    """SQLite-backed monitor state with atomic polling claims."""

    def __init__(self, db_path: str = "artifacts/.state/social_monitors.db") -> None:
        self.db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = Lock()
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS social_monitors (
                monitor_id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                target_ref TEXT NOT NULL,
                scope_hash TEXT NOT NULL,
                interval_seconds REAL NOT NULL,
                status TEXT NOT NULL,
                next_poll_at REAL,
                last_poll_at REAL,
                non_actionable INTEGER NOT NULL DEFAULT 0,
                last_receipt_json TEXT,
                lease_owner TEXT,
                lease_expires_at REAL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_social_monitors_due
                ON social_monitors(status, next_poll_at);
            """
        )
        existing_columns = {str(row[1]) for row in self._connection.execute("PRAGMA table_info(social_monitors)")}
        for column, definition in (("lease_owner", "TEXT"), ("lease_expires_at", "REAL")):
            if column not in existing_columns:
                self._connection.execute(f"ALTER TABLE social_monitors ADD COLUMN {column} {definition}")
        self._connection.commit()

    def create(
        self,
        *,
        provider: str,
        target_ref: str,
        authorization_scope: Mapping[str, Any],
        interval_seconds: float,
        start_at: datetime | None = None,
    ) -> SocialMonitorRecord:
        interval = _validate_interval(interval_seconds)
        target = str(target_ref).strip()
        if not target:
            raise SocialMonitorConflict("target_ref is required")
        scope_hash = _scope_hash(authorization_scope)
        now = time()
        next_poll = _timestamp(start_at) if start_at is not None else now
        monitor_id = f"monitor-{uuid4().hex}"
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO social_monitors
                    (monitor_id, provider, target_ref, scope_hash, interval_seconds,
                     status, next_poll_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)
                """,
                (monitor_id, str(provider).strip().lower(), target, scope_hash, interval, next_poll, now, now),
            )
            self._connection.commit()
            return self._get_locked(monitor_id)  # type: ignore[return-value]

    def get(self, monitor_id: str) -> SocialMonitorRecord | None:
        with self._lock:
            return self._get_locked(monitor_id)

    def claim_due(
        self,
        *,
        worker_id: str = "monitor-worker",
        lease_seconds: float = 300.0,
        now: float | None = None,
    ) -> SocialMonitorRecord | None:
        if not str(worker_id).strip():
            raise SocialMonitorConflict("worker_id is required")
        if lease_seconds <= 0:
            raise SocialMonitorConflict("lease_seconds must be positive")
        current = time() if now is None else float(now)
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            row = self._connection.execute(
                """
                SELECT * FROM social_monitors
                WHERE non_actionable = 0 AND next_poll_at IS NOT NULL AND next_poll_at <= ?
                  AND (
                    status = 'active'
                    OR (status = 'polling' AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?)
                  )
                ORDER BY next_poll_at, monitor_id
                LIMIT 1
                """,
                (current, current),
            ).fetchone()
            if row is None:
                self._connection.commit()
                return None
            self._connection.execute(
                "UPDATE social_monitors SET status = 'polling', lease_owner = ?, lease_expires_at = ?, updated_at = ? WHERE monitor_id = ?",
                (str(worker_id).strip(), current + float(lease_seconds), current, row["monitor_id"]),
            )
            self._connection.commit()
            return self._get_locked(str(row["monitor_id"]))

    def finish(
        self,
        monitor_id: str,
        *,
        receipt: SocialReceipt,
        worker_id: str = "monitor-worker",
        now: float | None = None,
        non_actionable: bool = False,
        next_poll_at: float | None = None,
    ) -> SocialMonitorRecord:
        current = time() if now is None else float(now)
        safe_receipt = receipt.to_dict()
        safe_receipt["data"] = sanitize_social_mapping(receipt.data)
        safe_receipt["metadata"] = sanitize_social_mapping(receipt.metadata)
        safe = json.dumps(safe_receipt, ensure_ascii=False, sort_keys=True)
        status = "paused" if non_actionable else "active"
        with self._lock:
            record = self._get_locked(monitor_id)
            if record is None:
                raise SocialMonitorConflict("monitor not found")
            if record.status not in {"polling", "active"}:
                if record.last_receipt:
                    return record
                raise SocialMonitorConflict(f"monitor is not pollable: {record.status}")
            row = self._connection.execute(
                "SELECT lease_owner FROM social_monitors WHERE monitor_id = ?", (monitor_id,)
            ).fetchone()
            if row["lease_owner"] not in {None, str(worker_id).strip()}:
                raise SocialMonitorConflict("monitor lease is owned by another worker")
            self._connection.execute(
                """
                UPDATE social_monitors
                SET status = ?, next_poll_at = ?, last_poll_at = ?, non_actionable = ?,
                    last_receipt_json = ?, lease_owner = NULL, lease_expires_at = NULL, updated_at = ?
                WHERE monitor_id = ?
                """,
                (status, None if non_actionable else next_poll_at, current, int(non_actionable), safe, current, monitor_id),
            )
            self._connection.commit()
            return self._get_locked(monitor_id)  # type: ignore[return-value]

    def pause(self, monitor_id: str) -> SocialMonitorRecord:
        return self._transition(monitor_id, "paused", next_poll_at=None)

    def resume(self, monitor_id: str, *, now: float | None = None) -> SocialMonitorRecord:
        current = time() if now is None else float(now)
        return self._transition(monitor_id, "active", next_poll_at=current, clear_non_actionable=True)

    def cancel(self, monitor_id: str) -> SocialMonitorRecord:
        return self._transition(monitor_id, "cancelled", next_poll_at=None)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _transition(
        self,
        monitor_id: str,
        status: str,
        *,
        next_poll_at: float | None,
        clear_non_actionable: bool = False,
    ) -> SocialMonitorRecord:
        with self._lock:
            record = self._get_locked(monitor_id)
            if record is None:
                raise SocialMonitorConflict("monitor not found")
            if record.status == "cancelled" and status != "cancelled":
                raise SocialMonitorConflict("cancelled monitor cannot resume")
            now = time()
            self._connection.execute(
                "UPDATE social_monitors SET status = ?, next_poll_at = ?, non_actionable = ?, updated_at = ? WHERE monitor_id = ?",
                (status, next_poll_at, 0 if clear_non_actionable else int(record.non_actionable), now, monitor_id),
            )
            self._connection.commit()
            return self._get_locked(monitor_id)  # type: ignore[return-value]

    def _get_locked(self, monitor_id: str) -> SocialMonitorRecord | None:
        row = self._connection.execute(
            "SELECT * FROM social_monitors WHERE monitor_id = ?", (monitor_id,)
        ).fetchone()
        if row is None:
            return None
        raw_receipt = row["last_receipt_json"]
        return SocialMonitorRecord(
            monitor_id=str(row["monitor_id"]), provider=str(row["provider"]),
            target_ref=str(row["target_ref"]), scope_hash=str(row["scope_hash"]),
            interval_seconds=float(row["interval_seconds"]), status=str(row["status"]),
            next_poll_at=float(row["next_poll_at"]) if row["next_poll_at"] is not None else None,
            last_poll_at=float(row["last_poll_at"]) if row["last_poll_at"] is not None else None,
            non_actionable=bool(row["non_actionable"]),
            last_receipt=json.loads(raw_receipt) if raw_receipt else None,
            created_at=float(row["created_at"]), updated_at=float(row["updated_at"]),
        )


class _ThreadReader(Protocol):
    def fetch_thread(self, target_ref: str, **kwargs: Any) -> SocialReceipt:
        """Fetch one bounded, scoped thread."""


class SocialThreadMonitorService:
    """Poll a read boundary only after explicit operator opt-in."""

    def __init__(self, reader: _ThreadReader, store: SocialMonitorStore) -> None:
        self.reader = reader
        self.store = store

    def start(
        self,
        *,
        provider: str,
        target_ref: str,
        authorization_scope: Mapping[str, Any],
        interval_seconds: float = 300.0,
        start_at: datetime | None = None,
        opt_in: bool = False,
    ) -> SocialMonitorRecord:
        if not opt_in:
            raise SocialMonitorConflict("thread monitoring requires explicit opt-in")
        return self.store.create(
            provider=provider, target_ref=target_ref,
            authorization_scope=authorization_scope, interval_seconds=interval_seconds,
            start_at=start_at,
        )

    def poll_due(
        self,
        *,
        authorization_scope: Mapping[str, Any],
        worker_id: str = "monitor-worker",
        now: float | None = None,
    ) -> SocialMonitorRecord | None:
        current = time() if now is None else float(now)
        claimed = self.store.claim_due(worker_id=worker_id, now=current)
        if claimed is None:
            return None
        if _scope_hash(authorization_scope) != claimed.scope_hash:
            receipt = SocialReceipt(
                receipt_id=f"social-monitor-scope-{uuid4().hex}", provider=claimed.provider,
                operation="fetch_thread", status="failed", target_ref=claimed.target_ref,
                error_code="SOCIAL_MONITOR_SCOPE_MISMATCH",
            )
            return self.store.finish(
                claimed.monitor_id, receipt=receipt, worker_id=worker_id,
                now=current, next_poll_at=None, non_actionable=True,
            )
        receipt = self.reader.fetch_thread(
            claimed.target_ref, provider=claimed.provider,
            authorization_scope=authorization_scope,
        )
        non_actionable = _is_non_actionable(receipt)
        delay = max(claimed.interval_seconds, receipt.retry_after_seconds or 0.0)
        return self.store.finish(
            claimed.monitor_id, receipt=receipt, worker_id=worker_id, now=current,
            next_poll_at=current + delay, non_actionable=non_actionable,
        )


def _validate_interval(value: float) -> float:
    try:
        interval = float(value)
    except (TypeError, ValueError) as error:
        raise SocialMonitorConflict("monitor interval must be numeric") from error
    if interval < 30 or interval > 604800:
        raise SocialMonitorConflict("monitor interval must be between 30 seconds and 7 days")
    return interval


def _timestamp(value: datetime) -> float:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SocialMonitorConflict("start_at must include a timezone")
    return value.astimezone(timezone.utc).timestamp()


def _is_non_actionable(receipt: SocialReceipt) -> bool:
    if receipt.error_code in {"SOCIAL_NOT_FOUND", "SOCIAL_DELETED", "SOCIAL_SCOPE_MISMATCH"}:
        return True
    return bool(receipt.data.get("deleted") or receipt.data.get("non_actionable"))


__all__ = [
    "SocialMonitorConflict",
    "SocialMonitorRecord",
    "SocialMonitorStore",
    "SocialThreadMonitorService",
]
