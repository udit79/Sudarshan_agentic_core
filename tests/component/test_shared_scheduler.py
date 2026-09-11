from __future__ import annotations

import threading
import time
from collections import deque

from api.control_plane import (
    AdmissionResult,
    ControlPlaneConflict,
    LeaseToken,
    QueueMessage,
    StaleLeaseError,
)
from api.scheduler import LocalRunScheduler


class FakeSharedControlPlane:
    """Deterministic shared-store double for scheduler integration tests."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: dict[str, dict[str, object]] = {}
        self._fences: dict[str, int] = {}
        self.transitions: list[tuple[str, str]] = []
        self._queue = deque()
        self._reclaims = deque()
        self.acks: list[str] = []

    def admit(self, resource_key, request_hash, payload, *, queue="runs"):
        with self._lock:
            existing = self._records.get(resource_key)
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise ControlPlaneConflict("different request")
                return AdmissionResult(resource_key, request_hash, str(existing["status"]), True)
            self._records[resource_key] = {
                "request_hash": request_hash,
                "payload": dict(payload),
                "status": "queued",
                "attempt": 0,
                "owner": "",
                "fence": 0,
                "expires_at": 0.0,
            }
            self._queue.append(QueueMessage(queue, f"{resource_key}-0", resource_key))
            return AdmissionResult(resource_key, request_hash, "queued", False)

    def poll(self, queue, *, owner, block_ms=250):
        del owner
        with self._lock:
            for message in list(self._queue):
                if message.queue == queue:
                    self._queue.remove(message)
                    return message
        time.sleep(min(max(block_ms, 1) / 1000, 0.01))
        return None

    def ack(self, message):
        with self._lock:
            self.acks.append(message.resource_key)

    def reclaim(self, queue, *, owner, min_idle_ms):
        del queue, owner, min_idle_ms
        with self._lock:
            return self._reclaims.popleft() if self._reclaims else None

    def claim(self, resource_key, *, owner, lease_seconds):
        with self._lock:
            record = self._records[resource_key]
            if str(record["status"]) in {"succeeded", "partial", "failed", "cancelled", "completed"}:
                return None
            if float(record["expires_at"]) > time.time():
                return None
            fence = self._fences.get(resource_key, 0) + 1
            self._fences[resource_key] = fence
            expires_at = time.time() + lease_seconds
            record.update(owner=owner, fence=fence, expires_at=expires_at, status="running")
            record["attempt"] = int(record["attempt"]) + 1
            return LeaseToken(resource_key, owner, fence, expires_at)

    def renew(self, lease, *, lease_seconds):
        with self._lock:
            record = self._records[lease.resource_key]
            if record["owner"] != lease.owner or record["fence"] != lease.fencing_token:
                raise StaleLeaseError("stale")
            expires_at = time.time() + lease_seconds
            record["expires_at"] = expires_at
            return LeaseToken(lease.resource_key, lease.owner, lease.fencing_token, expires_at)

    def transition(self, lease, *, status, result=None):
        with self._lock:
            record = self._records[lease.resource_key]
            if record["owner"] != lease.owner or record["fence"] != lease.fencing_token:
                raise StaleLeaseError("stale")
            record.update(status=status, owner="", expires_at=0.0, result=dict(result or {}))
            self.transitions.append((lease.resource_key, status))

    def schedule_retry(self, lease, *, retry_at, error):
        with self._lock:
            record = self._records[lease.resource_key]
            if record["owner"] != lease.owner or record["fence"] != lease.fencing_token:
                raise StaleLeaseError("stale")
            record.update(status="retrying", owner="", expires_at=0.0, retry_at=retry_at, error=error)

    def state(self, resource_key):
        with self._lock:
            record = self._records.get(resource_key)
            return dict(record) if record is not None else None


def _payload() -> dict[str, object]:
    return {
        "task_id": "task-1",
        "case_id": "case-1",
        "user_id": "operator-1",
        "query": "shared control plane",
    }


def _wait_for(scheduler: LocalRunScheduler, run_id: str, expected: set[str]):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        state = scheduler.status(run_id)
        if state and state["status"] in expected:
            return state
        time.sleep(0.01)
    raise AssertionError(f"run did not reach {expected}: {scheduler.status(run_id)}")


def test_scheduler_uses_shared_admission_and_terminal_fencing(tmp_path):
    control = FakeSharedControlPlane()
    calls: list[str] = []

    def execute(payload, *, operator_id):
        calls.append(str(payload["query"]))
        return {"status": "succeeded", "skill_result": {"artifact_id": "artifact-1"}}

    first = LocalRunScheduler(
        execute,
        db_path=tmp_path / "first.db",
        max_workers=1,
        control_plane=control,
    )
    second = LocalRunScheduler(
        execute,
        db_path=tmp_path / "second.db",
        max_workers=1,
        control_plane=control,
    )
    try:
        accepted = first.submit("run-shared", _payload(), operator_id="operator-1")
        replay = second.submit("run-shared", _payload(), operator_id="operator-1")
        completed = _wait_for(first, "run-shared", {"succeeded"})

        assert accepted["run_id"] == "run-shared"
        assert replay["idempotent_replay"] is True
        assert completed["status"] == "succeeded"
        assert calls == ["shared control plane"]
        assert control.transitions == [("run-shared", "succeeded")]
    finally:
        first.close()
        second.close()


def test_scheduler_discovers_job_admitted_by_another_process(tmp_path):
    control = FakeSharedControlPlane()
    payload = _payload()
    control.admit("run-remote", "hash-remote", payload)
    calls: list[str] = []

    def execute(value, *, operator_id):
        calls.append(str(value["query"]))
        return {"status": "succeeded"}

    scheduler = LocalRunScheduler(
        execute,
        db_path=tmp_path / "remote.db",
        max_workers=1,
        control_plane=control,
    )
    try:
        completed = _wait_for(scheduler, "run-remote", {"succeeded"})
        assert completed["status"] == "succeeded"
        assert calls == ["shared control plane"]
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and control.acks != ["run-remote"]:
            time.sleep(0.01)
        assert control.acks == ["run-remote"]
    finally:
        scheduler.close()


def test_scheduler_reclaims_pending_job_after_consumer_loss(tmp_path):
    control = FakeSharedControlPlane()
    payload = _payload()
    control.admit("run-reclaimed", "hash-reclaimed", payload)
    with control._lock:
        control._reclaims.append(control._queue.popleft())
    calls: list[str] = []

    def execute(value, *, operator_id):
        calls.append(str(value["query"]))
        return {"status": "succeeded"}

    scheduler = LocalRunScheduler(
        execute,
        db_path=tmp_path / "reclaimed.db",
        max_workers=1,
        control_plane=control,
        queue_reclaim_idle_ms=1,
    )
    try:
        completed = _wait_for(scheduler, "run-reclaimed", {"succeeded"})
        assert completed["status"] == "succeeded"
        assert calls == ["shared control plane"]
        assert control.acks == ["run-reclaimed"]
    finally:
        scheduler.close()
