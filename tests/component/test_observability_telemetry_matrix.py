from __future__ import annotations

import hashlib
import json

from integrations.deepseek_harness.application import SudarshanApplication
from pipelines.orchestrator.contracts import NodeSpec, TelemetryUsage
from pipelines.orchestrator.dag import DependencyDAG
from pipelines.orchestrator.observability import SQLiteObservabilityStore
from pipelines.orchestrator.progress import InMemoryProgressSink, ProgressEvent


def _artifact_id(seed: str) -> str:
    return "artifact-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _node(node_id: str, *dependencies: str) -> NodeSpec:
    return NodeSpec(
        node_id=node_id,
        skill_id=f"skill.{node_id}",
        output_schema="ArtifactManifest",
        dependencies=list(dependencies),
    )


def test_successful_run_projections_agree_and_keep_memory_raw_text_out(tmp_path) -> None:
    run_id = "run-observability-success"
    artifact_id = _artifact_id("success")
    secret_memory = "CASE-A raw intelligence that must never enter telemetry"
    store = SQLiteObservabilityStore(str(tmp_path / "observability.db"))

    store.record_runtime_event(
        "memory.recall.completed",
        {
            "run_id": run_id,
            "owner_id": "operator-1",
            "case_id": "case-a",
            "operation": "recall",
            "backend": "CogneeHttpAdapter",
            "stage_id": "grounding",
            "query_hash": "query-hash-a",
            "backend_result_count": 3,
            "accepted_result_count": 2,
            "trace_id": "trace-a",
            "duration_ms": 17,
            "raw_context": secret_memory,
            "records": [secret_memory],
        },
    )
    store.record_runtime_event(
        "skill.completed",
        {
            "parent_run_id": run_id,
            "owner_id": "operator-1",
            "case_id": "case-a",
            "task_id": "task-a",
            "skill_id": "executive.summary",
            "artifact_ids": [artifact_id],
            "provider_request_id": "provider-request-a",
            "usage_id": "usage-a",
            "usage": {
                "provider": "deterministic-test-provider",
                "model": "test-model",
                "input_tokens": 12,
                "output_tokens": 8,
                "latency_ms": 41,
                "estimated_cost": 0.03,
            },
            "model_output": secret_memory,
        },
    )
    store.record_progress(
        ProgressEvent(
            run_id=run_id,
            task_id="task-a",
            stage="completed",
            status="succeeded",
            progress=100,
            artifact_id=artifact_id,
            quality_status="passed",
        )
    )

    dashboard = store.safe_dashboard(run_id, access_level="RESTRICTED", operator_id="operator-1")
    encoded = json.dumps(dashboard, ensure_ascii=False)
    summary = dashboard["summary"]

    assert summary["last_status"] == "succeeded"
    assert summary["last_stage"] == "completed"
    assert summary["input_tokens"] == 12
    assert summary["output_tokens"] == 8
    assert summary["latency_ms"] == 41
    assert summary["estimated_cost"] == 0.03
    assert summary["artifact_count"] == 1
    assert {event["event_type"] for event in dashboard["events"]} >= {
        "memory.recall.completed",
        "skill.completed",
        "progress.completed",
    }
    assert secret_memory not in encoded
    assert "raw_context" not in encoded
    assert "model_output" not in encoded


def test_failure_run_exposes_memory_provider_and_safe_failure_details(tmp_path) -> None:
    run_id = "run-observability-failure"
    store = SQLiteObservabilityStore(str(tmp_path / "observability.db"))
    store.record_runtime_event(
        "memory.recall.failed",
        {
            "run_id": run_id,
            "owner_id": "operator-1",
            "operation": "recall",
            "backend": "CogneeHttpAdapter",
            "error_code": "MEMORY_UNAVAILABLE",
            "raw_error": "secret backend response",
        },
    )
    store.record_runtime_event(
        "provider.failed",
        {
            "run_id": run_id,
            "owner_id": "operator-1",
            "provider_request_id": "provider-request-failure",
            "error_code": "PROVIDER_TIMEOUT",
            "usage": {"provider": "test-provider", "latency_ms": 2500},
        },
    )
    store.record_progress(
        ProgressEvent(
            run_id=run_id,
            task_id="task-failure",
            stage="failed",
            status="failed",
            progress=42,
            error_code="PROVIDER_TIMEOUT",
            quality_status="failed",
        )
    )

    dashboard = store.safe_dashboard(run_id, access_level="RESTRICTED", operator_id="operator-1")
    encoded = json.dumps(dashboard, ensure_ascii=False)

    assert dashboard["summary"]["last_status"] == "failed"
    assert dashboard["summary"]["last_stage"] == "failed"
    assert dashboard["summary"]["latency_ms"] == 2500
    assert any(event["error_code"] == "MEMORY_UNAVAILABLE" for event in dashboard["events"])
    assert any(event["error_code"] == "PROVIDER_TIMEOUT" for event in dashboard["events"])
    assert "secret backend response" not in encoded
    assert "raw_error" not in encoded


def test_status_events_and_telemetry_share_the_same_terminal_projection(tmp_path) -> None:
    run_id = "run-status-consistency"
    progress = InMemoryProgressSink()
    progress.publish(
        ProgressEvent(
            run_id=run_id,
            task_id="task-status",
            stage="running",
            status="running",
            progress=40,
        )
    )
    progress.publish(
        ProgressEvent(
            run_id=run_id,
            task_id="task-status",
            stage="completed",
            status="succeeded",
            progress=100,
            quality_status="passed",
        )
    )

    application = object.__new__(SudarshanApplication)
    application.progress_sink = progress
    application._run_contexts = {}
    application.telemetry = lambda _run_id: {
        "event_count": 2,
        "last_stage": "completed",
        "last_status": "succeeded",
        "input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "tool_calls": 0,
        "latency_ms": 0,
        "estimated_cost": 0.0,
        "usage_is_estimate": False,
        "child_count": 0,
        "artifact_count": 0,
        "cache_hits": 0,
        "cache_misses": 0,
        "cache_waits": 0,
        "wait_count": 0,
        "quality_report_count": 0,
    }

    events = application.events(run_id)
    summary = application._run_summary(
        {
            "run_id": run_id,
            "task_id": "task-status",
            "case_id": "case-status",
            "pipeline": "executive_summary",
            "requested_pipelines": ["executive_summary"],
            "status": "succeeded",
            "stage": "completed",
            "request": {"case_id": "case-status", "task_id": "task-status", "metadata": {}},
            "responses": {},
        },
        events,
    )

    assert events[-1]["status"] == "succeeded"
    assert summary.status == "succeeded"
    assert summary.stage == "completed"
    assert summary.progress == 100
    assert summary.telemetry.last_status == "succeeded"


def test_dag_projection_matches_completed_status_and_artifact_references(tmp_path) -> None:
    run_id = "run-dag-observability"
    source_artifact = _artifact_id("source")
    final_artifact = _artifact_id("final")
    dag = DependencyDAG(tmp_path / "dag.db")
    try:
        dag.create_run(run_id, [_node("source"), _node("final", "source")])
        dag.claim_ready_nodes(run_id, limit=1)
        dag.complete_node(run_id, "source", status="succeeded", output_ref=source_artifact)
        dag.claim_ready_nodes(run_id, limit=1)
        dag.complete_node(run_id, "final", status="succeeded", output_ref=final_artifact)

        projection = dag.get_public_dag(run_id, after_revision=-1)
        assert projection is not None
        assert projection.status == "succeeded"
        assert {node.status for node in projection.nodes} == {"succeeded"}
        assert {node.output_ref for node in projection.nodes} == {source_artifact, final_artifact}
        assert [(edge.source, edge.target) for edge in projection.edges] == [("source", "final")]
    finally:
        dag.close()


def test_trajectory_contains_recorded_memory_and_provider_steps_in_separate_lanes(tmp_path) -> None:
    run_id = "run-trajectory-observability"
    store = SQLiteObservabilityStore(str(tmp_path / "observability.db"))
    store.record_runtime_event(
        "memory.recall.completed",
        {
            "run_id": run_id,
            "owner_id": "operator-1",
            "operation": "recall",
            "backend": "local-test-memory",
            "query_hash": "hash-trajectory",
            "accepted_result_count": 1,
            "trace_id": "trace-trajectory",
            "duration_ms": 5,
            "lane_id": "main",
        },
    )
    store.record_runtime_event(
        "skill.completed",
        {
            "run_id": run_id,
            "owner_id": "operator-1",
            "skill_id": "presentation.case-brief",
            "lane_id": "child-presentation",
            "provider_request_id": "provider-trajectory",
        },
    )

    application = object.__new__(SudarshanApplication)
    application.observability = store
    application._run_contexts = {}
    trajectory = application.trajectory(run_id, operator_id="operator-1")

    assert trajectory["event_count"] == 2
    assert {lane["lane_id"] for lane in trajectory["lanes"]} == {"main", "child-presentation"}
    assert {event["event_type"] for event in trajectory["events"]} == {
        "memory.recall.completed",
        "skill.completed",
    }
    assert all("query_hash" in event or "provider_request_id" in event for event in trajectory["events"])


def test_artifact_manifest_matches_bytes_and_ownership_projection(tmp_path) -> None:
    artifact_root = tmp_path / "artifacts"
    artifact_path = artifact_root / "summary.txt"
    artifact_path.parent.mkdir(parents=True)
    content = "Verified case-a finding\n"
    artifact_path.write_text(content, encoding="utf-8")
    expected_digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()

    from api.artifacts import ArtifactStore

    store = ArtifactStore(artifact_root)
    manifest = store.register(
        artifact_path,
        run_id="run-manifest-observability",
        kind="text",
        classification_level="RESTRICTED",
        user_id="user-1",
        case_id="case-a",
        task_id="task-a",
        quality_status="passed",
    )
    loaded, source = store.get(manifest.artifact_id)

    assert loaded.artifact_id == manifest.artifact_id
    assert loaded.run_id == "run-manifest-observability"
    assert loaded.user_id == "user-1"
    assert loaded.case_id == "case-a"
    assert loaded.task_id == "task-a"
    assert loaded.sha256 == expected_digest
    assert source.read_text(encoding="utf-8") == content
    assert loaded.size_bytes == len(artifact_path.read_bytes())


def test_sqlite_telemetry_deduplicates_repeated_usage_receipts(tmp_path) -> None:
    store = SQLiteObservabilityStore(str(tmp_path / "observability.db"))
    usage = TelemetryUsage(
        provider="test-provider",
        model="test-model",
        input_tokens=10,
        output_tokens=20,
        latency_ms=30,
    )
    first = ProgressEvent(
        run_id="run-usage-dedup",
        task_id="task-usage",
        stage="provider.completed",
        status="running",
        usage=usage,
        usage_id="receipt-1",
    )
    second = first.model_copy(update={"event_id": "event-duplicate"})
    store.record_progress(first)
    store.record_progress(second)

    summary = store.summary("run-usage-dedup")

    assert summary.input_tokens == 10
    assert summary.output_tokens == 20
    assert summary.latency_ms == 30
