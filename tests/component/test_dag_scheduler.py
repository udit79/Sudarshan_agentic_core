from __future__ import annotations

import threading
import time

from api.dag_scheduler import DAGSchedulerBridge
from pipelines.orchestrator.contracts import NodeSpec
from pipelines.orchestrator.dag import DependencyDAG


def spec(node_id: str, *dependencies: str) -> NodeSpec:
    return NodeSpec(
        node_id=node_id,
        skill_id=f"skill.{node_id}",
        output_schema="ArtifactManifest",
        dependencies=list(dependencies),
    )


def wait_for(bridge: DAGSchedulerBridge, run_id: str, statuses: set[str], timeout: float = 3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = bridge.status(run_id)
        if state["status"] in statuses:
            return state
        time.sleep(0.01)
    raise AssertionError(f"DAG run did not reach {statuses}: {bridge.status(run_id)}")


def test_bridge_runs_independent_nodes_concurrently_then_admits_dependents(tmp_path) -> None:
    started: list[str] = []
    lock = threading.Lock()

    def execute(node, payload, cancel_event):
        with lock:
            started.append(node.node_id)
        return {"status": "succeeded", "output_ref": f"artifact-{node.node_id}"}

    bridge = DAGSchedulerBridge(
        DependencyDAG(tmp_path / "dag.db"),
        execute,
        queue_db_path=str(tmp_path / "queue.db"),
        max_workers=2,
    )
    try:
        state = bridge.start_run(
            "run-bridge",
            [spec("source"), spec("visual"), spec("assemble", "source", "visual")],
            {
                "query": "assemble case brief",
                "user_id": "operator-1",
                "case_id": "case-1",
                "task_id": "task-bridge",
                "classification_level": "RESTRICTED",
                "distribution": "Authorized NTRO personnel",
            },
            operator_id="operator-1",
        )
        assert state["status"] in {"queued", "running"}
        completed = wait_for(bridge, "run-bridge", {"succeeded"})
        assert started[:2] == ["source", "visual"]
        assert started[-1] == "assemble"
        assert completed["completed_count"] == 3
        assert all(node["status"] == "succeeded" for node in completed["nodes"])
    finally:
        bridge.close()
