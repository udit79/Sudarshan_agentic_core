from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock
from time import monotonic, sleep

import pytest

from api.artifacts import ArtifactStore
from api.scheduler import (
    LocalRunScheduler,
    RetryableSchedulerError,
    SchedulerCancellationError,
    SchedulerConflictError,
)


def _payload(*, task_id: str = "task-1", case_id: str = "case-1", query: str = "same request") -> dict[str, object]:
    return {
        "task_id": task_id,
        "case_id": case_id,
        "user_id": "user-1",
        "query": query,
    }


def _wait_for(scheduler: LocalRunScheduler, run_id: str, expected: set[str], timeout: float = 3.0):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        state = scheduler.status(run_id)
        if state and state["status"] in expected:
            return state
        sleep(0.01)
    raise AssertionError(f"run {run_id} did not reach {expected}: {scheduler.status(run_id)}")


def test_concurrent_duplicate_submission_creates_one_logical_run_and_one_execution(tmp_path) -> None:
    calls: list[str] = []
    calls_lock = Lock()

    def execute(payload, *, operator_id):
        del operator_id
        with calls_lock:
            calls.append(str(payload["query"]))
        sleep(0.05)
        return {"status": "succeeded", "skill_result": {"artifact_id": "artifact-once"}}

    scheduler = LocalRunScheduler(execute, db_path=tmp_path / "queue.db", max_workers=4)
    barrier = Barrier(8)
    try:
        def submit_once():
            barrier.wait()
            return scheduler.submit("run-duplicate", _payload(), operator_id="operator-1")

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _item: submit_once(), range(8)))
        final = _wait_for(scheduler, "run-duplicate", {"succeeded"})

        assert all(result["run_id"] == "run-duplicate" for result in results)
        assert sum(bool(result.get("idempotent_replay")) for result in results) >= 1
        assert calls == ["same request"]
        assert final["attempt"] == 1
        assert final["skill_result"] == {"artifact_id": "artifact-once"}
    finally:
        scheduler.close()


def test_reusing_run_id_for_different_request_is_rejected_before_second_execution(tmp_path) -> None:
    calls: list[str] = []

    def execute(payload, *, operator_id):
        del operator_id
        calls.append(str(payload["query"]))
        return {"status": "succeeded"}

    scheduler = LocalRunScheduler(execute, db_path=tmp_path / "queue.db", max_workers=1)
    try:
        scheduler.submit("run-conflict", _payload(query="original"), operator_id="operator-1")
        _wait_for(scheduler, "run-conflict", {"succeeded"})
        with pytest.raises(SchedulerConflictError, match="different request"):
            scheduler.submit("run-conflict", _payload(query="changed"), operator_id="operator-1")
        assert calls == ["original"]
    finally:
        scheduler.close()


def test_retry_reuses_one_logical_run_and_increments_attempt_without_duplicate_admission(tmp_path) -> None:
    attempts: list[int] = []

    def execute(_payload, *, operator_id, attempt_id=None, lease_token=None):
        del operator_id, lease_token
        attempts.append(len(attempts) + 1)
        if len(attempts) == 1:
            raise RetryableSchedulerError("temporary provider failure")
        return {"status": "succeeded", "skill_result": {"attempt_id": attempt_id}}

    scheduler = LocalRunScheduler(
        execute,
        db_path=tmp_path / "queue.db",
        max_workers=1,
        max_attempts=2,
        retry_backoff_ms=1,
    )
    try:
        scheduler.submit("run-retry", _payload(), operator_id="operator-1")
        final = _wait_for(scheduler, "run-retry", {"succeeded", "failed"})
        assert final["status"] == "succeeded"
        assert final["attempt"] == 2
        assert len(attempts) == 2
    finally:
        scheduler.close()


def test_same_task_can_run_under_two_run_ids_but_is_not_implicitly_deduplicated(tmp_path) -> None:
    calls: list[tuple[str, str]] = []
    calls_lock = Lock()

    def execute(payload, *, operator_id):
        del operator_id
        with calls_lock:
            calls.append((str(payload["task_id"]), str(payload["case_id"])))
        sleep(0.02)
        return {"status": "succeeded"}

    scheduler = LocalRunScheduler(execute, db_path=tmp_path / "queue.db", max_workers=2)
    try:
        scheduler.submit("run-task-a", _payload(task_id="same-task"), operator_id="operator-1")
        scheduler.submit("run-task-b", _payload(task_id="same-task"), operator_id="operator-1")
        _wait_for(scheduler, "run-task-a", {"succeeded"})
        _wait_for(scheduler, "run-task-b", {"succeeded"})
        assert calls.count(("same-task", "case-1")) == 2
    finally:
        scheduler.close()


def test_parallel_runs_keep_case_scope_and_artifact_reference_separate(tmp_path) -> None:
    calls: list[tuple[str, str]] = []
    calls_lock = Lock()

    def execute(payload, *, operator_id):
        del operator_id
        with calls_lock:
            calls.append((str(payload["case_id"]), str(payload["query"])))
        return {
            "status": "succeeded",
            "skill_result": {"artifact_id": f"artifact-{payload['case_id']}"},
        }

    scheduler = LocalRunScheduler(execute, db_path=tmp_path / "queue.db", max_workers=2)
    try:
        scheduler.submit("run-case-a", _payload(case_id="case-a", query="evidence A"), operator_id="operator-1")
        scheduler.submit("run-case-b", _payload(case_id="case-b", query="evidence B"), operator_id="operator-1")
        state_a = _wait_for(scheduler, "run-case-a", {"succeeded"})
        state_b = _wait_for(scheduler, "run-case-b", {"succeeded"})

        assert state_a["case_id"] == "case-a"
        assert state_b["case_id"] == "case-b"
        assert state_a["skill_result"] == {"artifact_id": "artifact-case-a"}
        assert state_b["skill_result"] == {"artifact_id": "artifact-case-b"}
        assert set(calls) == {("case-a", "evidence A"), ("case-b", "evidence B")}
    finally:
        scheduler.close()


def test_late_provider_response_after_timeout_cannot_overwrite_terminal_run_state(tmp_path) -> None:
    late_response_seen = Event()

    def execute(_payload, *, operator_id, cancel_event=None):
        del operator_id, cancel_event
        sleep(0.08)
        late_response_seen.set()
        return {"status": "succeeded", "skill_result": {"artifact_id": "late-artifact"}}

    scheduler = LocalRunScheduler(
        execute,
        db_path=tmp_path / "queue.db",
        max_workers=1,
        execution_timeout_ms=15,
    )
    try:
        scheduler.submit("run-timeout", _payload(), operator_id="operator-1")
        timed_out = _wait_for(scheduler, "run-timeout", {"failed"})
        assert "SchedulerExecutionTimeout" in str(timed_out["error"])
        assert timed_out["skill_result"] is None
        assert late_response_seen.wait(1.0) is True
        still_terminal = scheduler.status("run-timeout")
        assert still_terminal["status"] == "failed"
        assert still_terminal["skill_result"] is None
    finally:
        scheduler.close()


def test_running_parent_can_be_cancelled_without_becoming_succeeded(tmp_path) -> None:
    started = Event()

    def execute(_payload, *, operator_id, cancel_event=None):
        del operator_id
        started.set()
        while cancel_event is not None and not cancel_event.is_set():
            sleep(0.005)
        raise SchedulerCancellationError("parent cancellation observed")

    scheduler = LocalRunScheduler(execute, db_path=tmp_path / "queue.db", max_workers=1)
    try:
        scheduler.submit("run-cancel", _payload(), operator_id="operator-1")
        assert started.wait(1.0) is True
        scheduler.cancel("run-cancel")
        cancelled = _wait_for(scheduler, "run-cancel", {"cancelled"})
        assert cancelled["status"] == "cancelled"
        assert cancelled["skill_result"] is None
    finally:
        scheduler.close()


def test_duplicate_artifact_registration_returns_one_manifest_for_same_run_and_content(tmp_path) -> None:
    root = tmp_path / "artifacts"
    source = root / "brief.txt"
    source.parent.mkdir(parents=True)
    source.write_text("case-a evidence", encoding="utf-8")
    store = ArtifactStore(root)

    first = store.register(
        source,
        run_id="run-artifact-duplicate",
        kind="text",
        classification_level="RESTRICTED",
        user_id="user-1",
        case_id="case-a",
        task_id="task-a",
    )
    second = store.register(
        source,
        run_id="run-artifact-duplicate",
        kind="text",
        classification_level="RESTRICTED",
        user_id="user-1",
        case_id="case-a",
        task_id="task-a",
    )

    assert second.artifact_id == first.artifact_id
    assert second.sha256 == first.sha256
