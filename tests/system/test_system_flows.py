from __future__ import annotations

from pathlib import Path

from ingestion_pipelines import ingest_file, to_access_context, to_knowledge_unit
from memory import ScopeType
from pipelines import InMemoryProgressSink, PipelineAdapter, PipelineOrchestrator, PipelineResponse

from tests.conftest import FakeRecallManager, make_request, successful_response


def test_system_ingestion_memory_routing_prompt_and_pipeline(
    memory_manager,
    recording_backend,
) -> None:
    source = Path("sample_data/sample_text.txt")
    document = ingest_file(str(source), user_id="user-1", case_id="case-1", task_id="task-1")
    unit = to_knowledge_unit(document)
    context = to_access_context(document)
    memory_manager.remember(unit, context, scope_type=ScopeType.CASE)

    sink = InMemoryProgressSink()
    orchestrator = PipelineOrchestrator(
        memory_manager,
        registry={
            "executive_summary": PipelineAdapter(
                "executive_summary",
                lambda request: successful_response(request, "executive_summary"),
            )
        },
        progress_sink=sink,
    )
    result = orchestrator.run(
        make_request("executive_summary", query="Create an executive summary for the case"),
        run_id="run-system-success",
    )

    assert result.status == "succeeded"
    assert result.response is not None
    assert result.response.output["validated"] is True
    stages = [event.stage for event in sink.events("run-system-success")]
    assert stages == [
        "queued",
        "request_understanding",
        "routing",
        "memory_recall",
        "memory_recall",
        "prompt_crafting",
        "prompt_crafting",
        "memory_and_generation",
        "pipeline_result",
        "completed",
    ]
    task_scoped_writes = [
        item for item in recording_backend.writes
        if item["node_sets"] == ["sudarshan:scope:task:task-1"]
    ]
    assert {item["metadata"]["step"] for item in task_scoped_writes} >= {
        "request_understanding",
        "memory_recall",
        "prompt_crafting",
    }


def test_system_clarification_round_trip_resumes_same_run() -> None:
    orchestrator = PipelineOrchestrator(
        FakeRecallManager(),
        registry={
            "advisory": PipelineAdapter(
                "advisory",
                lambda request: successful_response(request, "advisory"),
            )
        },
    )
    pending = orchestrator.run(make_request(), run_id="run-system-clarify")

    assert pending.status == "pending"
    clarification_interrupt = pending.interrupt
    assert clarification_interrupt is not None
    assert clarification_interrupt["type"] == "clarification.required"

    completed = orchestrator.resume(
        "run-system-clarify",
        "task-1",
        {"answer": "Create an advisory focused on the case decision."},
    )

    assert completed.status == "succeeded"
    assert completed.pipeline == "advisory"


def test_system_external_approval_round_trip() -> None:
    decisions: list[dict[str, object]] = []

    def resume(request, decision):
        decisions.append(dict(decision))
        return successful_response(request, "advisory")

    orchestrator = PipelineOrchestrator(
        FakeRecallManager(),
        registry={
            "advisory": PipelineAdapter(
                "advisory",
                lambda request: PipelineResponse(
                    status="pending",
                    pipeline="advisory",
                    task_id=request.task_id,
                    run_id=request.metadata.get("run_id", "run-system-approval"),
                    output={"draft": True},
                ),
                resume=resume,
            )
        },
    )
    pending = orchestrator.run(make_request("advisory"), run_id="run-system-approval")
    completed = orchestrator.resume(
        "run-system-approval",
        "task-1",
        {"decision": "approved", "reviewer_id": "reviewer-1"},
    )

    assert pending.status == "pending"
    approval_interrupt = pending.interrupt
    assert approval_interrupt is not None
    assert approval_interrupt["type"] == "approval.required"
    assert completed.status == "succeeded"
    assert decisions == [{"decision": "approved", "reviewer_id": "reviewer-1"}]
