from __future__ import annotations

import pytest

from pipelines.common.collaboration import build_collaborative_workflow


def test_collaborative_workflow_creates_parallel_wave_by_default() -> None:
    plan = build_collaborative_workflow(
        ["advisory", "video", "infographic"],
        {
            "advisory": {"objective": "Prepare evidence"},
            "video": {"objective": "Create a case video"},
            "infographic": {"objective": "Create a visual summary"},
        },
        classification_level="RESTRICTED",
        distribution="Authorized NTRO personnel",
    )

    assert plan.execution_waves == [["advisory", "infographic", "video"]]
    assert plan.dependencies == {"advisory": [], "video": [], "infographic": []}
    assert any(message.kind == "shared_constraint" for message in plan.messages)


def test_collaborative_workflow_honors_explicit_dependency_waves() -> None:
    plan = build_collaborative_workflow(
        ["advisory", "video", "presentation"],
        {},
        metadata={"pipeline_dependencies": {"video": ["advisory"]}},
    )

    assert plan.execution_waves == [["advisory", "presentation"], ["video"]]
    assert plan.dependencies["video"] == ["advisory"]


def test_collaborative_workflow_rejects_dependency_cycles() -> None:
    with pytest.raises(ValueError, match="cycle"):
        build_collaborative_workflow(
            ["advisory", "video"],
            {},
            metadata={"pipeline_dependencies": {"video": ["advisory"], "advisory": ["video"]}},
        )
