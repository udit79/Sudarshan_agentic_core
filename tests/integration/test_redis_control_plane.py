from __future__ import annotations

import importlib.util
import os
import threading
import time
from uuid import uuid4

import pytest

from api.control_plane import RedisControlPlane, StaleLeaseError
from pipelines.orchestrator.budget import BudgetController, BudgetExceededError
from pipelines.orchestrator.contracts import RunPolicy, UsageRecord
from pipelines.orchestrator.contracts import NodeSpec
from pipelines.orchestrator.dag import DependencyDAG
from api.scheduler import LocalRunScheduler
from ingestion_pipelines.contracts import IngestionBudget
from ingestion_pipelines.runtime import IngestionBudgetController, IngestionBudgetExceededError, IngestionUsageRecorder


_REDIS_URL = os.getenv("REDIS_URL") or os.getenv("SUDARSHAN_REDIS_URL")
pytestmark = pytest.mark.skipif(
    not _REDIS_URL or importlib.util.find_spec("redis") is None,
    reason="requires REDIS_URL/SUDARSHAN_REDIS_URL and the optional redis extra",
)


def _payload() -> dict[str, str]:
    return {
        "task_id": "live-task",
        "case_id": "live-case",
        "query": "live shared queue contract",
    }


def _wait_for_state(control: RedisControlPlane, run_id: str, expected: str) -> dict[str, str]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        state = control.state(run_id)
        if state and state.get("status") == expected:
            return state
        time.sleep(0.02)
    raise AssertionError(f"Redis run did not reach {expected}: {control.state(run_id)}")


def _cleanup(control: RedisControlPlane) -> None:
    client = control.client
    for key in client.scan_iter(match=f"{control.prefix}:*"):
        client.delete(key)


def test_live_redis_scheduler_discovery_and_single_execution(tmp_path):
    prefix = f"sudarshan:test:t39-5:{uuid4().hex}"
    control = RedisControlPlane.from_url(_REDIS_URL, prefix=prefix)
    calls: list[str] = []
    calls_lock = threading.Lock()

    def execute(payload, *, operator_id):
        del operator_id
        with calls_lock:
            calls.append(str(payload["query"]))
        time.sleep(0.1)
        return {"status": "succeeded", "skill_result": {"live": True}}

    first = LocalRunScheduler(
        execute,
        db_path=tmp_path / "first.db",
        max_workers=1,
        control_plane=control,
        queue_name="runs",
    )
    second = LocalRunScheduler(
        execute,
        db_path=tmp_path / "second.db",
        max_workers=1,
        control_plane=control,
        queue_name="runs",
    )
    run_id = f"live-run-{uuid4().hex}"
    try:
        control.admit(run_id, "live-hash", _payload(), queue="runs")
        state = _wait_for_state(control, run_id, "succeeded")
        assert state["status"] == "succeeded"
        assert calls == ["live shared queue contract"]
    finally:
        first.close()
        second.close()
        _cleanup(control)


def test_live_redis_fencing_rejects_stale_worker(tmp_path):
    del tmp_path
    prefix = f"sudarshan:test:t39-5-fence:{uuid4().hex}"
    control = RedisControlPlane.from_url(_REDIS_URL, prefix=prefix)
    resource = f"fenced-{uuid4().hex}"
    try:
        control.admit(resource, "fence-hash", _payload())
        first = control.claim(resource, owner="worker-1", lease_seconds=0.05)
        assert first is not None
        time.sleep(0.08)
        second = control.claim(resource, owner="worker-2", lease_seconds=1)
        assert second is not None
        with pytest.raises(StaleLeaseError):
            control.transition(first, status="succeeded", result={"worker": "stale"})
        control.transition(second, status="succeeded", result={"worker": "current"})
        assert control.state(resource)["status"] == "succeeded"
    finally:
        _cleanup(control)


def test_live_redis_budget_reservation_is_atomic():
    prefix = f"sudarshan:test:t39-9-budget:{uuid4().hex}"
    control = RedisControlPlane.from_url(_REDIS_URL, prefix=prefix)
    policy = RunPolicy(max_model_tokens=256, max_tool_calls=4, max_wall_time_ms=1000, max_parallel_children=2)
    first = BudgetController(control_plane=control)
    second = BudgetController(control_plane=control)
    try:
        first.register_run("budget-run", policy)
        second.register_run("budget-run", policy)
        reservation = first.reserve("budget-run", node_id="node-1", model_tokens=256)
        with pytest.raises(BudgetExceededError, match="TOKEN_BUDGET"):
            second.reserve("budget-run", node_id="node-2", model_tokens=1)
        snapshot = first.commit(
            reservation.reservation_id,
            UsageRecord(
                usage_id="live-usage",
                run_id="budget-run",
                node_id="node-1",
                provider="test",
                model="test-model",
                input_tokens=100,
                output_tokens=50,
                is_estimate=True,
            ),
        )
        assert snapshot.used_model_tokens == 150
        assert second.snapshot("budget-run").remaining_model_tokens == 106
    finally:
        _cleanup(control)


def test_live_redis_dag_snapshot_replicates_dependent_unlock(tmp_path):
    prefix = f"sudarshan:test:t39-11-dag:{uuid4().hex}"
    control = RedisControlPlane.from_url(_REDIS_URL, prefix=prefix)
    first = DependencyDAG(tmp_path / "first-dag.db", control_plane=control)
    second = DependencyDAG(tmp_path / "second-dag.db", control_plane=control)
    nodes = [
        NodeSpec(node_id="source", skill_id="skill.source", output_schema="ArtifactManifest"),
        NodeSpec(
            node_id="assemble",
            skill_id="skill.assemble",
            output_schema="ArtifactManifest",
            dependencies=["source"],
        ),
    ]
    try:
        first.create_run("live-dag", nodes)
        second.create_run("live-dag", nodes)
        assert [node.node_id for node in first.claim_ready_nodes("live-dag", limit=1)] == ["source"]
        first.complete_node("live-dag", "source", status="succeeded", output_ref="source-ref")

        claimed = second.claim_ready_nodes("live-dag", limit=1)
        assert [node.node_id for node in claimed] == ["assemble"]
        assert second.get_node("live-dag", "source").output_ref == "source-ref"
    finally:
        first.close()
        second.close()
        _cleanup(control)


def test_live_redis_ingestion_budget_and_usage_are_shared():
    prefix = f"sudarshan:test:t41-ingestion:{uuid4().hex}"
    control = RedisControlPlane.from_url(_REDIS_URL, prefix=prefix)
    first = IngestionBudgetController(control_plane=control)
    second = IngestionBudgetController(control_plane=control)
    recorder = IngestionUsageRecorder(control_plane=control)
    budget = IngestionBudget(token_budget=100, parser_units=1, max_fan_out=2)
    try:
        first.register("live-ingestion", budget)
        second.register("live-ingestion", budget)
        first.charge("live-ingestion", "parser", units=1, tokens=50, fan_out=1)
        with pytest.raises(IngestionBudgetExceededError, match="STAGE_CALL_BUDGET"):
            second.charge("live-ingestion", "parser", units=1, tokens=1, fan_out=1)
        recorder.record_estimate("live-ingestion", stage="vision", tokens=20)
        recorder.record(
            "live-ingestion",
            stage="vision",
            provider="test",
            model="vision",
            output_tokens=12,
        )
        usage = recorder.snapshot("live-ingestion")
        assert usage["estimated_tokens"] == 20
        assert usage["actual_tokens"] == 12
    finally:
        _cleanup(control)
