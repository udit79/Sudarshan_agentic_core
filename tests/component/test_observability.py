from pipelines.orchestrator.contracts import TelemetryUsage, project_progress_event
from pipelines.orchestrator.observability import SQLiteObservabilityStore, runtime_event
from pipelines.orchestrator.progress import ProgressEvent


def test_runtime_event_allowlist_drops_payload_and_projects_usage() -> None:
    event = runtime_event(
        "skill.completed",
        {
            "parent_run_id": "run-obs",
            "parent_node_id": "node-1",
            "task_id": "task-1",
            "skill_id": "visual.flowchart",
            "skill_call_id": "call-1",
            "child_run_id": "child-1",
            "artifact_ids": ["artifact-1"],
            "quality_report_id": "quality-1",
            "usage": {
                "provider": "test",
                "model": "test-model",
                "input_tokens": 100,
                "output_tokens": 50,
                "latency_ms": 25,
            },
            "input_payload": {"query": "must never be stored"},
        },
    )

    assert event is not None
    assert event.usage is not None
    assert event.usage.total_tokens == 150
    assert not hasattr(event, "input_payload")
    assert event.artifact_ids == ["artifact-1"]


def test_observability_store_aggregates_runtime_and_progress_metrics(tmp_path) -> None:
    store = SQLiteObservabilityStore(str(tmp_path / "observability.db"))
    store.record_runtime_event(
        "skill.completed",
        {
            "parent_run_id": "run-aggregate",
            "parent_node_id": "node-1",
            "skill_id": "visual.flowchart",
            "skill_call_id": "call-1",
            "child_run_id": "child-1",
            "artifact_ids": ["artifact-1"],
            "quality_report_id": "quality-1",
            "usage": {"input_tokens": 100, "output_tokens": 50, "latency_ms": 25},
        },
    )
    store.record_progress(ProgressEvent(
        run_id="run-aggregate",
        task_id="task-1",
        stage="waiting",
        status="waiting_for_input",
        progress=40,
        requires_action=True,
        wait_reason="Operator input is required",
        usage=TelemetryUsage(input_tokens=10, output_tokens=5, latency_ms=4),
    ))

    summary = store.summary("run-aggregate")
    assert summary.event_count == 2
    assert summary.child_count == 1
    assert summary.artifact_count == 1
    assert summary.wait_count == 1
    assert summary.input_tokens == 110
    assert summary.output_tokens == 55
    assert summary.latency_ms == 29


def test_projected_run_event_preserves_safe_telemetry_fields() -> None:
    event = project_progress_event(
        ProgressEvent(
            run_id="run-projection",
            task_id="task-1",
            stage="skill.completed",
            status="succeeded",
            progress=100,
            skill_call_id="call-1",
            usage=TelemetryUsage(input_tokens=4, output_tokens=6),
            cache_status="hit",
        ).model_dump(mode="json"),
        sequence=1,
    )
    assert event.skill_call_id == "call-1"
    assert event.usage is not None
    assert event.usage.output_tokens == 6
    assert event.cache_status == "hit"
