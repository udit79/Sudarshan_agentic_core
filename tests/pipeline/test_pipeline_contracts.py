from __future__ import annotations

from threading import Barrier, Lock

import pytest

from pipelines.common.contracts import AdvisoryRequest, PipelineResponse
from pipelines import InMemoryProgressSink, PipelineAdapter, PipelineOrchestrator

from tests.conftest import FakeRecallManager, make_request, successful_response


@pytest.mark.parametrize(
    "pipeline",
    ["advisory", "linkedin_post", "executive_summary", "infographic"],
)
def test_pipeline_contract_runs_each_registered_generation_pipeline(pipeline: str) -> None:
    sink = InMemoryProgressSink()
    seen = []

    def run(request):
        seen.append(request)
        assert request.metadata["pipeline"] == pipeline
        assert request.metadata["prompt_plan"]["pipeline"] == pipeline
        assert request.metadata["resolved_memory_context"] == "verified case context"
        return successful_response(request, pipeline)

    orchestrator = PipelineOrchestrator(
        FakeRecallManager(),
        registry={pipeline: PipelineAdapter(pipeline, run)},
        progress_sink=sink,
    )
    result = orchestrator.run(make_request(pipeline), run_id=f"run-{pipeline}")

    assert result.status == "succeeded"
    assert result.pipeline == pipeline
    assert len(seen) == 1
    assert sink.events(f"run-{pipeline}")[-1].stage == "completed"


def test_pipeline_contract_rejects_unregistered_route() -> None:
    orchestrator = PipelineOrchestrator(FakeRecallManager(), registry={})
    result = orchestrator.run(make_request("ppt"), run_id="run-unregistered")

    assert result.status == "failed"
    assert result.response is None


def test_pending_provider_job_is_not_treated_as_human_approval() -> None:
    def run(request: AdvisoryRequest):
        return PipelineResponse(
            status="pending",
            pipeline="video",
            task_id=request.task_id,
            run_id=str(request.metadata.get("run_id", "test-run")),
            artifact={"provider_task_id": "mpt-1"},
            metadata={"human_approval_required": False},
        )

    orchestrator = PipelineOrchestrator(
        FakeRecallManager(),
        registry={"video": PipelineAdapter("video", run)},
    )
    result = orchestrator.run(make_request("video"), run_id="run-video-pending")

    assert result.status == "pending"
    assert result.interrupt is None
    assert result.response is not None
    assert result.response.metadata["human_approval_required"] is False


def test_revision_request_links_new_result_to_parent_artifact() -> None:
    seen: list[AdvisoryRequest] = []

    def run(request: AdvisoryRequest):
        seen.append(request)
        return successful_response(request, "linkedin_post")

    request = AdvisoryRequest(
        query="Make only the opening shorter",
        user_id="user-1",
        case_id="case-1",
        task_id="task-revision",
        operation="revise",
        parent_artifact_id="artifact-post-v1",
        revision_instruction="Make only the opening shorter and preserve the facts.",
        revision_scope=("post_text.opening",),
        metadata={"pipeline": "linkedin_post"},
    )
    orchestrator = PipelineOrchestrator(
        FakeRecallManager(),
        registry={"linkedin_post": PipelineAdapter("linkedin_post", run)},
    )

    result = orchestrator.run(request, run_id="run-revision")

    assert result.status == "succeeded"
    assert seen[0].operation == "revise"
    assert seen[0].parent_artifact_id == "artifact-post-v1"
    assert result.response is not None
    assert result.response.metadata["parent_artifact_id"] == "artifact-post-v1"


def test_router_fans_out_requested_pipelines_with_isolated_child_runs() -> None:
    sink = InMemoryProgressSink()
    barrier = Barrier(2)
    lock = Lock()
    active = 0
    max_active = 0
    seen: dict[str, AdvisoryRequest] = {}

    def run(request: AdvisoryRequest):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
            seen[request.metadata["pipeline"]] = request
        barrier.wait(timeout=5)
        with lock:
            active -= 1
        return successful_response(request, str(request.metadata["pipeline"]))

    orchestrator = PipelineOrchestrator(
        FakeRecallManager(),
        registry={
            "ppt": PipelineAdapter("ppt", run),
            "linkedin_post": PipelineAdapter("linkedin_post", run),
        },
        progress_sink=sink,
    )
    request = make_request(
        query="Create a PPT and a LinkedIn post for this case",
    )

    result = orchestrator.run(request, run_id="run-parallel")

    assert result.status == "succeeded"
    assert set(result.responses) == {"ppt", "linkedin_post"}
    assert max_active == 2
    assert seen["ppt"].task_id != seen["linkedin_post"].task_id
    assert seen["ppt"].metadata["parent_orchestration_run_id"] == "run-parallel"
    assert seen["linkedin_post"].metadata["parent_orchestration_run_id"] == "run-parallel"
    assert {event.pipeline for event in sink.events("run-parallel") if event.stage == "pipeline_result"} == {
        "ppt",
        "linkedin_post",
    }


def test_revision_routes_only_the_selected_artifact_pipeline() -> None:
    calls: list[tuple[str, str, str | None]] = []

    def run(request: AdvisoryRequest):
        calls.append((str(request.metadata["pipeline"]), request.task_id, request.parent_artifact_id))
        return successful_response(request, str(request.metadata["pipeline"]))

    registry = {
        "ppt": PipelineAdapter("ppt", run),
        "linkedin_post": PipelineAdapter("linkedin_post", run),
    }
    orchestrator = PipelineOrchestrator(FakeRecallManager(), registry=registry)
    revised = AdvisoryRequest(
        query="Shorten the LinkedIn opening",
        user_id="user-1",
        case_id="case-1",
        task_id="task-revise-linkedin",
        requested_pipelines=("linkedin_post",),
        operation="revise",
        parent_artifact_id="artifact-linkedin-v1",
        revision_instruction="Shorten only the opening; do not change the PPT.",
        revision_scope=("post_text.opening",),
    )

    result = orchestrator.run(revised, run_id="run-revise-linkedin")

    assert result.status == "succeeded"
    assert [call[0] for call in calls] == ["linkedin_post"]
    assert calls[0][2] == "artifact-linkedin-v1"
