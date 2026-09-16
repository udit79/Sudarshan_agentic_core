"""Authenticated, persisted operator waiver store for degraded fallback releases."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import sqlite3
from threading import Lock
from time import time
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class OperatorWaiver(BaseModel):
    """An authorized, single-use, time-limited waiver for degraded fallback output."""

    model_config = ConfigDict(extra="forbid")

    waiver_id: str = Field(min_length=1)
    operator_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    artifact_id: str | None = None
    reason: str = Field(min_length=1)
    created_at: float
    expires_at: float
    used: bool = False


class OperatorWaiverStore:
    """Thread-safe SQLite store for authenticated operator waivers."""

    def __init__(self, db_path: str = "artifacts/.state/operator_waivers.db") -> None:
        self.db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = Lock()
        self._create_schema()

    def _create_schema(self) -> None:
        with self._lock:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS operator_waivers (
                    waiver_id TEXT PRIMARY KEY,
                    operator_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    artifact_id TEXT,
                    reason TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    used INTEGER NOT NULL DEFAULT 0
                );
                """
            )
            self._connection.commit()

    def issue_waiver(
        self,
        *,
        operator_id: str,
        run_id: str,
        reason: str,
        artifact_id: str | None = None,
        valid_seconds: float = 3600.0,
    ) -> OperatorWaiver:
        if not operator_id or not operator_id.strip():
            raise ValueError("operator_id is required to issue a waiver")
        if not run_id or not run_id.strip():
            raise ValueError("run_id is required to issue a waiver")
        if not reason or not reason.strip():
            raise ValueError("reason is required to issue a waiver")

        now = time()
        waiver = OperatorWaiver(
            waiver_id=f"waiver-{uuid4().hex[:12]}",
            operator_id=operator_id.strip(),
            run_id=run_id.strip(),
            artifact_id=artifact_id.strip() if artifact_id else None,
            reason=reason.strip(),
            created_at=now,
            expires_at=now + valid_seconds,
            used=False,
        )
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO operator_waivers (waiver_id, operator_id, run_id, artifact_id, reason, created_at, expires_at, used)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (waiver.waiver_id, waiver.operator_id, waiver.run_id, waiver.artifact_id, waiver.reason, waiver.created_at, waiver.expires_at),
            )
            self._connection.commit()
        return waiver

    def verify_and_consume_waiver(self, waiver_id: str, *, run_id: str, now: float | None = None) -> bool:
        """Verify the waiver is valid, bound to run_id, not expired, and mark used atomically."""
        current_time = now if now is not None else time()
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM operator_waivers WHERE waiver_id = ? AND run_id = ?",
                (waiver_id, run_id),
            ).fetchone()
            if row is None:
                return False
            if bool(row["used"]):
                return False
            if float(row["expires_at"]) < current_time:
                return False

            self._connection.execute(
                "UPDATE operator_waivers SET used = 1 WHERE waiver_id = ?",
                (waiver_id,),
            )
            self._connection.commit()
            return True

    def get_waiver(self, waiver_id: str) -> OperatorWaiver | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM operator_waivers WHERE waiver_id = ?",
                (waiver_id,),
            ).fetchone()
            if row is None:
                return None
            return OperatorWaiver(
                waiver_id=row["waiver_id"],
                operator_id=row["operator_id"],
                run_id=row["run_id"],
                artifact_id=row["artifact_id"],
                reason=row["reason"],
                created_at=float(row["created_at"]),
                expires_at=float(row["expires_at"]),
                used=bool(row["used"]),
            )

    def close(self) -> None:
        with self._lock:
            self._connection.close()


__all__ = ["OperatorWaiver", "OperatorWaiverStore"]
