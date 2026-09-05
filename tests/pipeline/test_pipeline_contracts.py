from __future__ import annotations

import pytest

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
