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
from threading import Event, Lock, Timer, Thread, current_thread
from typing import Any

from api.control_plane import (
    ControlPlane,
    ControlPlaneConflict,
    LeaseToken,
    QueueMessage,
    StaleLeaseError,
    new_worker_id,
)
from pipelines.common.correlation import HarnessCorrelation


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
        control_plane: ControlPlane | None = None,
        queue_name: str = "runs",
        queue_reclaim_idle_ms: int | None = None,
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
        if not str(queue_name).strip() or ":" in str(queue_name):
            raise ValueError("queue_name must be a non-empty name without ':'")
        if queue_reclaim_idle_ms is not None and queue_reclaim_idle_ms < 1:
            raise ValueError("queue_reclaim_idle_ms must be positive")
        self.execute = execute
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_workers = max_workers
        self.lease_seconds = lease_ms / 1000
        self.max_attempts = max_attempts
        self.retry_backoff_seconds = retry_backoff_ms / 1000
        self.execution_timeout_seconds = execution_timeout_ms / 1000
        self.control_plane = control_plane
        self.queue_name = str(queue_name).strip()
        self.queue_reclaim_idle_ms = queue_reclaim_idle_ms or max(1000, lease_ms * 2)
        self.worker_owner = new_worker_id("scheduler")
        self._lock = Lock()
        self._closed = Event()
        self._cancel_signals: dict[str, Event] = {}
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="sudarshan-run")
        self._initialise()
        self._recover_expired_leases()
        for run_id in self._queued_ids():
            self._executor.submit(self._worker, run_id)
        self._queue_thread: Thread | None = None
        if self.control_plane is not None and all(
            callable(getattr(self.control_plane, name, None)) for name in ("poll", "ack", "reclaim")
        ):
            self._queue_thread = Thread(
                target=self._discover_shared_queue,
                name=f"sudarshan-queue-{self.queue_name}",
                daemon=True,
            )
            self._queue_thread.start()

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
                    queue_wait_ms REAL,
                updated_at REAL NOT NULL,
                    lease_until REAL,
                    retry_at REAL,
                    dead_letter INTEGER NOT NULL DEFAULT 0,
                    skill_result_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_run_queue_status
                    ON run_queue(status, created_at);
                CREATE TABLE IF NOT EXISTS run_queue_events (
                    run_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT,
                    created_at REAL NOT NULL,
                    PRIMARY KEY(run_id, sequence)
                );
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
            if "queue_wait_ms" not in columns:
                connection.execute("ALTER TABLE run_queue ADD COLUMN queue_wait_ms REAL")

    @staticmethod
    def _request_hash(payload: Mapping[str, Any]) -> str:
        encoded = json.dumps(dict(payload), sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @classmethod
    def _identity_payload(cls, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """Exclude process-local ingestion paths from idempotency fingerprints."""

        if payload.get("job_type") != "ingestion":
            return payload
        identity = dict(payload)
        identity.pop("file_path", None)
        return identity

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

    def _record_event(
        self,
        run_id: str,
        event_type: str,
        status: str,
        message: str = "",
    ) -> None:
        now = time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) AS sequence FROM run_queue_events WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            sequence = int(row["sequence"]) + 1
            connection.execute(
                """
                INSERT INTO run_queue_events
                (run_id, sequence, event_type, status, message, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (run_id, sequence, str(event_type), str(status), str(message)[:2000], now),
            )
            connection.commit()

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
        harness_correlation = HarnessCorrelation.from_metadata(metadata)
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
            "harness_correlation": (
                harness_correlation.model_dump(mode="json")
                if harness_correlation is not None
                else None
            ),
            "job_type": str(payload.get("job_type", "run")),
            "source_reference": payload.get("source_reference"),
            "source_hash": payload.get("source_hash"),
            "source_object_id": payload.get("source_object_id"),
            "media_type": payload.get("media_type"),
            "modality": payload.get("modality"),
            "skill_result": skill_result,
            "created_at": float(row["created_at"]),
            "started_at": row["started_at"],
            "queue_wait_ms": row["queue_wait_ms"],
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
        request_hash = self._request_hash(self._identity_payload(queue_payload))
        if self.control_plane is not None:
            try:
                admission = self.control_plane.admit(
                    run_id,
                    request_hash,
                    queue_payload,
                    queue=self.queue_name,
                )
            except ControlPlaneConflict as exc:
                raise SchedulerConflictError(str(exc)) from exc
            if admission.replayed:
                state = self.status(run_id)
                if state is not None:
                    state["idempotent_replay"] = True
                    return state
                remote_state = self.control_plane.state(run_id) or {}
                return {
                    "run_id": run_id,
                    "task_id": task_id,
                    "case_id": case_id,
                    "status": str(remote_state.get("status", admission.status)),
                    "attempt": int(remote_state.get("attempt", "0") or 0),
                    "idempotent_replay": True,
                }
        with self._lock, self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM run_queue WHERE run_id = ?", (run_id,)
            ).fetchone()
            if existing:
                if str(existing["request_hash"]) != request_hash:
                    raise SchedulerConflictError("run_id was already used for a different request")
                state = self._row_state(existing)
                state["idempotent_replay"] = True
                return state
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
        self._record_event(run_id, "admitted", "queued", "Job admitted to the durable queue.")
        self._executor.submit(self._worker, run_id)
        return self.status(run_id) or {}

    def _hydrate_shared(self, run_id: str) -> bool:
        """Materialize a remotely admitted job into this worker's local queue."""

        if self.status(run_id) is not None or self.control_plane is None:
            return self.status(run_id) is not None
        remote = self.control_plane.state(run_id)
        if not remote or not remote.get("payload"):
            return False
        raw_payload = remote["payload"]
        if isinstance(raw_payload, Mapping):
            payload = dict(raw_payload)
        else:
            try:
                payload = json.loads(str(raw_payload))
            except (TypeError, ValueError):
                return False
        if not isinstance(payload, Mapping):
            return False
        status = str(remote.get("status", "queued"))
        if status in TERMINAL_STATES:
            return False
        now = time.time()
        task_id = str(payload.get("task_id", "shared-task"))
        case_id = str(payload.get("case_id", "shared-case"))
        request_hash = str(remote.get("request_hash", ""))
        if not request_hash:
            request_hash = self._request_hash(self._identity_payload(payload))
        with self._lock, self._connect() as connection:
            existing = connection.execute(
                "SELECT run_id FROM run_queue WHERE run_id = ?", (run_id,)
            ).fetchone()
            if existing:
                return True
            connection.execute(
                """
                INSERT INTO run_queue
                (run_id, task_id, case_id, operator_id, request_hash, request_json,
                 status, attempt, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)
                """,
                (
                    run_id,
                    task_id,
                    case_id,
                    str(payload.get("operator_id", "shared-worker")),
                    request_hash,
                    json.dumps(dict(payload), ensure_ascii=False, default=str),
                    int(remote.get("attempt", "0") or 0),
                    float(remote.get("created_at", now) or now),
                    now,
                ),
            )
        self._record_event(run_id, "admitted", "queued", "Job discovered from the shared queue.")
        return True

    def _consume_shared_message(self, message: QueueMessage) -> None:
        acknowledge = True
        try:
            remote = self.control_plane.state(message.resource_key)  # type: ignore[union-attr]
            if remote and str(remote.get("status", "")) == "running":
                # Keep a reclaimed message pending while another fenced worker
                # is still alive. Its completion path can acknowledge it; if
                # that worker dies, a later reclaim can safely retry it.
                acknowledge = False
                return
            if self._hydrate_shared(message.resource_key):
                self._worker(message.resource_key)
        finally:
            if acknowledge:
                self.control_plane.ack(message)  # type: ignore[union-attr]

    def _discover_shared_queue(self) -> None:
        """Discover jobs admitted by another process through Redis Streams."""

        while not self._closed.is_set():
            try:
                message = self.control_plane.poll(  # type: ignore[union-attr]
                    self.queue_name,
                    owner=self.worker_owner,
                    block_ms=250,
                )
            except Exception:
                # A transient Redis outage must not kill the local scheduler.
                if self._closed.wait(0.5):
                    return
                continue
            if message is not None and not self._closed.is_set():
                self._executor.submit(self._consume_shared_message, message)
                continue
            try:
                reclaimed = self.control_plane.reclaim(  # type: ignore[union-attr]
                    self.queue_name,
                    owner=self.worker_owner,
                    min_idle_ms=self.queue_reclaim_idle_ms,
                )
            except Exception:
                if self._closed.wait(0.5):
                    return
                continue
            if reclaimed is not None and not self._closed.is_set():
                self._executor.submit(self._consume_shared_message, reclaimed)

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
            queue_wait_ms = max(0.0, (now - float(row["created_at"])) * 1000)
            connection.execute(
                """
                UPDATE run_queue
                SET status = 'running', attempt = attempt + 1,
                    started_at = COALESCE(started_at, ?),
                    queue_wait_ms = COALESCE(queue_wait_ms, ?),
                    updated_at = ?, lease_until = ?
                WHERE run_id = ?
                """,
                (now, queue_wait_ms, now, lease_until, run_id),
            )
            connection.commit()
            claimed = connection.execute("SELECT * FROM run_queue WHERE run_id = ?", (run_id,)).fetchone()
        self._record_event(
            run_id,
            "started",
            "running",
            f"Worker lease acquired after {int(queue_wait_ms)}ms queue wait.",
        )
        return claimed

    def _requeue_local_claim(self, run_id: str) -> None:
        """Return a local claim to queued when the shared claim is unavailable."""

        now = time.time()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE run_queue
                SET status = 'queued', lease_until = NULL, updated_at = ?
                WHERE run_id = ? AND status = 'running'
                """,
                (now, run_id),
            )

    def _claim_shared(self, run_id: str) -> list[LeaseToken | None] | None:
        """Claim the shared fencing lease after the local row is claimed."""

        if self.control_plane is None:
            return [None]
        lease = self.control_plane.claim(
            run_id,
            owner=self.worker_owner,
            lease_seconds=self.lease_seconds,
        )
        if lease is None:
            self._requeue_local_claim(run_id)
            return None
        return [lease]

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

    def _heartbeat(
        self,
        run_id: str,
        stop: Event,
        lease_holder: list[LeaseToken | None],
        lease_lost: Event,
    ) -> None:
        """Renew a worker lease until execution completes or the row is terminal."""

        interval = max(0.05, min(30.0, self.lease_seconds / 3))
        while not stop.wait(interval):
            if not self._renew_lease(run_id):
                lease_lost.set()
                return
            if self.control_plane is not None and lease_holder[0] is not None:
                try:
                    lease_holder[0] = self.control_plane.renew(
                        lease_holder[0],
                        lease_seconds=self.lease_seconds,
                    )
                except StaleLeaseError:
                    lease_lost.set()
                    return

    def _set_terminal(
        self,
        run_id: str,
        status: str,
        error: str | None = None,
        *,
        dead_letter: bool = False,
        skill_result: Mapping[str, Any] | None = None,
        lease: LeaseToken | None = None,
    ) -> bool:
        if self.control_plane is not None and lease is not None:
            try:
                self.control_plane.transition(
                    lease,
                    status=status,
                    result={
                        "error": error,
                        "dead_letter": dead_letter,
                        "skill_result": dict(skill_result or {}),
                    },
                )
            except StaleLeaseError:
                return False
        now = time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
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
            row = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) AS sequence "
                "FROM run_queue_events WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            sequence = int(row["sequence"]) + 1
            connection.execute(
                """
                INSERT INTO run_queue_events
                    (run_id, sequence, event_type, status, message, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (run_id, sequence, "completed", status, error or status, now),
            )
            connection.commit()
        return True

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
            self._record_event(run_id, "requeued", "queued", "Retry backoff elapsed; job requeued.")
            self._executor.submit(self._worker, run_id)

    def _schedule_retry(self, run_id: str, error: str, *, lease: LeaseToken | None = None) -> bool:
        retry_at = time.time() + self.retry_backoff_seconds
        if self.control_plane is not None and lease is not None:
            try:
                self.control_plane.schedule_retry(lease, retry_at=retry_at, error=error)
            except StaleLeaseError:
                return False
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
        self._record_event(run_id, "retrying", "retrying", "Transient execution failure; retry scheduled.")
        timer = Timer(self.retry_backoff_seconds, self._release_retry, args=(run_id,))
        timer.daemon = True
        timer.start()
        return True

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
        lease_holder = self._claim_shared(run_id)
        if lease_holder is None:
            return
        payload = json.loads(str(row["request_json"]))
        with self._lock:
            cancel_event = self._cancel_signals.setdefault(run_id, Event())
        heartbeat_stop = Event()
        lease_lost = Event()
        heartbeat = Thread(
            target=self._heartbeat,
            args=(run_id, heartbeat_stop, lease_holder, lease_lost),
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
            if lease_lost.is_set():
                return
            status = str(result.get("status", "succeeded"))
            if status == "failed" and bool(result.get("retryable", False)):
                raise RetryableSchedulerError(self._failure_message(result.get("error") or result.get("failure")))
            self._set_terminal(
                run_id,
                status if status in TERMINAL_STATES else "completed",
                self._failure_message(result.get("error")) if status == "failed" else None,
                skill_result=result.get("skill_result") if isinstance(result.get("skill_result"), Mapping) else None,
                lease=lease_holder[0],
            )
        except SchedulerCancellationError as exc:
            if not lease_lost.is_set():
                self._set_terminal(run_id, "cancelled", str(exc)[:2000], lease=lease_holder[0])
        except Exception as exc:
            if lease_lost.is_set():
                return
            error = f"{type(exc).__name__}: {exc}"[:2000]
            retryable = self._is_retryable_exception(exc)
            attempt = int(row["attempt"])
            if retryable and attempt < self.max_attempts:
                self._schedule_retry(run_id, error, lease=lease_holder[0])
            else:
                self._set_terminal(
                    run_id,
                    "failed",
                    error,
                    dead_letter=retryable,
                    lease=lease_holder[0],
                )
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
            wait_row = connection.execute(
                "SELECT AVG(queue_wait_ms) AS average_wait, MAX(queue_wait_ms) AS maximum_wait "
                "FROM run_queue WHERE queue_wait_ms IS NOT NULL"
            ).fetchone()
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
            "average_queue_wait_ms": int(float(wait_row["average_wait"] or 0)),
            "maximum_queue_wait_ms": int(float(wait_row["maximum_wait"] or 0)),
        }

    def status(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM run_queue WHERE run_id = ?", (str(run_id),)).fetchone()
        return self._row_state(row) if row else None

    def events(self, run_id: str, *, after_sequence: int = 0) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT sequence, event_type, status, message, created_at
                FROM run_queue_events
                WHERE run_id = ? AND sequence > ?
                ORDER BY sequence
                """,
                (str(run_id), int(after_sequence)),
            ).fetchall()
        return [
            {
                "sequence": int(row["sequence"]),
                "event_type": str(row["event_type"]),
                "status": str(row["status"]),
                "message": str(row["message"] or ""),
                "created_at": float(row["created_at"]),
            }
            for row in rows
        ]

    def cancel(self, run_id: str) -> dict[str, Any] | None:
        now = time.time()
        with self._lock:
            signal = self._cancel_signals.get(str(run_id))
            if signal is not None:
                signal.set()
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE run_queue SET status = 'cancelled', updated_at = ?, lease_until = NULL, retry_at = NULL WHERE run_id = ? AND status IN ('queued', 'retrying')",
                (now, str(run_id)),
            )
        if cursor.rowcount == 1:
            self._record_event(str(run_id), "cancelled", "cancelled", "Cancellation requested before worker execution.")
        return self.status(run_id)

    def close(self) -> None:
        self._closed.set()
        with self._lock:
            for signal in self._cancel_signals.values():
                signal.set()
        self._executor.shutdown(wait=False, cancel_futures=True)
        if self._queue_thread is not None and self._queue_thread is not current_thread():
            self._queue_thread.join(timeout=1)


__all__ = [
    "LocalRunScheduler",
    "NonRetryableSchedulerError",
    "RetryableSchedulerError",
    "SchedulerConflictError",
    "SchedulerCancellationError",
    "SchedulerExecutionTimeout",
    "TERMINAL_STATES",
]
