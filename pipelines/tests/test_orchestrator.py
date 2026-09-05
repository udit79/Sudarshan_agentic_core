from types import SimpleNamespace

from pipelines.common.contracts import AdvisoryRequest, PipelineResponse
from pipelines.orchestrator import (
    InMemoryProgressSink,
    PipelineAdapter,
    PipelineOrchestrator,
    PromptCrafterAgent,
    RequestUnderstandingAgent,
)


class FakeMemoryManager:
    def recall(self, **_: object) -> SimpleNamespace:
        return SimpleNamespace(
            context=SimpleNamespace(text="case fact: approved source context"),
            results=[],
        )


def request(pipeline: str | None = None) -> AdvisoryRequest:
    return AdvisoryRequest(
        query=f"Run the {pipeline or 'requested'} operation",
        user_id="user-1",
        case_id="case-1",
        task_id="task-1",
        metadata={"pipeline": pipeline} if pipeline else {},
    )


def response(status: str, pipeline: str, task_id: str, run_id: str) -> PipelineResponse:
    return PipelineResponse(
        status=status,  # type: ignore[arg-type]
        pipeline=pipeline,
        task_id=task_id,
        run_id=run_id,
        output={"value": "validated"} if status == "succeeded" else {"draft": True},
        failure=None if status != "failed" else "failed",
    )


def test_orchestrator_routes_and_publishes_frontend_progress() -> None:
    sink = InMemoryProgressSink()
    received: list[AdvisoryRequest] = []

    def run(req: AdvisoryRequest) -> PipelineResponse:
        received.append(req)
        return response("succeeded", "linkedin_post", req.task_id, "run-from-pipeline")

    orchestrator = PipelineOrchestrator(
        FakeMemoryManager(),
        registry={
            "linkedin_post": PipelineAdapter(
                "linkedin_post",
                run,
            )
        },
        progress_sink=sink,
    )

    result = orchestrator.run(request("linkedin_post"), run_id="run-progress")

    assert result.status == "succeeded"
    assert result.pipeline == "linkedin_post"
    assert received[0].metadata["request_understanding"]["requested_pipeline"] == "linkedin_post"
    assert received[0].metadata["prompt_plan"]["pipeline"] == "linkedin_post"
    assert received[0].metadata["resolved_memory_context"] == "case fact: approved source context"
    assert [event.stage for event in sink.events("run-progress")] == [
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
    assert sink.events("run-progress")[-1].progress == 100


def test_orchestrator_can_pause_and_resume_an_external_approval() -> None:
    decisions: list[dict[str, object]] = []

    def resume(req: AdvisoryRequest, decision: dict[str, object]) -> PipelineResponse:
        decisions.append(decision)
        return response("succeeded", "advisory", req.task_id, "run-approval")

    orchestrator = PipelineOrchestrator(
        FakeMemoryManager(),
        registry={
            "advisory": PipelineAdapter(
                "advisory",
                lambda req: response("pending", "advisory", req.task_id, "run-approval"),
                resume=resume,
            )
        },
    )

    pending = orchestrator.run(request("advisory"), run_id="run-approval")
    assert pending.status == "pending"
    assert pending.requires_action
    assert pending.interrupt is not None

    completed = orchestrator.resume(
        "run-approval",
        "task-1",
        {"decision": "approved", "reviewer_id": "reviewer-1"},
    )

    assert completed.status == "succeeded"
    assert decisions == [{"decision": "approved", "reviewer_id": "reviewer-1"}]


def test_orchestrator_rejects_ambiguous_requests_without_routing() -> None:
    orchestrator = PipelineOrchestrator(FakeMemoryManager(), registry={})

    result = orchestrator.run(request())

    assert result.status == "failed"
    assert result.response is None


def test_request_understanding_is_structured_and_conservative() -> None:
    understood = RequestUnderstandingAgent().run(request("linkedin_post"))

    assert understood.requested_pipeline == "linkedin_post"
    assert understood.image_requested is None
    assert understood.classification_level == "RESTRICTED"
    assert 0.0 <= understood.confidence <= 1.0


def test_prompt_crafter_delimits_recalled_memory_and_preserves_delivery_policy() -> None:
    req = request("advisory")
    understood = RequestUnderstandingAgent().run(req)
    plan = PromptCrafterAgent().run(req, understood, "verified case fact")

    assert plan.pipeline == "advisory"
    assert "<sudarshan_memory_context>" in plan.prompt_text
    assert "verified case fact" in plan.prompt_text
    assert "RESTRICTED" in plan.prompt_text
