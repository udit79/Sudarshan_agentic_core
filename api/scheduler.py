"""Small durable scheduler for API-owned run admission.

The scheduler persists admission and worker-lease state, while the existing
application/orchestrator remains responsible for graph execution and durable
pipeline state. It intentionally stores no model output or raw memory.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import sqlite3
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path
from threading import Event, Lock, Timer, Thread
from typing import Any


TERMINAL_STATES = {"succeeded", "partial", "failed", "cancelled", "completed", "pending"}


class RetryableSchedulerError(RuntimeError):
    """An execution failure that may safely be retried with the same run ID."""


class NonRetryableSchedulerError(RuntimeError):
    """An execution failure that must not be retried automatically."""


class SchedulerExecutionTimeout(RetryableSchedulerError):
    """The scheduler-side execution deadline elapsed."""


class SchedulerCancellationError(NonRetryableSchedulerError):
    """A cooperative cancellation signal interrupted scheduler execution."""


class SchedulerConflictError(ValueError):
    """Raised when a run identity is reused for a different request."""


class LocalRunScheduler:
    """Persist queued jobs and admit them through a bounded worker pool."""

    def __init__(
        self,
        execute: Callable[..., Mapping[str, Any]],
        *,
        db_path: str | Path = "artifacts/.state/run_queue.db",
        max_workers: int = 2,
        lease_ms: int = 900_000,
        max_attempts: int = 1,
        retry_backoff_ms: int = 250,
        execution_timeout_ms: int = 0,
    ) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be positive")
        if lease_ms < 1:
            raise ValueError("lease_ms must be positive")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if retry_backoff_ms < 0:
            raise ValueError("retry_backoff_ms must not be negative")
        if execution_timeout_ms < 0:
            raise ValueError("execution_timeout_ms must not be negative")
        self.execute = execute
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_workers = max_workers
        self.lease_seconds = lease_ms / 1000
        self.max_attempts = max_attempts
        self.retry_backoff_seconds = retry_backoff_ms / 1000
        self.execution_timeout_seconds = execution_timeout_ms / 1000
        self._lock = Lock()
        self._closed = Event()
        self._cancel_signals: dict[str, Event] = {}
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="sudarshan-run")
        self._initialise()
        self._recover_expired_leases()
        for run_id in self._queued_ids():
            self._executor.submit(self._worker, run_id)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path), timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialise(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS run_queue (
                    run_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    operator_id TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    created_at REAL NOT NULL,
                    started_at REAL,
                updated_at REAL NOT NULL,
                    lease_until REAL,
                    retry_at REAL,
                    dead_letter INTEGER NOT NULL DEFAULT 0,
                    skill_result_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_run_queue_status
                    ON run_queue(status, created_at);
                """
            )
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(run_queue)").fetchall()
            }
            if "retry_at" not in columns:
                connection.execute("ALTER TABLE run_queue ADD COLUMN retry_at REAL")
            if "dead_letter" not in columns:
                connection.execute(
                    "ALTER TABLE run_queue ADD COLUMN dead_letter INTEGER NOT NULL DEFAULT 0"
                )
            if "skill_result_json" not in columns:
                connection.execute("ALTER TABLE run_queue ADD COLUMN skill_result_json TEXT")

    @staticmethod
    def _request_hash(payload: Mapping[str, Any]) -> str:
        encoded = json.dumps(dict(payload), sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _queue_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
        """Keep restart inputs while excluding memory and prompt internals."""

        safe = dict(payload)
        metadata = dict(safe.get("metadata") or {})
        for key in {
            "resolved_memory_context",
            "resolved_memory_records",
            "raw_memory",
            "cognee_raw",
            "cognee_response",
            "system_prompt",
            "chain_of_thought",
            "model_reasoning",
        }:
            metadata.pop(key, None)
        safe["metadata"] = metadata
        return safe

    def _recover_expired_leases(self) -> None:
        now = time.time()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE run_queue
                SET status = 'queued', lease_until = NULL, updated_at = ?
                WHERE status = 'running' AND lease_until IS NOT NULL AND lease_until < ?
                """,
                (now, now),
            )
            connection.execute(
                """
                UPDATE run_queue
                SET status = 'queued', retry_at = NULL, updated_at = ?
                WHERE status = 'retrying' AND (retry_at IS NULL OR retry_at <= ?)
                """,
                (now, now),
            )

    def _queued_ids(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT run_id FROM run_queue WHERE status = 'queued' ORDER BY created_at"
            ).fetchall()
        return [str(row["run_id"]) for row in rows]

    @staticmethod
    def _row_state(row: sqlite3.Row) -> dict[str, Any]:
        payload = json.loads(str(row["request_json"]))
        metadata = dict(payload.get("metadata") or {})
        skill_result = None
        if "skill_result_json" in row.keys() and row["skill_result_json"]:
            try:
                skill_result = json.loads(str(row["skill_result_json"]))
            except (TypeError, ValueError):
                skill_result = None
        return {
            "run_id": str(row["run_id"]),
            "task_id": str(row["task_id"]),
            "case_id": str(row["case_id"]),
            "status": str(row["status"]),
            "attempt": int(row["attempt"]),
            "error": row["error"],
            "classification_level": str(payload.get("classification_level", "RESTRICTED")),
            "distribution": str(payload.get("distribution", "Authorized NTRO personnel")),
            "requested_pipelines": list(payload.get("requested_pipelines") or []),
            "skill_id": metadata.get("skill_id"),
            "skill_version": metadata.get("skill_version"),
            "skill_result": skill_result,
            "created_at": float(row["created_at"]),
            "started_at": row["started_at"],
            "updated_at": float(row["updated_at"]),
            "dead_letter": bool(row["dead_letter"]),
        }

    def submit(
        self,
        run_id: str,
        payload: Mapping[str, Any],
        *,
        operator_id: str,
    ) -> dict[str, Any]:
        run_id = str(run_id).strip()
        if not run_id:
            raise ValueError("run_id is required")
        task_id = str(payload.get("task_id", "")).strip()
        case_id = str(payload.get("case_id", "")).strip()
        if not task_id or not case_id:
            raise ValueError("task_id and case_id are required")
        now = time.time()
        queue_payload = self._queue_payload(payload)
        request_hash = self._request_hash(queue_payload)
        with self._lock, self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM run_queue WHERE run_id = ?", (run_id,)
            ).fetchone()
            if existing:
                if str(existing["request_hash"]) != request_hash:
                    raise SchedulerConflictError("run_id was already used for a different request")
                return self._row_state(existing)
            connection.execute(
                """
                INSERT INTO run_queue
                (run_id, task_id, case_id, operator_id, request_hash, request_json,
                 status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?)
                """,
                (
                    run_id,
                    task_id,
                    case_id,
                    str(operator_id).strip(),
                    request_hash,
                    json.dumps(queue_payload, ensure_ascii=False, default=str),
                    now,
                    now,
                ),
            )
        self._executor.submit(self._worker, run_id)
        return self.status(run_id) or {}

    def _claim(self, run_id: str) -> sqlite3.Row | None:
        now = time.time()
        lease_until = now + self.lease_seconds
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM run_queue WHERE run_id = ?", (run_id,)
            ).fetchone()
            if not row:
                connection.commit()
                return None
            if row["status"] not in {"queued", "running"}:
                connection.commit()
                return None
            if row["status"] == "running" and row["lease_until"] and float(row["lease_until"]) >= now:
                connection.commit()
                return None
            connection.execute(
                """
                UPDATE run_queue
                SET status = 'running', attempt = attempt + 1,
                    started_at = COALESCE(started_at, ?), updated_at = ?, lease_until = ?
                WHERE run_id = ?
                """,
                (now, now, lease_until, run_id),
            )
            connection.commit()
            return connection.execute("SELECT * FROM run_queue WHERE run_id = ?", (run_id,)).fetchone()

    def _renew_lease(self, run_id: str) -> bool:
        """Extend a healthy worker lease without changing logical run state."""

        now = time.time()
        lease_until = now + self.lease_seconds
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE run_queue
                SET lease_until = ?, updated_at = ?
                WHERE run_id = ? AND status = 'running'
                """,
                (lease_until, now, run_id),
            )
        return cursor.rowcount == 1

    def _heartbeat(self, run_id: str, stop: Event) -> None:
        """Renew a worker lease until execution completes or the row is terminal."""

        interval = max(0.05, min(30.0, self.lease_seconds / 3))
        while not stop.wait(interval):
            if not self._renew_lease(run_id):
                return

    def _set_terminal(
        self,
        run_id: str,
        status: str,
        error: str | None = None,
        *,
        dead_letter: bool = False,
        skill_result: Mapping[str, Any] | None = None,
    ) -> None:
        now = time.time()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE run_queue
                SET status = ?, error = ?, updated_at = ?, lease_until = NULL,
                    retry_at = NULL, dead_letter = ?, skill_result_json = ?
                WHERE run_id = ?
                """,
                (
                    status,
                    error,
                    now,
                    int(dead_letter),
                    json.dumps(dict(skill_result), ensure_ascii=False, default=str)
                    if skill_result is not None else None,
                    run_id,
                ),
            )

    def _release_retry(self, run_id: str) -> None:
        if self._closed.is_set():
            return
        now = time.time()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE run_queue
                SET status = 'queued', retry_at = NULL, updated_at = ?
                WHERE run_id = ? AND status = 'retrying'
                """,
                (now, run_id),
            )
        if cursor.rowcount == 1 and not self._closed.is_set():
            self._executor.submit(self._worker, run_id)

    def _schedule_retry(self, run_id: str, error: str) -> None:
        retry_at = time.time() + self.retry_backoff_seconds
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE run_queue
                SET status = 'retrying', error = ?, retry_at = ?,
                    updated_at = ?, lease_until = NULL
                WHERE run_id = ?
                """,
                (error, retry_at, time.time(), run_id),
            )
        timer = Timer(self.retry_backoff_seconds, self._release_retry, args=(run_id,))
        timer.daemon = True
        timer.start()

    @staticmethod
    def _is_retryable_exception(exc: Exception) -> bool:
        return isinstance(exc, (RetryableSchedulerError, TimeoutError, ConnectionError))

    @staticmethod
    def _failure_message(value: Any) -> str:
        return str(value or "scheduler execution failed")[:2000]

    def _invoke_execute(
        self,
        payload: Mapping[str, Any],
        operator_id: str,
        cancel_event: Event,
    ) -> Mapping[str, Any]:
        """Call old callbacks unchanged while enabling cooperative cancellation."""

        try:
            parameters = inspect.signature(self.execute).parameters
            supports_event = "cancel_event" in parameters or any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in parameters.values()
            )
        except (TypeError, ValueError):
            supports_event = False
        kwargs: dict[str, Any] = {"operator_id": operator_id}
        if supports_event:
            kwargs["cancel_event"] = cancel_event
        result = self.execute(payload, **kwargs)
        return result if isinstance(result, Mapping) else {"status": "succeeded"}

    def _execute_with_timeout(
        self,
        payload: Mapping[str, Any],
        operator_id: str,
        cancel_event: Event,
    ) -> Mapping[str, Any]:
        if self.execution_timeout_seconds <= 0:
            if cancel_event.is_set():
                raise SchedulerCancellationError("execution cancelled before admission")
            return self._invoke_execute(payload, operator_id, cancel_event)
        child_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sudarshan-call")
        future = child_executor.submit(self._invoke_execute, payload, operator_id, cancel_event)
        deadline = time.monotonic() + self.execution_timeout_seconds
        try:
            while True:
                if cancel_event.is_set():
                    future.cancel()
                    raise SchedulerCancellationError("execution cancelled cooperatively")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    future.cancel()
                    raise SchedulerExecutionTimeout(
                        f"execution exceeded {int(self.execution_timeout_seconds * 1000)}ms"
                    )
                try:
                    return future.result(timeout=min(0.05, remaining))
                except FutureTimeoutError:
                    continue
        finally:
            # Python cannot forcibly stop a running thread. The scheduler frees
            # its worker slot, while provider adapters must use their own
            # cooperative timeout/cancellation controls.
            child_executor.shutdown(wait=False, cancel_futures=True)

    def _worker(self, run_id: str) -> None:
        row = self._claim(run_id)
        if not row:
            return
        payload = json.loads(str(row["request_json"]))
        with self._lock:
            cancel_event = self._cancel_signals.setdefault(run_id, Event())
        heartbeat_stop = Event()
        heartbeat = Thread(
            target=self._heartbeat,
            args=(run_id, heartbeat_stop),
            name=f"sudarshan-lease-{run_id}",
            daemon=True,
        )
        heartbeat.start()
        try:
            result = self._execute_with_timeout(
                payload,
                operator_id=str(row["operator_id"]),
                cancel_event=cancel_event,
            )
            status = str(result.get("status", "succeeded"))
            if status == "failed" and bool(result.get("retryable", False)):
                raise RetryableSchedulerError(self._failure_message(result.get("error") or result.get("failure")))
            self._set_terminal(
                run_id,
                status if status in TERMINAL_STATES else "completed",
                self._failure_message(result.get("error")) if status == "failed" else None,
                skill_result=result.get("skill_result") if isinstance(result.get("skill_result"), Mapping) else None,
            )
        except SchedulerCancellationError as exc:
            self._set_terminal(run_id, "cancelled", str(exc)[:2000])
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:2000]
            retryable = self._is_retryable_exception(exc)
            attempt = int(row["attempt"])
            if retryable and attempt < self.max_attempts:
                self._schedule_retry(run_id, error)
            else:
                self._set_terminal(run_id, "failed", error, dead_letter=retryable)
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=max(0.1, min(1.0, self.lease_seconds)))
            with self._lock:
                self._cancel_signals.pop(run_id, None)

    def metrics(self) -> dict[str, int]:
        """Return queue counts safe to expose through the health endpoint."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT status, dead_letter, COUNT(*) AS count FROM run_queue GROUP BY status, dead_letter"
            ).fetchall()
        counts: dict[str, int] = {}
        dead_letter_count = 0
        for row in rows:
            status = str(row["status"])
            count = int(row["count"])
            counts[status] = counts.get(status, 0) + count
            if status == "failed" and bool(row["dead_letter"]):
                dead_letter_count += count
        return {
            "queued": counts.get("queued", 0),
            "running": counts.get("running", 0),
            "succeeded": counts.get("succeeded", 0),
            "partial": counts.get("partial", 0),
            "failed": counts.get("failed", 0),
            "cancelled": counts.get("cancelled", 0),
            "retrying": counts.get("retrying", 0),
            "dead_letter": dead_letter_count,
            "max_workers": self.max_workers,
            "lease_ms": int(self.lease_seconds * 1000),
            "max_attempts": self.max_attempts,
        }

    def status(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM run_queue WHERE run_id = ?", (str(run_id),)).fetchone()
        return self._row_state(row) if row else None

    def cancel(self, run_id: str) -> dict[str, Any] | None:
        now = time.time()
        with self._lock:
            signal = self._cancel_signals.get(str(run_id))
            if signal is not None:
                signal.set()
        with self._connect() as connection:
            connection.execute(
                "UPDATE run_queue SET status = 'cancelled', updated_at = ?, lease_until = NULL, retry_at = NULL WHERE run_id = ? AND status IN ('queued', 'retrying')",
                (now, str(run_id)),
            )
        return self.status(run_id)

    def close(self) -> None:
        self._closed.set()
        with self._lock:
            for signal in self._cancel_signals.values():
                signal.set()
        self._executor.shutdown(wait=False, cancel_futures=True)


__all__ = [
    "LocalRunScheduler",
    "NonRetryableSchedulerError",
    "RetryableSchedulerError",
    "SchedulerConflictError",
    "SchedulerCancellationError",
    "SchedulerExecutionTimeout",
    "TERMINAL_STATES",
]
