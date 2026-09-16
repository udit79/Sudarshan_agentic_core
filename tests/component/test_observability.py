from pipelines.orchestrator.contracts import TelemetryUsage, project_progress_event
import pipelines.orchestrator.observability as observability_module
from pipelines.orchestrator.observability import (
    CompositeObservabilityStore,
    JsonHttpObservabilityExporter,
    SQLiteObservabilityStore,
    runtime_event,
)
from datetime import datetime, timedelta, timezone
import sqlite3
import pytest
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


def test_runtime_event_projects_safe_memory_operation_details() -> None:
    event = runtime_event(
        "memory.recall.completed",
        {
            "run_id": "run-memory",
            "owner_id": "operator-1",
            "case_id": "case-1",
            "operation": "recall",
            "backend": "CogneeHttpAdapter",
            "stage_id": "grounding",
            "query_hash": "abc123",
            "backend_result_count": 4,
            "accepted_result_count": 2,
            "trace_id": "trace-1",
            "duration_ms": 38,
            "raw_context": "must never be stored",
        },
    )

    assert event is not None
    assert event.operation == "recall"
    assert event.backend == "CogneeHttpAdapter"
    assert event.backend_result_count == 4
    assert event.accepted_result_count == 2
    assert event.trace_id == "trace-1"
    assert event.duration_ms == 38
    assert not hasattr(event, "raw_context")


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


def test_observability_hash_chain_retention_and_role_boundary(tmp_path) -> None:
    db_path = tmp_path / "observability.db"
    store = SQLiteObservabilityStore(str(db_path))
    secret = runtime_event(
        "skill.completed",
        {
            "parent_run_id": "run-secure",
            "classification_level": "SECRET",
            "owner_id": "operator-1",
            "case_id": "case-1",
            "usage": {"input_tokens": 2},
        },
    )
    assert secret is not None
    store.record(secret)
    with pytest.raises(PermissionError):
        store.events("run-secure", access_level="RESTRICTED")
    dashboard = store.safe_dashboard(
        "run-secure", access_level="SECRET", operator_id="operator-1"
    )
    assert dashboard["summary"]["input_tokens"] == 2
    assert store.verify_integrity("run-secure") is True

    old = secret.model_copy(update={
        "event_id": "old-event",
        "run_id": "run-retention",
        "timestamp": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
    })
    store.record(old)
    assert store.purge_expired(retention_seconds=60 * 60, dry_run=True)
    assert store.purge_expired(retention_seconds=60 * 60, dry_run=False)
    assert store.verify_integrity("run-retention") is True

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE observability_events SET event_json = ? WHERE run_id = ?",
            ('{"tampered":true}', "run-secure"),
        )
    assert store.verify_integrity("run-secure") is False


def test_composite_observability_exports_only_safe_events(monkeypatch, tmp_path) -> None:
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size):
            return b"ok"

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return Response()

    monkeypatch.setattr(observability_module, "urlopen", fake_urlopen)
    exporter = JsonHttpObservabilityExporter("https://collector.invalid/events", bearer_token="secret")
    store = CompositeObservabilityStore(SQLiteObservabilityStore(str(tmp_path / "obs.db")), exporter=exporter)
    event = runtime_event(
        "skill.completed",
        {"parent_run_id": "run-export", "input_payload": "must not be exported"},
    )
    assert event is not None
    store.record(event)
    assert len(requests) == 1
    request, timeout = requests[0]
    assert timeout == 2.0
    assert request.get_header("Authorization") == "Bearer secret"
    assert b"input_payload" not in request.data
    assert exporter.failed_exports == 0
