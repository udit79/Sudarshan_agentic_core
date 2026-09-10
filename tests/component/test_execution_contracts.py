from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from pipelines.orchestrator.contracts import (
    ArtifactManifest,
    ContextPack,
    NodeSpec,
    QualityReport,
    RunEvent,
    RunPolicy,
    RunSummary,
    SkillCall,
    UsageRecord,
    project_progress_event,
)


FIXTURES = Path(__file__).resolve().parents[1] / "contracts"


def test_run_summary_and_event_are_strict_and_replayable() -> None:
    summary = RunSummary(
        run_id="run-1",
        task_id="task-1",
        case_id="case-1",
        skill_id="presentation.case-brief",
        skill_version="1.0.0",
        execution_version="2026.1",
        status="running",
        stage="planning",
    )
    event = project_progress_event(
        {
            "event_id": "evt-1",
            "run_id": summary.run_id,
            "task_id": summary.task_id,
            "stage": "planning",
            "status": "planning",
            "progress": 20,
        },
        sequence=1,
    )

    assert summary.model_dump(mode="json")["skill_id"] == "presentation.case-brief"
    assert event.sequence == 1
    assert event.status == "planning"

    with pytest.raises(ValidationError):
        RunEvent(
            event_id="evt-2",
            run_id="run-1",
            task_id="task-1",
            sequence=2,
            stage="planning",
            status="planning",
            unexpected="must be rejected",
        )


def test_artifact_manifest_requires_lowercase_sha256() -> None:
    valid = ArtifactManifest(
        artifact_id="artifact-1",
        run_id="run-1",
        kind="pptx",
        name="brief.pptx",
        uri="/artifacts/artifact-1/download",
        sha256="a" * 64,
        size_bytes=10,
        classification_level="RESTRICTED",
        renderer_version="ppt@1",
        schema_version="1",
    )
    assert valid.sha256 == "a" * 64

    with pytest.raises(ValidationError):
        ArtifactManifest(
            **{
                **valid.model_dump(),
                "sha256": "not-a-hash",
            }
        )


def test_skill_call_rejects_depth_overflow_and_node_self_dependency() -> None:
    with pytest.raises(ValidationError):
        SkillCall(
            skill_call_id="call-1",
            parent_run_id="run-1",
            parent_node_id="node-1",
            skill_id="visual.flowchart",
            skill_version="1.0.0",
            depth=4,
            max_depth=3,
        )

    with pytest.raises(ValidationError):
        NodeSpec(
            node_id="node-1",
            skill_id="presentation.case-brief",
            output_schema="DeckPlan",
            dependencies=["node-1"],
        )


def test_budget_context_and_usage_have_non_negative_limits() -> None:
    policy = RunPolicy(max_model_tokens=4000, max_parallel_children=2)
    usage = UsageRecord(
        usage_id="usage-1",
        run_id="run-1",
        provider="test",
        model="test-model",
        input_tokens=100,
        output_tokens=50,
        is_estimate=True,
    )
    context = ContextPack(
        pack_id="pack-1",
        run_id="run-1",
        stage_id="grounding",
        query="case facts",
        token_budget=500,
    )

    assert policy.max_parallel_children == 2
    assert usage.input_tokens + usage.output_tokens == 150
    assert context.token_budget == 500


@pytest.mark.parametrize(
    ("filename", "model"),
    [
        ("run-summary.running.json", RunSummary),
        ("run-summary.waiting.json", RunSummary),
        ("run-summary.completed.json", RunSummary),
        ("artifact-manifest.pptx.json", ArtifactManifest),
        ("quality-report.passed.json", QualityReport),
        ("quality-report.failed.json", QualityReport),
        ("usage-record.json", UsageRecord),
        ("context-pack.json", ContextPack),
    ],
)
def test_contract_fixtures_validate(filename: str, model: type) -> None:
    payload = json.loads((FIXTURES / filename).read_text(encoding="utf-8"))
    assert model.model_validate(payload).model_dump(mode="json")


def test_event_fixture_is_strict_ndjson() -> None:
    lines = (FIXTURES / "run-events.ndjson").read_text(encoding="utf-8").splitlines()
    events = [RunEvent.model_validate(json.loads(line)) for line in lines]
    assert [event.sequence for event in events] == [1, 2]
