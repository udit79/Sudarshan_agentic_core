"""Durable provider job lifecycle tracking and reconciliation for video generation."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from threading import RLock
from time import time
from typing import Any, Callable, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


ProviderJobStatus = Literal["submit_unknown", "submitting", "pending", "succeeded", "failed", "cancelled"]


class VideoProviderJobRecord(BaseModel):
    """Durable state for an external or asynchronous video generation job."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    provider_task_id: str = Field(default="")
    provider: str = Field(min_length=1)
    status: ProviderJobStatus = "submitting"
    submit_fingerprint: str = Field(min_length=1)
    created_at: float
    last_checked_at: float
    next_check_at: float
    attempt_count: int = 1
    error: str | None = None
    receipt_json: str | None = None


class VideoProviderJobStore:
    """Thread-safe SQLite store for external video provider tasks."""

    def __init__(self, db_path: str = "artifacts/.state/video_provider_jobs.db") -> None:
        self.db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = RLock()
        self._create_schema()

    def _create_schema(self) -> None:
        with self._lock:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS video_provider_jobs (
                    run_id TEXT PRIMARY KEY,
                    provider_task_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    status TEXT NOT NULL,
                    submit_fingerprint TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    last_checked_at REAL NOT NULL,
                    next_check_at REAL NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 1,
                    error TEXT,
                    receipt_json TEXT
                );
                """
            )
            self._connection.commit()

    def record_submit_start(self, run_id: str, provider: str, submit_fingerprint: str) -> VideoProviderJobRecord:
        now = time()
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO video_provider_jobs
                    (run_id, provider_task_id, provider, status, submit_fingerprint, created_at, last_checked_at, next_check_at, attempt_count)
                VALUES (?, '', ?, 'submitting', ?, ?, ?, ?, 1)
                ON CONFLICT(run_id) DO UPDATE SET
                    status = 'submitting',
                    submit_fingerprint = excluded.submit_fingerprint,
                    last_checked_at = excluded.last_checked_at,
                    attempt_count = video_provider_jobs.attempt_count + 1
                """,
                (run_id, provider, submit_fingerprint, now, now, now + 5.0),
            )
            self._connection.commit()
            return self.get(run_id)  # type: ignore[return-value]

    def record_submit_unknown(self, run_id: str, error: str) -> VideoProviderJobRecord:
        now = time()
        with self._lock:
            self._connection.execute(
                """
                UPDATE video_provider_jobs
                SET status = 'submit_unknown', error = ?, last_checked_at = ?, next_check_at = ?
                WHERE run_id = ?
                """,
                (error[:500], now, now + 10.0, run_id),
            )
            self._connection.commit()
            return self.get(run_id)  # type: ignore[return-value]

    def record_submit_success(self, run_id: str, provider_task_id: str, status: ProviderJobStatus = "pending") -> VideoProviderJobRecord:
        now = time()
        with self._lock:
            self._connection.execute(
                """
                UPDATE video_provider_jobs
                SET provider_task_id = ?, status = ?, last_checked_at = ?, next_check_at = ?
                WHERE run_id = ?
                """,
                (provider_task_id, status, now, now + 5.0, run_id),
            )
            self._connection.commit()
            return self.get(run_id)  # type: ignore[return-value]

    def record_terminal(self, run_id: str, status: Literal["succeeded", "failed", "cancelled"], receipt: Mapping[str, Any] | None = None, error: str | None = None) -> VideoProviderJobRecord:
        now = time()
        receipt_str = json.dumps(dict(receipt), ensure_ascii=False) if receipt else None
        with self._lock:
            self._connection.execute(
                """
                UPDATE video_provider_jobs
                SET status = ?, receipt_json = ?, error = ?, last_checked_at = ?
                WHERE run_id = ?
                """,
                (status, receipt_str, error[:500] if error else None, now, run_id),
            )
            self._connection.commit()
            return self.get(run_id)  # type: ignore[return-value]

    def reconcile_job(
        self,
        run_id: str,
        status_check_fn: Callable[[str, str], tuple[ProviderJobStatus, Mapping[str, Any] | None, str | None]],
    ) -> VideoProviderJobRecord | None:
        """Reconcile a pending or submit_unknown job by polling external provider status."""
        record = self.get(run_id)
        if record is None:
            return None
        if record.status in {"succeeded", "failed", "cancelled"}:
            return record

        now = time()
        new_status, receipt, error = status_check_fn(record.provider, record.provider_task_id)

        with self._lock:
            receipt_str = json.dumps(dict(receipt), ensure_ascii=False) if receipt else record.receipt_json
            next_interval = 10.0 if new_status in {"pending", "submit_unknown"} else 0.0
            self._connection.execute(
                """
                UPDATE video_provider_jobs
                SET status = ?, receipt_json = ?, error = ?, last_checked_at = ?, next_check_at = ?
                WHERE run_id = ?
                """,
                (new_status, receipt_str, error, now, now + next_interval, run_id),
            )
            self._connection.commit()
            return self.get(run_id)

    def get(self, run_id: str) -> VideoProviderJobRecord | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM video_provider_jobs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                return None
            return VideoProviderJobRecord(
                run_id=row["run_id"],
                provider_task_id=row["provider_task_id"],
                provider=row["provider"],
                status=row["status"],
                submit_fingerprint=row["submit_fingerprint"],
                created_at=float(row["created_at"]),
                last_checked_at=float(row["last_checked_at"]),
                next_check_at=float(row["next_check_at"]),
                attempt_count=int(row["attempt_count"]),
                error=row["error"],
                receipt_json=row["receipt_json"],
            )

    def close(self) -> None:
        with self._lock:
            self._connection.close()


__all__ = ["ProviderJobStatus", "VideoProviderJobRecord", "VideoProviderJobStore"]
