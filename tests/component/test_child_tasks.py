import pytest

from pipelines.orchestrator.child_tasks import reconcile_child_result, validate_child_plan
from pipelines.orchestrator.contracts import ChildTaskSpec, SkillResult


def test_optional_child_failure_uses_typed_fallback_without_blocking_parent():
    spec = ChildTaskSpec(
        child_id="slide-2-flowchart",
        parent_run_id="run-1",
        parent_node_id="slide-2",
        skill_id="visual.flowchart",
        required=False,
        fallback="replace-with-bullets",
    )
    outcome = reconcile_child_result(
        spec,
        SkillResult(
            skill_call_id=spec.child_id,
            child_run_id="child-run",
            status="failed",
            failure_code="QUALITY_GATE",
        ),
    )
    assert outcome.fallback_used == "replace-with-bullets"
    assert outcome.delivery_blocked is False


def test_required_child_failure_blocks_parent_and_dependencies_are_checked():
    first = ChildTaskSpec(
        child_id="chart",
        parent_run_id="run-1",
        parent_node_id="slide-1",
        skill_id="visual.chart",
    )
    second = ChildTaskSpec(
        child_id="slide",
        parent_run_id="run-1",
        parent_node_id="deck",
        skill_id="presentation.slide",
        dependencies=["chart"],
    )
    assert validate_child_plan([first, second]) == (first, second)
    outcome = reconcile_child_result(
        first,
        SkillResult(skill_call_id="chart", child_run_id="child", status="blocked", failure_code="BUDGET"),
    )
    assert outcome.delivery_blocked is True
    with pytest.raises(ValueError, match="unknown dependencies"):
        validate_child_plan([second])
