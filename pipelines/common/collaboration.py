"""Typed collaboration plans shared by selected generation pipelines.

The coordinator lets pipeline-level planners exchange bounded proposals without
giving one pipeline direct access to another pipeline's Python internals.  The
plan is deterministic today so collaboration does not add an LLM call or cost;
an optional model-backed crafter can later populate the same schemas.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field


class PipelineCapability(BaseModel):
    """Versioned capability information exposed to the coordinator."""

    model_config = ConfigDict(extra="forbid")

    pipeline: str = Field(min_length=1, max_length=64)
    version: str = Field(default="1", min_length=1, max_length=32)
    produces: list[str] = Field(default_factory=list, max_length=20)
    consumes: list[str] = Field(default_factory=list, max_length=20)
    focus: list[str] = Field(default_factory=list, max_length=20)


class PipelinePlan(BaseModel):
    """A bounded proposal from one pipeline-level planner."""

    model_config = ConfigDict(extra="forbid")

    pipeline: str = Field(min_length=1, max_length=64)
    capability_version: str = Field(default="1", min_length=1, max_length=32)
    objective: str = Field(min_length=1, max_length=1200)
    peer_pipelines: list[str] = Field(default_factory=list, max_length=8)
    required_context: list[str] = Field(default_factory=list, max_length=20)
    requested_artifacts: list[str] = Field(default_factory=list, max_length=20)
    proposed_dependencies: list[str] = Field(default_factory=list, max_length=8)
    constraints: list[str] = Field(default_factory=list, max_length=30)


class CollaborationMessage(BaseModel):
    """A safe, auditable message between a pipeline crafter and coordinator."""

    model_config = ConfigDict(extra="forbid")

    sender: str = Field(min_length=1, max_length=64)
    recipient: str = Field(default="coordinator", min_length=1, max_length=64)
    kind: Literal["proposal", "dependency_request", "shared_constraint", "conflict"]
    message: str = Field(min_length=1, max_length=1200)


class CollaborativeWorkflowPlan(BaseModel):
    """Merged execution plan returned to the LangGraph control plane."""

    model_config = ConfigDict(extra="forbid")

    version: str = Field(default="1", min_length=1, max_length=32)
    pipelines: list[str] = Field(default_factory=list, max_length=8)
    plans: list[PipelinePlan] = Field(default_factory=list, max_length=8)
    dependencies: dict[str, list[str]] = Field(default_factory=dict)
    execution_waves: list[list[str]] = Field(default_factory=list, max_length=8)
    shared_constraints: list[str] = Field(default_factory=list, max_length=30)
    messages: list[CollaborationMessage] = Field(default_factory=list, max_length=40)


CAPABILITIES: dict[str, PipelineCapability] = {
    "advisory": PipelineCapability(
        pipeline="advisory",
        produces=["advisory_artifact", "evidence_pack"],
        consumes=["bounded_case_memory"],
        focus=["evidence", "provenance", "decision_support"],
    ),
    "executive_summary": PipelineCapability(
        pipeline="executive_summary",
        produces=["executive_summary_artifact"],
        consumes=["bounded_case_memory", "evidence_pack"],
        focus=["synthesis", "decision_relevance"],
    ),
    "linkedin_post": PipelineCapability(
        pipeline="linkedin_post",
        produces=["linkedin_draft", "optional_image"],
        consumes=["bounded_case_memory", "evidence_pack"],
        focus=["public_communication", "audience_fit"],
    ),
    "infographic": PipelineCapability(
        pipeline="infographic",
        produces=["infographic_svg"],
        consumes=["bounded_case_memory", "evidence_pack"],
        focus=["visual_hierarchy", "structured_facts"],
    ),
    "presentation": PipelineCapability(
        pipeline="presentation",
        produces=["presentation_pptx"],
        consumes=["bounded_case_memory", "evidence_pack"],
        focus=["briefing_structure", "speaker_notes"],
    ),
    "ppt": PipelineCapability(
        pipeline="ppt",
        version="1-legacy-alias",
        produces=["presentation_pptx"],
        consumes=["bounded_case_memory", "evidence_pack"],
        focus=["briefing_structure", "speaker_notes"],
    ),
    "video": PipelineCapability(
        pipeline="video",
        produces=["video_package", "video_mp4"],
        consumes=["bounded_case_memory", "evidence_pack"],
        focus=["narration", "storyboard", "media_rendering"],
    ),
}


def _capability(pipeline: str) -> PipelineCapability:
    return CAPABILITIES.get(
        pipeline,
        PipelineCapability(
            pipeline=pipeline,
            produces=[f"{pipeline}_artifact"],
            consumes=["bounded_case_memory"],
            focus=["pipeline_specific_generation"],
        ),
    )


def _metadata_dependencies(metadata: Mapping[str, Any], pipelines: list[str]) -> dict[str, list[str]]:
    raw = metadata.get("pipeline_dependencies", {})
    if raw is None:
        return {pipeline: [] for pipeline in pipelines}
    if not isinstance(raw, Mapping):
        raise ValueError("metadata.pipeline_dependencies must be an object")

    selected = set(pipelines)
    dependencies: dict[str, list[str]] = {pipeline: [] for pipeline in pipelines}
    for target, sources in raw.items():
        target_name = str(target).strip().lower()
        if target_name not in selected:
            raise ValueError(f"pipeline dependency target '{target_name}' is not selected")
        if isinstance(sources, str):
            sources = [sources]
        if not isinstance(sources, (list, tuple)):
            raise ValueError(f"pipeline dependencies for '{target_name}' must be a list")
        cleaned = []
        for source in sources:
            source_name = str(source).strip().lower()
            if source_name not in selected:
                raise ValueError(
                    f"pipeline dependency '{source_name}' for '{target_name}' is not selected"
                )
            if source_name == target_name:
                raise ValueError(f"pipeline '{target_name}' cannot depend on itself")
            if source_name not in cleaned:
                cleaned.append(source_name)
        dependencies[target_name] = cleaned
    return dependencies


def _execution_waves(pipelines: list[str], dependencies: Mapping[str, list[str]]) -> list[list[str]]:
    """Topologically order selected pipelines into parallel execution waves."""

    indegree = {pipeline: len(dependencies.get(pipeline, [])) for pipeline in pipelines}
    children: dict[str, list[str]] = defaultdict(list)
    for target, sources in dependencies.items():
        for source in sources:
            children[source].append(target)

    remaining = set(pipelines)
    waves: list[list[str]] = []
    while remaining:
        ready = sorted(pipeline for pipeline in remaining if indegree[pipeline] == 0)
        if not ready:
            raise ValueError("pipeline_dependencies contains a cycle")
        waves.append(ready)
        for source in ready:
            remaining.remove(source)
            for child in children[source]:
                indegree[child] -= 1
    return waves


def build_collaborative_workflow(
    pipelines: list[str] | tuple[str, ...],
    prompt_plans: Mapping[str, Mapping[str, Any]],
    *,
    metadata: Mapping[str, Any] | None = None,
    classification_level: str = "RESTRICTED",
    distribution: str = "Authorized NTRO personnel",
) -> CollaborativeWorkflowPlan:
    """Merge pipeline proposals without performing additional model calls.

    Explicit dependencies are opt-in through ``metadata.pipeline_dependencies``.
    Until artifact handoff is implemented for a dependency, the coordinator
    rejects unselected nodes and cycles rather than silently running a wrong
    order. All selected pipelines still share the central bounded memory pack.
    """

    selected = []
    for item in pipelines:
        name = str(item).strip().lower()
        if name and name not in selected:
            selected.append(name)
    if not selected:
        raise ValueError("at least one pipeline is required for collaboration")
    if len(selected) > 8:
        raise ValueError("collaborative workflow cannot contain more than 8 pipelines")

    dependencies = _metadata_dependencies(metadata or {}, selected)
    plans: list[PipelinePlan] = []
    messages: list[CollaborationMessage] = []
    for pipeline in selected:
        capability = _capability(pipeline)
        source = dict(prompt_plans.get(pipeline, {}))
        explicit_constraints = [
            str(value).strip()[:500]
            for value in source.get("delivery_constraints", [])
            if str(value).strip()
        ]
        constraints = [
            f"classification: {classification_level}",
            f"distribution: {distribution}",
            "Use only the shared bounded memory pack and approved artifact references.",
            *explicit_constraints,
        ]
        peer_pipelines = [other for other in selected if other != pipeline]
        plan = PipelinePlan(
            pipeline=pipeline,
            capability_version=capability.version,
            objective=str(source.get("objective") or f"Generate a validated {pipeline} output"),
            peer_pipelines=peer_pipelines,
            required_context=capability.consumes,
            requested_artifacts=capability.produces,
            proposed_dependencies=dependencies[pipeline],
            constraints=constraints,
        )
        plans.append(plan)
        messages.append(CollaborationMessage(
            sender=pipeline,
            kind="proposal",
            message=(
                f"{pipeline} proposes {', '.join(capability.produces)} and requires "
                f"{', '.join(capability.consumes)}."
            ),
        ))

    shared_constraints = [
        f"classification: {classification_level}",
        f"distribution: {distribution}",
        "All pipelines use the same case terminology and bounded evidence context.",
        "Pipeline outputs remain isolated until the coordinator validates an artifact handoff.",
    ]
    if len(selected) > 1:
        messages.append(CollaborationMessage(
            sender="coordinator",
            kind="shared_constraint",
            message="Selected pipelines must preserve shared terminology, provenance, and delivery markings.",
        ))

    return CollaborativeWorkflowPlan(
        pipelines=selected,
        plans=plans,
        dependencies=dependencies,
        execution_waves=_execution_waves(selected, dependencies),
        shared_constraints=shared_constraints,
        messages=messages,
    )


__all__ = [
    "CAPABILITIES",
    "CollaborationMessage",
    "CollaborativeWorkflowPlan",
    "PipelineCapability",
    "PipelinePlan",
    "build_collaborative_workflow",
]
