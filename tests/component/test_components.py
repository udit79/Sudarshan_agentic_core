from __future__ import annotations

from crewai import TaskOutput
from memory import AccessContext, MemoryManager
from pipelines.common.contracts import AdvisoryRequest, PipelineResponse
from pipelines.common.memory_tools import MemoryRuntime, TaskMemoryWriter
from pipelines.orchestrator import (
    InMemoryProgressSink,
    ProgressEvent,
    PromptCrafterAgent,
    PipelineAdapter,
    PipelineRegistry,
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


def test_request_understanding_accepts_explicit_plugin_pipeline_names() -> None:
    request = make_request(
        metadata={"pipelines": ["partner_report", "partner_chart"]},
        query="Create the requested partner outputs",
    )

    understood = RequestUnderstandingAgent().run(request)

    assert understood.requested_pipelines == ["partner_report", "partner_chart"]


def test_pipeline_registry_is_a_small_plugin_registration_boundary() -> None:
    registry = PipelineRegistry()

    def run(request: AdvisoryRequest) -> PipelineResponse:
        return PipelineResponse(
            status="succeeded",
            pipeline="partner_report",
            task_id=request.task_id,
            run_id="run-plugin-test",
            output={"ok": True},
        )

    adapter = PipelineAdapter("partner_report", run)

    registry.register(adapter)

    assert registry["partner_report"] is adapter
    try:
        registry.register(adapter)
    except ValueError as exc:
        assert "already registered" in str(exc)
    else:
        raise AssertionError("duplicate pipeline plugins must be rejected")


def test_prompt_crafter_produces_bounded_memory_delimited_plan() -> None:
    request = make_request("advisory")
    understood = RequestUnderstandingAgent().run(request)
    plan = PromptCrafterAgent().run(request, understood, "verified fact")

    assert plan.pipeline == "advisory"
    assert "<sudarshan_memory_context>" in plan.prompt_text
    assert "</sudarshan_memory_context>" in plan.prompt_text
    assert len(plan.prompt_text) <= 60000


def test_revision_request_is_structured_and_preserves_parent_link() -> None:
    request = AdvisoryRequest(
        query="Regenerate only the opening paragraph",
        user_id="user-1",
        case_id="case-1",
        task_id="task-revision-1",
        operation="revise",
        parent_artifact_id="artifact-post-v1",
        revision_instruction="Make the opening more concise without changing facts.",
        revision_scope=("post_text.opening",),
        metadata={"pipeline": "linkedin_post"},
    )
    understanding = RequestUnderstandingAgent().run(request, memory_context="User prefers concise writing.")
    plan = PromptCrafterAgent().run(request, understanding, "The original post is in Case memory.")

    assert understanding.operation == "revise"
    assert understanding.parent_artifact_id == "artifact-post-v1"
    assert "post_text.opening" in plan.prompt_text
    assert "parent artifact" in plan.prompt_text


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


def test_task_memory_writer_registers_and_runs_video_callbacks(recording_backend) -> None:
    writer = TaskMemoryWriter(
        MemoryRuntime(
            manager=MemoryManager(recording_backend),
            context=AccessContext(user_id="user-1", case_id="case-1", task_id="task-1"),
            task_id="task-1",
            case_id="case-1",
            run_id="run-1",
            pipeline_name="video",
        )
    )
    output = TaskOutput(
        description="video task",
        expected_output="JSON",
        raw="{}",
        agent="test-agent",
    )

    with writer.activate():
        for step in ("video_evidence", "video_script", "video_storyboard", "video_quality"):
            writer.callback(step)(output)

    assert [write["metadata"]["step"] for write in recording_backend.writes] == [
        "video_evidence",
        "video_script",
        "video_storyboard",
        "video_quality",
    ]


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
