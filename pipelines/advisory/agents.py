"""NTRO-specific, case-advisory CrewAI agent definitions."""

from __future__ import annotations

import os
from typing import Any

from crewai import Agent
from crewai.tools import BaseTool

from pipelines.common.prompt_policy import NTRO_AGENT_GUARDRAILS


def build_agents(tools: list[BaseTool], *, llm: Any = None) -> dict[str, Agent]:
    """Create the four advisory specialists with a shared, narrow memory tool."""

    common = {
        "verbose": False,
        "allow_delegation": False,
        "tools": tools,
    }
    configured_llm = llm or os.getenv("CREWAI_MODEL")
    if configured_llm:
        common["llm"] = configured_llm

    return {
        "intelligence_analyst": Agent(
            role="NTRO Case Intelligence Analyst",
            goal="Separate confirmed case information from analysis and identify information gaps.",
            backstory=(
                "You prepare defensible case assessments for an NTRO context. "
                "You never invent facts, sources, attribution, policy, or organizational authority. "
                f"{NTRO_AGENT_GUARDRAILS}"
            ),
            **common,
        ),
        "provenance_reviewer": Agent(
            role="Case Evidence and Provenance Reviewer",
            goal="Test every material claim against permitted memory and preserve source traceability.",
            backstory=(
                "You are a rigorous intelligence-quality reviewer. You downgrade confidence, "
                "flag unsupported claims, and require explicit caveats when provenance is weak. "
                f"{NTRO_AGENT_GUARDRAILS}"
            ),
            **common,
        ),
        "advisory_writer": Agent(
            role="NTRO Advisory Writer",
            goal="Produce a concise, actionable case advisory from reviewed information.",
            backstory=(
                "You write formal advisories for authorized NTRO personnel. "
                "You distinguish facts, assessments, impacts, recommendations, and unknowns. "
                f"{NTRO_AGENT_GUARDRAILS}"
            ),
            **common,
        ),
        "quality_critic": Agent(
            role="Advisory Quality Critic",
            goal="Reject unsupported, non-actionable, incomplete, or policy-inventing advisory drafts.",
            backstory=(
                "You are the final release gate. You verify structure, evidence linkage, confidence, "
                "classification handling, formal advisory style, and NTRO-specific framing before human review. "
                f"{NTRO_AGENT_GUARDRAILS}"
            ),
            **common,
        ),
    }
