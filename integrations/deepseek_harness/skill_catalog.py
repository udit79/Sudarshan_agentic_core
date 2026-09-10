"""Canonical skill catalog shared by the native Harness and MCP clients."""

from __future__ import annotations

from typing import Any, Mapping

from pipelines.orchestrator.contracts import RunPolicy, SkillManifest
from skills.workspace import SkillWorkspace


SKILL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "presentation.case-brief": {
        "pipeline": "presentation",
        "purpose": "Create a grounded, editable intelligence briefing deck.",
        "output_artifact_types": ["pptx", "slide-preview"],
        "required_capabilities": ["render.presentation"],
        "allowed_tools": ["memory.recall", "diagram.layout", "artifact.write"],
        "quality_gates": ["schema", "evidence", "render", "overflow"],
        "risk_class": "RESTRICTED",
        "max_model_tokens": 6000,
    },
    "video.storyboard": {
        "pipeline": "video",
        "purpose": "Plan a case-grounded storyboard and render a controlled video package.",
        "output_artifact_types": ["storyboard", "video"],
        "required_capabilities": ["render.video"],
        "allowed_tools": ["memory.recall", "media.render", "artifact.write"],
        "quality_gates": ["schema", "evidence", "media"],
        "risk_class": "RESTRICTED",
        "max_model_tokens": 6000,
    },
    "infographic": {
        "pipeline": "infographic",
        "purpose": "Transform scoped evidence into a validated visual summary.",
        "output_artifact_types": ["svg", "png"],
        "required_capabilities": ["render.infographic"],
        "allowed_tools": ["memory.recall", "diagram.layout", "artifact.write"],
        "quality_gates": ["schema", "evidence", "visual"],
        "risk_class": "RESTRICTED",
        "max_model_tokens": 5000,
    },
    "linkedin.post": {
        "pipeline": "linkedin_post",
        "purpose": "Draft a grounded LinkedIn post with humanizer and approval checks.",
        "output_artifact_types": ["linkedin-draft"],
        "required_capabilities": ["write.social"],
        "allowed_tools": ["memory.recall", "artifact.write"],
        "quality_gates": ["schema", "evidence", "humanizer"],
        "risk_class": "RESTRICTED",
        "max_model_tokens": 4000,
    },
    "executive.summary": {
        "pipeline": "executive_summary",
        "purpose": "Produce a concise, evidence-linked intelligence summary.",
        "output_artifact_types": ["brief"],
        "required_capabilities": ["write.brief"],
        "allowed_tools": ["memory.recall", "artifact.write"],
        "quality_gates": ["schema", "evidence"],
        "risk_class": "RESTRICTED",
        "max_model_tokens": 3500,
    },
    "advisory.brief": {
        "pipeline": "advisory",
        "purpose": "Create a formal case advisory with provenance and uncertainty markers.",
        "output_artifact_types": ["advisory"],
        "required_capabilities": ["write.advisory"],
        "allowed_tools": ["memory.recall", "artifact.write"],
        "quality_gates": ["schema", "evidence", "policy"],
        "risk_class": "RESTRICTED",
        "max_model_tokens": 6000,
    },
    "visual.flowchart": {
        "pipeline": None,
        "purpose": "Create an editable, renderer-neutral flowchart IR for parent skills.",
        "output_artifact_types": ["diagram.ir", "svg"],
        "required_capabilities": ["render.diagram"],
        "allowed_tools": ["diagram.layout", "artifact.write"],
        "quality_gates": ["schema", "graph", "visual"],
        "risk_class": "RESTRICTED",
        "max_model_tokens": 3500,
    },
}


def build_skill_manifests() -> dict[str, SkillManifest]:
    manifests: dict[str, SkillManifest] = {}
    for skill_id, definition in SKILL_DEFINITIONS.items():
        manifests[skill_id] = SkillManifest(
            skill_id=skill_id,
            version="1.0.0",
            purpose=str(definition["purpose"]),
            input_schema="AdvisoryRequest",
            output_artifact_types=list(definition["output_artifact_types"]),
            required_capabilities=list(definition["required_capabilities"]),
            allowed_tools=list(definition["allowed_tools"]),
            budget_policy=RunPolicy(
                max_model_tokens=int(definition["max_model_tokens"]),
                max_wall_time_ms=300_000,
                max_parallel_children=2,
            ),
            quality_gates=list(definition["quality_gates"]),
            risk_class=str(definition["risk_class"]),
            coordination={"pipeline": definition["pipeline"]},
        )
    # The versioned workspace is authoritative for packaged skills. Keep the
    # definitions above as a compatibility fallback while teams migrate old
    # or locally generated packages.
    manifests.update(SkillWorkspace().manifests())
    return manifests


def skill_pipeline(skill_id: str) -> str | None:
    definition = SKILL_DEFINITIONS.get(skill_id)
    if definition and definition["pipeline"]:
        return str(definition["pipeline"])
    package = SkillWorkspace().get(skill_id)
    if package is not None:
        pipeline = package.manifest.coordination.get("pipeline")
        return str(pipeline) if pipeline else None
    return None


def canonical_skill_id(value: str) -> str:
    normalized = str(value).strip().lower()
    aliases = {
        "presentation": "presentation.case-brief",
        "ppt": "presentation.case-brief",
        "video": "video.storyboard",
        "linkedin_post": "linkedin.post",
        "executive_summary": "executive.summary",
        "advisory": "advisory.brief",
    }
    return aliases.get(normalized, normalized)


def skill_summary(manifest: SkillManifest, *, available: bool) -> dict[str, Any]:
    """Return a safe catalog entry without prompt bodies or provider details."""

    return {
        "skill_id": manifest.skill_id,
        "version": manifest.version,
        "purpose": manifest.purpose,
        "output_artifact_types": list(manifest.output_artifact_types),
        "required_capabilities": list(manifest.required_capabilities),
        "quality_gates": list(manifest.quality_gates),
        "risk_class": manifest.risk_class,
        "available": available,
        "pipeline": skill_pipeline(manifest.skill_id),
    }


__all__ = [
    "SKILL_DEFINITIONS",
    "build_skill_manifests",
    "canonical_skill_id",
    "skill_pipeline",
    "skill_summary",
]
