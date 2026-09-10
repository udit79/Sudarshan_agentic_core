from __future__ import annotations

import threading
import time
import json
import sqlite3

import pytest

from api.scheduler import (
    LocalRunScheduler,
    NonRetryableSchedulerError,
    RetryableSchedulerError,
    SchedulerConflictError,
)


def _wait_for(scheduler: LocalRunScheduler, run_id: str, expected: set[str], timeout: float = 2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = scheduler.status(run_id)
        if state and state["status"] in expected:
            return state
        time.sleep(0.01)
    raise AssertionError(f"run {run_id} did not reach {expected}")


def _payload(run_id: str) -> dict[str, object]:
    return {
        "query": "Prepare the case brief",
        "user_id": "operator-1",
        "case_id": "case-1",
        "task_id": run_id,
        "classification_level": "RESTRICTED",
        "distribution": "Authorized NTRO personnel",
        "requested_pipelines": ["executive_summary"],
        "metadata": {"run_id": run_id},
    }


def test_scheduler_persists_admission_and_rejects_run_id_reuse(tmp_path) -> None:
    calls: list[str] = []

    def execute(payload, *, operator_id):
        calls.append(f"{payload['task_id']}:{operator_id}")
        return {"status": "succeeded"}

    scheduler = LocalRunScheduler(execute, db_path=tmp_path / "queue.db", max_workers=1)
    try:
        request = _payload("task-1")
        request["metadata"] = {
            "run_id": "run-1",
            "resolved_memory_context": "must not be persisted",
            "system_prompt": "must not be persisted",
        }
        accepted = scheduler.submit("run-1", request, operator_id="operator-1")
        completed = _wait_for(scheduler, "run-1", {"succeeded"})
        duplicate_request = _payload("task-1")
        duplicate_request["metadata"] = {"run_id": "run-1"}
        duplicate = scheduler.submit("run-1", duplicate_request, operator_id="operator-1")

        assert accepted["run_id"] == "run-1"
        assert completed["status"] == "succeeded"
        assert duplicate["status"] == "succeeded"
        assert calls == ["task-1:operator-1"]
        raw_queue = (tmp_path / "queue.db").read_bytes()
        assert b"must not be persisted" not in raw_queue
        conflicting = _payload("task-1")
        conflicting["query"] = "A different request"
        with pytest.raises(SchedulerConflictError):
            scheduler.submit("run-1", conflicting, operator_id="operator-1")
    finally:
        scheduler.close()


def test_scheduler_cancels_a_queued_job_before_worker_admission(tmp_path) -> None:
    release_first = threading.Event()
    started_first = threading.Event()

    def execute(payload, *, operator_id):
        if payload["task_id"] == "task-1":
            started_first.set()
            release_first.wait(2)
        return {"status": "succeeded"}

    scheduler = LocalRunScheduler(execute, db_path=tmp_path / "queue.db", max_workers=1)
    try:
        scheduler.submit("run-1", _payload("task-1"), operator_id="operator-1")
        assert started_first.wait(1)
        scheduler.submit("run-2", _payload("task-2"), operator_id="operator-1")
        cancelled = scheduler.cancel("run-2")
        release_first.set()

        assert cancelled["status"] == "cancelled"
        assert _wait_for(scheduler, "run-1", {"succeeded"})["status"] == "succeeded"
        assert scheduler.status("run-2")["status"] == "cancelled"
    finally:
        release_first.set()
        scheduler.close()


def test_scheduler_renews_a_live_worker_lease(tmp_path) -> None:
    started = threading.Event()
    release = threading.Event()

    def execute(payload, *, operator_id):
        started.set()
        release.wait(2)
        return {"status": "succeeded"}

    scheduler = LocalRunScheduler(
        execute,
        db_path=tmp_path / "queue.db",
        max_workers=1,
        lease_ms=120,
    )
    try:
        scheduler.submit("run-live", _payload("task-live"), operator_id="operator-1")
        assert started.wait(1)
        with sqlite3.connect(tmp_path / "queue.db") as connection:
            before = float(
                connection.execute(
                    "SELECT lease_until FROM run_queue WHERE run_id = ?", ("run-live",)
                ).fetchone()[0]
            )
        time.sleep(0.18)
        with sqlite3.connect(tmp_path / "queue.db") as connection:
            after = float(
                connection.execute(
                    "SELECT lease_until FROM run_queue WHERE run_id = ?", ("run-live",)
                ).fetchone()[0]
            )
        assert after > before
        release.set()
        assert _wait_for(scheduler, "run-live", {"succeeded"})["status"] == "succeeded"
    finally:
        release.set()
        scheduler.close()


def test_scheduler_recovers_an_expired_worker_lease(tmp_path) -> None:
    db_path = tmp_path / "queue.db"
    request = _payload("task-recovered")
    now = time.time()
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE run_queue (
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
                lease_until REAL
            );
            CREATE INDEX idx_run_queue_status ON run_queue(status, created_at);
            """
        )
        connection.execute(
            """
            INSERT INTO run_queue
            (run_id, task_id, case_id, operator_id, request_hash, request_json,
             status, attempt, created_at, started_at, updated_at, lease_until)
            VALUES (?, ?, ?, ?, ?, ?, 'running', 1, ?, ?, ?, ?)
            """,
            (
                "run-recovered",
                "task-recovered",
                "case-1",
                "operator-1",
                "stale-hash",
                json.dumps(request),
                now - 10,
                now - 10,
                now - 10,
                now - 1,
            ),
        )

    calls: list[str] = []

    def execute(payload, *, operator_id):
        calls.append(str(payload["task_id"]))
        return {"status": "succeeded"}

    scheduler = LocalRunScheduler(execute, db_path=db_path, max_workers=1)
    try:
        assert _wait_for(scheduler, "run-recovered", {"succeeded"})["status"] == "succeeded"
        assert calls == ["task-recovered"]
        assert scheduler.metrics()["succeeded"] == 1
    finally:
        scheduler.close()


def test_scheduler_retries_explicitly_transient_failure(tmp_path) -> None:
    attempts: list[int] = []

    def execute(payload, *, operator_id):
        attempts.append(1)
        if len(attempts) == 1:
            raise RetryableSchedulerError("provider temporarily unavailable")
        return {"status": "succeeded"}

    scheduler = LocalRunScheduler(
        execute,
        db_path=tmp_path / "queue.db",
        max_workers=1,
        max_attempts=2,
        retry_backoff_ms=10,
    )
    try:
        scheduler.submit("run-retry", _payload("task-retry"), operator_id="operator-1")
        completed = _wait_for(scheduler, "run-retry", {"succeeded"})
        assert completed["attempt"] == 2
        assert attempts == [1, 1]
        assert completed["dead_letter"] is False
        assert scheduler.metrics()["retrying"] == 0
    finally:
        scheduler.close()


def test_scheduler_does_not_retry_non_retryable_failure(tmp_path) -> None:
    attempts: list[int] = []

    def execute(payload, *, operator_id):
        attempts.append(1)
        raise NonRetryableSchedulerError("invalid artifact request")

    scheduler = LocalRunScheduler(
        execute,
        db_path=tmp_path / "queue.db",
        max_workers=1,
        max_attempts=3,
    )
    try:
        scheduler.submit("run-no-retry", _payload("task-no-retry"), operator_id="operator-1")
        failed = _wait_for(scheduler, "run-no-retry", {"failed"})
        assert failed["attempt"] == 1
        assert failed["dead_letter"] is False
        assert attempts == [1]
    finally:
        scheduler.close()


def test_scheduler_dead_letters_exhausted_retryable_failure(tmp_path) -> None:
    def execute(payload, *, operator_id):
        raise RetryableSchedulerError("provider remained unavailable")

    scheduler = LocalRunScheduler(
        execute,
        db_path=tmp_path / "queue.db",
        max_workers=1,
        max_attempts=2,
        retry_backoff_ms=10,
    )
    try:
        scheduler.submit("run-dead", _payload("task-dead"), operator_id="operator-1")
        failed = _wait_for(scheduler, "run-dead", {"failed"})
        assert failed["attempt"] == 2
        assert failed["dead_letter"] is True
        assert scheduler.metrics()["dead_letter"] == 1
    finally:
        scheduler.close()


def test_scheduler_marks_execution_deadline_as_retryable_failure(tmp_path) -> None:
    release = threading.Event()

    def execute(payload, *, operator_id):
        release.wait(2)
        return {"status": "succeeded"}

    scheduler = LocalRunScheduler(
        execute,
        db_path=tmp_path / "queue.db",
        max_workers=1,
        execution_timeout_ms=30,
    )
    try:
        scheduler.submit("run-timeout", _payload("task-timeout"), operator_id="operator-1")
        failed = _wait_for(scheduler, "run-timeout", {"failed"})
        assert failed["dead_letter"] is True
        assert "SchedulerExecutionTimeout" in failed["error"]
    finally:
        release.set()
        scheduler.close()


def test_scheduler_propagates_running_cancellation_to_compatible_callback(tmp_path) -> None:
    started = threading.Event()
    observed = threading.Event()

    def execute(payload, *, operator_id, cancel_event):
        started.set()
        while not cancel_event.wait(0.01):
            pass
        observed.set()
        return {"status": "cancelled"}

    scheduler = LocalRunScheduler(execute, db_path=tmp_path / "queue.db", max_workers=1)
    try:
        scheduler.submit("run-cancel", _payload("task-cancel"), operator_id="operator-1")
        assert started.wait(1)
        scheduler.cancel("run-cancel")
        cancelled = _wait_for(scheduler, "run-cancel", {"cancelled"})
        assert cancelled["status"] == "cancelled"
        assert observed.is_set()
    finally:
        scheduler.close()
