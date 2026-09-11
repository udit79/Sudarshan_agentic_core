"""Planning and reconciliation helpers for cross-skill child execution."""

from __future__ import annotations

from collections.abc import Iterable

from pipelines.orchestrator.contracts import ChildTaskOutcome, ChildTaskSpec, SkillResult


def reconcile_child_result(spec: ChildTaskSpec, result: SkillResult) -> ChildTaskOutcome:
    """Turn a runtime result into a deterministic parent delivery decision."""

    if result.skill_call_id != spec.child_id:
        raise ValueError("child result does not belong to the planned child task")
    succeeded = result.status == "succeeded"
    fallback_used = None if succeeded else spec.fallback
    return ChildTaskOutcome(
        child_id=spec.child_id,
        status=result.status,
        artifact_ids=list(result.artifact_ids),
        quality_report_id=result.quality_report_id,
        fallback_used=fallback_used,
        delivery_blocked=not succeeded and spec.required,
        failure_code=result.failure_code,
    )


def validate_child_plan(specs: Iterable[ChildTaskSpec]) -> tuple[ChildTaskSpec, ...]:
    """Validate unique IDs and dependency references before DAG admission."""

    items = tuple(specs)
    ids = {item.child_id for item in items}
    if len(ids) != len(items):
        raise ValueError("child task IDs must be unique")
    for item in items:
        unknown = set(item.dependencies) - ids
        if unknown:
            raise ValueError(f"child task {item.child_id} has unknown dependencies: {sorted(unknown)}")
    return items


__all__ = ["reconcile_child_result", "validate_child_plan"]
