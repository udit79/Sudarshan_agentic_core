"""NTRO-specific, case-advisory CrewAI agent definitions."""

from __future__ import annotations

from typing import Any

from crewai import Agent
from crewai.tools import BaseTool
from pipelines.common.model_routing import resolve_model


def build_agents(tools: list[BaseTool], *, llm: Any = None) -> dict[str, Agent]:
    """Create the four advisory specialists with a shared, narrow memory tool."""

    common = {
        "verbose": False,
        "allow_delegation": False,
        "tools": tools,
    }

    def agent_options(role: str) -> dict[str, Any]:
        return {**common, "llm": resolve_model(role, override=llm)}

    return {
        "intelligence_analyst": Agent(
            role="NTRO Case Intelligence Analyst",
            goal="Separate confirmed case information from analysis and identify information gaps.",
            backstory=(
                "You prepare defensible case assessments for an NTRO context. "
                "You never invent facts, sources, attribution, policy, or organizational authority."
            ),
            **agent_options("advisory_intelligence"),
        ),
        "provenance_reviewer": Agent(
            role="Case Evidence and Provenance Reviewer",
            goal="Test every material claim against permitted memory and preserve source traceability.",
            backstory=(
                "You are a rigorous intelligence-quality reviewer. You downgrade confidence, "
                "flag unsupported claims, and require explicit caveats when provenance is weak."
            ),
            **agent_options("advisory_provenance"),
        ),
        "advisory_writer": Agent(
            role="NTRO Advisory Writer",
            goal="Produce a concise, actionable case advisory from reviewed information.",
            backstory=(
                "You write formal advisories for authorized NTRO personnel. "
                "You distinguish facts, assessments, impacts, recommendations, and unknowns."
            ),
            **agent_options("advisory_writer"),
        ),
        "quality_critic": Agent(
            role="Advisory Quality Critic",
            goal="Reject unsupported, non-actionable, incomplete, or policy-inventing advisory drafts.",
            backstory=(
                "You are the final release gate. You verify structure, evidence linkage, confidence, "
                "classification handling, formal advisory style, and NTRO-specific framing before human review."
            ),
            **agent_options("advisory_quality"),
        ),
    }
