from __future__ import annotations

import pytest

from pipelines.orchestrator.contracts import NodeSpec
from pipelines.orchestrator.dag import DAGError, DependencyDAG


def node(node_id: str, *dependencies: str, repairs: int = 0) -> NodeSpec:
    return NodeSpec(
        node_id=node_id,
        skill_id=f"skill.{node_id}",
        output_schema="ArtifactManifest",
        dependencies=list(dependencies),
        retry_policy={"max_repairs": repairs},
    )


def test_dag_admits_independent_nodes_and_waits_for_all_dependencies() -> None:
    events = []
    dag = DependencyDAG(":memory:", event_sink=lambda name, payload: events.append((name, payload)))
    dag.create_run("run-1", [node("source"), node("visual"), node("assemble", "source", "visual")])

    ready = dag.admit_ready_nodes("run-1")
    assert [item.node_id for item in ready] == ["source", "visual"]
    claimed = dag.claim_ready_nodes("run-1", limit=2)
    assert {item.node_id for item in claimed} == {"source", "visual"}
    assert dag.get_run("run-1").status == "running"

    dag.complete_node("run-1", "source", status="succeeded", output_ref="artifact-source")
    assert dag.admit_ready_nodes("run-1") == []
    dag.complete_node("run-1", "visual", status="succeeded", output_ref="artifact-visual")
    assert [item.node_id for item in dag.admit_ready_nodes("run-1")] == ["assemble"]
    assert [name for name, _ in events].count("node.started") == 2


def test_failed_dependency_blocks_descendants_with_typed_reason() -> None:
    dag = DependencyDAG(":memory:")
    dag.create_run("run-2", [node("a"), node("b", "a"), node("c", "b")])
    dag.claim_ready_nodes("run-2", limit=1)
    dag.complete_node("run-2", "a", status="failed", failure_code="RENDER_FAILED", failure_reason="bad SVG")

    assert dag.get_node("run-2", "b").status == "blocked"
    assert dag.get_node("run-2", "c").status == "blocked"
    assert dag.get_node("run-2", "c").failure_code == "DEPENDENCY_FAILED"
    assert dag.get_run("run-2").status == "failed"


def test_repair_loop_is_bounded_and_persisted(tmp_path) -> None:
    db_path = tmp_path / "dag.sqlite"
    dag = DependencyDAG(db_path)
    dag.create_run("run-3", [node("render", repairs=1)])
    dag.claim_ready_nodes("run-3", limit=1)
    repaired = dag.complete_node("run-3", "render", status="failed", repair=True, failure_reason="overflow")
    assert repaired.status == "ready"
    assert repaired.repair_attempts == 1

    dag.claim_ready_nodes("run-3", limit=1)
    final = dag.complete_node("run-3", "render", status="failed", repair=True, failure_code="OVERFLOW")
    assert final.status == "failed"
    assert final.repair_attempts == 1
    dag.close()

    reopened = DependencyDAG(db_path)
    assert reopened.get_node("run-3", "render").failure_code == "OVERFLOW"
    assert reopened.get_run("run-3").status == "failed"
    reopened.close()


def test_graph_rejects_unknown_dependencies_and_cycles() -> None:
    dag = DependencyDAG(":memory:")
    with pytest.raises(DAGError, match="unknown nodes"):
        dag.create_run("unknown", [node("a", "missing")])
    with pytest.raises(DAGError, match="cycle"):
        dag.create_run("cycle", [node("a", "b"), node("b", "a")])
