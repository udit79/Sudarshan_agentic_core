from __future__ import annotations

from memory import AccessContext, MemoryManager
from pipelines.common.memory_tools import MemoryRuntime, TaskMemoryWriter
from pipelines.orchestrator import (
    InMemoryProgressSink,
    ProgressEvent,
    PromptCrafterAgent,
    RequestUnderstandingAgent,
)

from tests.conftest import FakeRecallManager, make_request


def test_request_understanding_selects_pipeline_and_image_policy() -> None:
    understood = RequestUnderstandingAgent().run(
        make_request(query="Create a LinkedIn post with an image")
    )

    assert understood.requested_pipeline == "linkedin_post"
    assert understood.image_requested is True
    assert understood.clarification_required is False


def test_request_understanding_requests_clarification_for_ambiguous_input() -> None:
    understood = RequestUnderstandingAgent().run(make_request())

    assert understood.clarification_required is True
    assert understood.requested_pipeline == "unknown"
    assert understood.clarification_questions


def test_prompt_crafter_produces_bounded_memory_delimited_plan() -> None:
    request = make_request("advisory")
    understood = RequestUnderstandingAgent().run(request)
    plan = PromptCrafterAgent().run(request, understood, "verified fact")

    assert plan.pipeline == "advisory"
    assert "<sudarshan_memory_context>" in plan.prompt_text
    assert "</sudarshan_memory_context>" in plan.prompt_text
    assert len(plan.prompt_text) <= 60000


def test_task_memory_writer_uses_task_scope(recording_backend) -> None:
    writer = TaskMemoryWriter(
        MemoryRuntime(
            manager=MemoryManager(recording_backend),
            context=AccessContext(user_id="user-1", case_id="case-1", task_id="task-1"),
            task_id="task-1",
            case_id="case-1",
            run_id="run-1",
        )
    )
    writer.write("prompt_crafting", "succeeded", "Prompt plan created")

    assert recording_backend.writes[0]["node_sets"] == ["sudarshan:scope:task:task-1"]
    assert recording_backend.writes[0]["metadata"]["step"] == "prompt_crafting"


def test_progress_contract_accepts_clarification_waiting_state() -> None:
    event = ProgressEvent(
        run_id="run-1",
        task_id="task-1",
        stage="request_clarification",
        status="waiting_for_input",
        progress=15,
        message="More information is required",
        requires_action=True,
    )

    assert event.requires_action is True
