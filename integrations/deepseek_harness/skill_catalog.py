"""Compatibility export for the optional DeepSeek Harness adapter."""

from skills.catalog import (
    SKILL_DEFINITIONS,
    build_skill_manifests,
    canonical_skill_id,
    skill_pipeline,
    skill_summary,
)

__all__ = [
    "SKILL_DEFINITIONS",
    "build_skill_manifests",
    "canonical_skill_id",
    "skill_pipeline",
    "skill_summary",
]
