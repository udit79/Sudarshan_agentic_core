from __future__ import annotations

import threading
import time

import pytest

from api.control_plane import AdmissionResult, ControlPlaneConflict, LeaseToken, StaleLeaseError
from pipelines.orchestrator.contracts import NodeSpec
from pipelines.orchestrator.dag import DAGError, DependencyDAG


class FakeDAGControlPlane:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.records: dict[str, dict[str, object]] = {}
        self.fences: dict[str, int] = {}
        self.snapshots: dict[str, dict[str, object]] = {}

    def admit(self, resource_key, request_hash, payload, *, queue="runs"):
        del queue
        with self._lock:
            existing = self.records.get(resource_key)
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise ControlPlaneConflict("different DAG node spec")
                return AdmissionResult(resource_key, request_hash, str(existing["status"]), True)
            self.records[resource_key] = {
                "request_hash": request_hash,
                "payload": dict(payload),
                "status": "queued",
                "owner": "",
                "fence": 0,
                "expires_at": 0.0,
            }
            return AdmissionResult(resource_key, request_hash, "queued", False)

    def claim(self, resource_key, *, owner, lease_seconds):
        with self._lock:
            record = self.records[resource_key]
            if str(record["status"]) in {"succeeded", "failed", "cancelled"}:
                return None
            if float(record["expires_at"]) > time.time():
                return None
            fence = self.fences.get(resource_key, 0) + 1
            self.fences[resource_key] = fence
            expires_at = time.time() + lease_seconds
            record.update(owner=owner, fence=fence, expires_at=expires_at, status="running")
            return LeaseToken(resource_key, owner, fence, expires_at)

    def transition(self, lease, *, status, result=None):
        with self._lock:
            record = self.records[lease.resource_key]
            if record["owner"] != lease.owner or record["fence"] != lease.fencing_token:
                raise StaleLeaseError("stale DAG lease")
            record.update(status=status, owner="", expires_at=0.0, result=dict(result or {}))

    def schedule_retry(self, lease, *, retry_at, error):
        with self._lock:
            record = self.records[lease.resource_key]
            if record["owner"] != lease.owner or record["fence"] != lease.fencing_token:
                raise StaleLeaseError("stale DAG lease")
            record.update(status="retrying", owner="", expires_at=retry_at, error=error)

    def dag_snapshot(self, run_id):
        with self._lock:
            snapshot = self.snapshots.get(run_id)
            return None if snapshot is None else {
                **snapshot,
                "nodes": {key: dict(value) for key, value in snapshot["nodes"].items()},
            }

    def dag_snapshot_put(self, run_id, snapshot):
        with self._lock:
            if run_id in self.snapshots:
                raise ControlPlaneConflict("DAG snapshot already exists")
            stored = dict(snapshot)
            stored["run_id"] = run_id
            stored["revision"] = 1
            stored["nodes"] = {key: dict(value) for key, value in snapshot["nodes"].items()}
            self.snapshots[run_id] = stored
            return 1

    def dag_snapshot_patch(self, run_id, nodes):
        with self._lock:
            snapshot = self.snapshots[run_id]
            merged = {key: dict(value) for key, value in snapshot["nodes"].items()}
            merged.update({key: dict(value) for key, value in nodes.items()})
            snapshot["nodes"] = merged
            snapshot["revision"] = int(snapshot["revision"]) + 1
            return int(snapshot["revision"])


def spec(node_id: str, *dependencies: str) -> NodeSpec:
    return NodeSpec(
        node_id=node_id,
        skill_id=f"skill.{node_id}",
        output_schema="ArtifactManifest",
        dependencies=list(dependencies),
    )


def test_shared_dag_claim_allows_one_worker_and_fences_stale_completion(tmp_path):
    control = FakeDAGControlPlane()
    first = DependencyDAG(tmp_path / "first.db", control_plane=control, lease_ms=100)
    second = DependencyDAG(tmp_path / "second.db", control_plane=control, lease_ms=100)
    try:
        nodes = [spec("source"), spec("assemble", "source")]
        first.create_run("run-shared-dag", nodes)
        second.create_run("run-shared-dag", nodes)

        first_claim = first.claim_ready_nodes("run-shared-dag", limit=1)
        second_claim = second.claim_ready_nodes("run-shared-dag", limit=1)
        assert [item.node_id for item in first_claim] == ["source"]
        assert second_claim == []

        time.sleep(0.12)
        replacement = control.claim(
            "dag:run-shared-dag:source",
            owner="replacement-worker",
            lease_seconds=1,
        )
        assert replacement is not None
        with pytest.raises(DAGError, match="stale shared lease"):
            first.complete_node("run-shared-dag", "source", status="succeeded", output_ref="source-ref")
    finally:
        first.close()
        second.close()


def test_shared_dag_unlocks_dependents_after_fenced_success(tmp_path):
    control = FakeDAGControlPlane()
    dag = DependencyDAG(tmp_path / "dag.db", control_plane=control)
    try:
        dag.create_run("run-unlock", [spec("source"), spec("assemble", "source")])
        assert [item.node_id for item in dag.claim_ready_nodes("run-unlock", limit=1)] == ["source"]
        dag.complete_node("run-unlock", "source", status="succeeded", output_ref="source-ref")
        assert [item.node_id for item in dag.claim_ready_nodes("run-unlock", limit=1)] == ["assemble"]
    finally:
        dag.close()


def test_shared_dag_snapshot_unlocks_dependent_on_another_worker(tmp_path):
    control = FakeDAGControlPlane()
    first = DependencyDAG(tmp_path / "first.db", control_plane=control)
    second = DependencyDAG(tmp_path / "second.db", control_plane=control)
    try:
        nodes = [spec("source"), spec("assemble", "source")]
        first.create_run("run-snapshot", nodes)
        second.create_run("run-snapshot", nodes)

        assert [item.node_id for item in first.claim_ready_nodes("run-snapshot", limit=1)] == ["source"]
        first.complete_node("run-snapshot", "source", status="succeeded", output_ref="source-ref")

        unlocked = second.claim_ready_nodes("run-snapshot", limit=1)
        assert [item.node_id for item in unlocked] == ["assemble"]
        assert second.get_node("run-snapshot", "source").output_ref == "source-ref"
    finally:
        first.close()
        second.close()
