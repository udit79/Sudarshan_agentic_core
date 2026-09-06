"""Tamper-evident local audit trail for NTRO compliance.

Every pipeline run, approval, cancellation, and memory interaction is recorded
with operator identity, classification level, and a SHA-256 integrity hash.
The audit log is a secondary persistence layer alongside Cognee task memory.

Uses SQLite with an application-level integrity hash per row.  Production
deployments should add at-rest encryption through the OS or a transparent
encryption layer consistent with GoI IT security guidelines.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Iterator, Mapping, Sequence
from uuid import uuid4


_DEFAULT_DB_PATH = "artifacts/.state/audit_log.db"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_hash(
    timestamp: str,
    operator_id: str,
    case_id: str,
    task_id: str,
    action: str,
    classification: str,
    status: str,
    detail: str,
) -> str:
    """Compute a SHA-256 integrity hash for one audit row."""

    material = "|".join((
        timestamp, operator_id, case_id, task_id,
        action, classification, status, detail,
    ))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class AuditLogger:
    """Append-only audit log with per-row integrity hashes.

    Thread-safe.  Multiple orchestrator threads may write concurrently.
    """

    def __init__(self, db_path: str | None = None) -> None:
        configured = db_path or os.getenv("SUDARSHAN_AUDIT_DB_PATH", _DEFAULT_DB_PATH)
        self._db_path = Path(configured).expanduser()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._setup()

    def _setup(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    operator_id TEXT NOT NULL,
                    case_id TEXT NOT NULL DEFAULT '',
                    task_id TEXT NOT NULL DEFAULT '',
                    run_id TEXT NOT NULL DEFAULT '',
                    action TEXT NOT NULL,
                    classification TEXT NOT NULL DEFAULT 'RESTRICTED',
                    status TEXT NOT NULL,
                    pipeline TEXT NOT NULL DEFAULT '',
                    detail TEXT NOT NULL DEFAULT '',
                    integrity_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_case
                ON audit_log (case_id, timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_operator
                ON audit_log (operator_id, timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_run
                ON audit_log (run_id, timestamp)
            """)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def log(
        self,
        *,
        operator_id: str,
        action: str,
        status: str,
        case_id: str = "",
        task_id: str = "",
        run_id: str = "",
        classification: str = "RESTRICTED",
        pipeline: str = "",
        detail: str = "",
    ) -> str:
        """Write one audit entry.  Returns the entry ID."""

        entry_id = f"audit-{uuid4()}"
        timestamp = _utc_now_iso()
        integrity = _row_hash(
            timestamp, operator_id, case_id, task_id,
            action, classification, status, detail[:2000],
        )
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO audit_log
                        (id, timestamp, operator_id, case_id, task_id, run_id,
                         action, classification, status, pipeline, detail, integrity_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (entry_id, timestamp, operator_id, case_id, task_id, run_id,
                     action, classification, status, pipeline, detail[:10000], integrity),
                )
        return entry_id

    def log_run_start(
        self,
        *,
        operator_id: str,
        case_id: str,
        task_id: str,
        run_id: str,
        classification: str,
        pipeline: str = "",
        query: str = "",
    ) -> str:
        return self.log(
            operator_id=operator_id,
            action="run_start",
            status="queued",
            case_id=case_id,
            task_id=task_id,
            run_id=run_id,
            classification=classification,
            pipeline=pipeline,
            detail=query[:2000],
        )

    def log_run_complete(
        self,
        *,
        operator_id: str,
        case_id: str,
        task_id: str,
        run_id: str,
        classification: str,
        pipeline: str,
        status: str,
    ) -> str:
        return self.log(
            operator_id=operator_id,
            action="run_complete",
            status=status,
            case_id=case_id,
            task_id=task_id,
            run_id=run_id,
            classification=classification,
            pipeline=pipeline,
        )

    def log_approval(
        self,
        *,
        operator_id: str,
        reviewer_id: str,
        run_id: str,
        task_id: str,
        case_id: str,
        decision: str,
        classification: str,
    ) -> str:
        return self.log(
            operator_id=operator_id,
            action="approval_decision",
            status=decision,
            case_id=case_id,
            task_id=task_id,
            run_id=run_id,
            classification=classification,
            detail=f"Reviewed by {reviewer_id}",
        )

    def log_cancellation(
        self,
        *,
        operator_id: str,
        run_id: str,
        task_id: str,
        case_id: str,
        classification: str,
    ) -> str:
        return self.log(
            operator_id=operator_id,
            action="cancellation",
            status="cancelled",
            case_id=case_id,
            task_id=task_id,
            run_id=run_id,
            classification=classification,
        )

    def log_memory_operation(
        self,
        *,
        operator_id: str,
        operation: str,
        case_id: str = "",
        task_id: str = "",
        classification: str = "RESTRICTED",
        detail: str = "",
    ) -> str:
        return self.log(
            operator_id=operator_id,
            action=f"memory_{operation}",
            status="completed",
            case_id=case_id,
            task_id=task_id,
            classification=classification,
            detail=detail[:2000],
        )

    def log_ingestion(
        self,
        *,
        operator_id: str,
        case_id: str,
        source_type: str,
        source_reference: str,
        classification: str = "RESTRICTED",
    ) -> str:
        return self.log(
            operator_id=operator_id,
            action="ingestion",
            status="completed",
            case_id=case_id,
            classification=classification,
            detail=f"source_type={source_type}; ref={source_reference[:500]}",
        )

    def query_by_case(self, case_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent audit entries for one case, newest first."""

        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_log WHERE case_id = ? ORDER BY timestamp DESC LIMIT ?",
                (case_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def query_by_run(self, run_id: str) -> list[dict[str, Any]]:
        """Return all audit entries for one run."""

        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_log WHERE run_id = ? ORDER BY timestamp ASC",
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def verify_integrity(self, entry: Mapping[str, Any]) -> bool:
        """Verify the integrity hash of a single audit entry."""

        expected = _row_hash(
            str(entry.get("timestamp", "")),
            str(entry.get("operator_id", "")),
            str(entry.get("case_id", "")),
            str(entry.get("task_id", "")),
            str(entry.get("action", "")),
            str(entry.get("classification", "")),
            str(entry.get("status", "")),
            str(entry.get("detail", ""))[:2000],
        )
        return entry.get("integrity_hash") == expected


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_audit_logger: AuditLogger | None = None
_audit_lock = Lock()


def get_audit_logger() -> AuditLogger:
    """Return the process-scoped audit logger."""

    global _audit_logger
    if _audit_logger is None:
        with _audit_lock:
            if _audit_logger is None:
                _audit_logger = AuditLogger()
    return _audit_logger
