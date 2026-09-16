"""CrewAI agents for case-grounded executive summary generation."""

from __future__ import annotations

from typing import Any

from crewai import Agent
from crewai.tools import BaseTool

from pipelines.common.prompt_policy import NTRO_AGENT_GUARDRAILS
from integrations.providers.router import ProviderRouter


def build_agents(tools: list[BaseTool], *, llm: Any = None) -> dict[str, Agent]:
    common = {"verbose": False, "allow_delegation": False, "tools": tools}
    configured_llm = ProviderRouter.configured_model("text", llm)
    if configured_llm:
        common["llm"] = configured_llm
    return {
        "case_analyst": Agent(
            role="Case Intelligence Analyst",
            goal="Extract the most decision-relevant, verified information from the case.",
            backstory=(
                "You produce evidence-linked analytical briefs. You distinguish fact from assessment and "
                "make uncertainty visible without adding unsupported information. "
                f"{NTRO_AGENT_GUARDRAILS}"
            ),
            **common,
        ),
        "summary_writer": Agent(
            role="Executive Summary Writer",
            goal="Produce a concise decision-support summary for the intended reader.",
            backstory=(
                "You write clear, neutral executive summaries. You prioritize material findings, implications, "
                "actions, provenance, and gaps over narrative decoration. "
                f"{NTRO_AGENT_GUARDRAILS}"
            ),
            **common,
        ),
        "quality_critic": Agent(
            role="Executive Summary Quality Reviewer",
            goal="Ensure the summary is complete, evidence-linked, concise, and decision-useful.",
            backstory=(
                "You reject unsupported conclusions, missing caveats, invented policy, and any AI or workflow "
                "language that should not appear in the delivered summary. "
                f"{NTRO_AGENT_GUARDRAILS}"
            ),
            **common,
        ),
    }
