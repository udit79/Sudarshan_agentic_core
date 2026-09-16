from __future__ import annotations

import time
import json
import sqlite3
import threading

import pytest

from api.scheduler import (
    LocalRunScheduler,
    RetryableSchedulerError,
    SchedulerConflictError,
)

def _wait_for(scheduler: LocalRunScheduler, run_id: str, expected: set[str], timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = scheduler.status(run_id)
        if state and state["status"] in expected:
            return state
        time.sleep(0.01)
    raise AssertionError(f"run {run_id} did not reach {expected}")

def _payload(run_id: str) -> dict[str, object]:
    return {
        "query": "Test fencing",
        "user_id": "operator-1",
        "case_id": "case-1",
        "task_id": run_id,
        "classification_level": "RESTRICTED",
        "distribution": "Authorized NTRO personnel",
        "requested_pipelines": ["executive_summary"],
        "metadata": {"run_id": run_id},
    }

def test_scheduler_prevents_stale_lease_overwrites(tmp_path) -> None:
    db_path = tmp_path / "queue.db"
    run_id = "task-fencing-1"

    barrier = threading.Barrier(2)
    executions = []

    def execute(payload, *, operator_id, attempt_id, lease_token, cancel_event=None):
        executions.append((attempt_id, lease_token))
        if len(executions) == 1:
            # First attempt: wait for main thread
            barrier.wait()
            # Wait for main thread to expire lease and finish attempt 2
            barrier.wait()
            return {"status": "succeeded", "skill_result": {"zombie": True}}
        else:
            return {"status": "succeeded", "skill_result": {"zombie": False}}

    scheduler = LocalRunScheduler(
        execute,
        db_path=db_path,
        max_workers=2,
        lease_ms=10000,
        max_attempts=2,
        retry_backoff_ms=0,
    )
    try:
        scheduler.submit(run_id, _payload(run_id), operator_id="operator-1")
        
        # Wait for the first attempt to freeze
        barrier.wait()

        # Expire lease manually
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("UPDATE run_queue SET lease_until = 0 WHERE run_id = ?", (run_id,))
            conn.commit()
        finally:
            conn.close()

        # Trigger reclaim explicitly
        scheduler._recover_expired_leases()
        for queued_id in scheduler._queued_ids():
            scheduler._executor.submit(scheduler._worker, queued_id)

        # Wait for attempt 2 to succeed
        _wait_for(scheduler, run_id, {"succeeded"})
        state = scheduler.status(run_id)
        assert state["status"] == "succeeded"
        assert state["skill_result"]["zombie"] is False

        # Wake up zombie
        barrier.wait()
        
        # Give zombie time to attempt DB update
        time.sleep(0.5)

        # Verify zombie did NOT overwrite the state
        final_state = scheduler.status(run_id)
        assert final_state["skill_result"]["zombie"] is False
        assert len(executions) == 2
    finally:
        scheduler.close()
