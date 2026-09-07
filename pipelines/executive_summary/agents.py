"""CrewAI agents for case-grounded executive summary generation."""

from __future__ import annotations

from typing import Any

from crewai import Agent
from crewai.tools import BaseTool
from pipelines.common.model_routing import resolve_model


def build_agents(tools: list[BaseTool], *, llm: Any = None) -> dict[str, Agent]:
    common = {"verbose": False, "allow_delegation": False, "tools": tools}

    def agent_options(role: str) -> dict[str, Any]:
        return {**common, "llm": resolve_model(role, override=llm)}
    return {
        "case_analyst": Agent(
            role="Case Intelligence Analyst",
            goal="Extract the most decision-relevant, verified information from the case.",
            backstory=(
                "You produce evidence-linked analytical briefs. You distinguish fact from assessment and "
                "make uncertainty visible without adding unsupported information."
            ),
            **agent_options("executive_analyst"),
        ),
        "summary_writer": Agent(
            role="Executive Summary Writer",
            goal="Produce a concise decision-support summary for the intended reader.",
            backstory=(
                "You write clear, neutral executive summaries. You prioritize material findings, implications, "
                "actions, provenance, and gaps over narrative decoration."
            ),
            **agent_options("executive_writer"),
        ),
        "quality_critic": Agent(
            role="Executive Summary Quality Reviewer",
            goal="Ensure the summary is complete, evidence-linked, concise, and decision-useful.",
            backstory=(
                "You reject unsupported conclusions, missing caveats, invented policy, and any AI or workflow "
                "language that should not appear in the delivered summary."
            ),
            **agent_options("executive_quality"),
        ),
    }
