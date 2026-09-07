"""Role-based OpenAI model selection for CrewAI agents.

The application keeps a strong model for high-consequence synthesis and
release gates, while using the mini tier for bounded extraction and formatting.
Every role can be overridden through an environment variable without changing
pipeline code.
"""

from __future__ import annotations

import os
from typing import Any


def _configured(name: str, fallback: str) -> str:
    return os.getenv(name, fallback).strip() or fallback


def resolve_model(role: str, *, override: Any = None) -> Any:
    """Resolve a CrewAI model for a named role.

    An injected ``override`` remains authoritative for tests or deployments
    that provide a custom CrewAI LLM object. Otherwise, role-specific
    environment variables take precedence over the strong/fast defaults.
    """

    if override is not None:
        return override

    primary = _configured("CREWAI_MODEL", "openai/gpt-5.4")
    fast = _configured("CREWAI_FAST_MODEL", "openai/gpt-5.4-mini")
    role_env = {
        "advisory_intelligence": "ADVISORY_INTELLIGENCE_MODEL",
        "advisory_provenance": "ADVISORY_PROVENANCE_MODEL",
        "advisory_writer": "ADVISORY_WRITER_MODEL",
        "advisory_quality": "ADVISORY_QUALITY_MODEL",
        "executive_analyst": "EXECUTIVE_ANALYST_MODEL",
        "executive_writer": "EXECUTIVE_WRITER_MODEL",
        "executive_quality": "EXECUTIVE_QUALITY_MODEL",
        "linkedin_analyst": "LINKEDIN_ANALYST_MODEL",
        "linkedin_writer": "LINKEDIN_WRITER_MODEL",
        "linkedin_quality": "LINKEDIN_QUALITY_MODEL",
        "infographic_analyst": "INFOGRAPHIC_ANALYST_MODEL",
        "infographic_writer": "INFOGRAPHIC_WRITER_MODEL",
        "infographic_quality": "INFOGRAPHIC_QUALITY_MODEL",
        "presentation_analyst": "PRESENTATION_ANALYST_MODEL",
        "presentation_writer": "PRESENTATION_WRITER_MODEL",
        "presentation_quality": "PRESENTATION_QUALITY_MODEL",
        "video_evidence": "VIDEO_EVIDENCE_MODEL",
        "video_script": "VIDEO_SCRIPT_MODEL",
        "video_storyboard": "VIDEO_STORYBOARD_MODEL",
        "video_quality": "VIDEO_QUALITY_MODEL",
    }
    explicit_name = role_env.get(role)
    if explicit_name:
        explicit = os.getenv(explicit_name, "").strip()
        if explicit:
            return explicit

    fast_roles = {
        "linkedin_analyst",
        "linkedin_writer",
        "linkedin_quality",
        "infographic_analyst",
        "infographic_writer",
        "presentation_analyst",
        "video_evidence",
        "video_storyboard",
    }
    return fast if role in fast_roles else primary


__all__ = ["resolve_model"]
