"""Typed optional visual-child composition for the LinkedIn parent skill."""

from __future__ import annotations

from pipelines.linkedin.schemas import LinkedInPostOutput
from pipelines.orchestrator.cross_skill import select_visual_child_skill
from pipelines.orchestrator.contracts import RunPolicy, SkillCall


def build_visual_child_call(
    output: LinkedInPostOutput,
    *,
    parent_run_id: str,
    parent_node_id: str = "linkedin_post",
    skill_version: str = "1.0.0",
) -> SkillCall | None:
    """Build, but do not execute, a visual specialist call when eligible."""

    if not output.image.requested or output.image.image_type not in {"diagram", "infographic"}:
        return None
    skill_id = select_visual_child_skill(output.image.model_dump(mode="json"))
    return SkillCall(
        skill_call_id=f"{parent_run_id}:visual-{skill_id.replace('.', '-')}",
        parent_run_id=parent_run_id,
        parent_node_id=parent_node_id,
        skill_id=skill_id,
        skill_version=skill_version,
        input_payload={
            "purpose": "Create an editable, case-grounded visual for a LinkedIn draft.",
            "alt_text": output.image.alt_text,
            "generation_prompt": output.image.generation_prompt,
            "source_references": list(output.source_references),
            "claim_bindings": [binding.model_dump(mode="json") for binding in output.claim_bindings],
        },
        policy=RunPolicy(
            max_wall_time_ms=120_000,
            max_model_tokens=2_000,
            max_tool_calls=8,
            max_parallel_children=1,
        ),
        depth=1,
        max_depth=3,
    )


__all__ = ["build_visual_child_call"]
