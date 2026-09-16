"""CrewAI agents for case-grounded AntV infographic syntax."""

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
            role="Case Visual-Content Analyst",
            goal="Extract the smallest set of verified facts that a visual can communicate clearly.",
            backstory=(
                "You identify relationships, sequences, comparisons, and hierarchies in case information. "
                "You preserve provenance and never invent facts, labels, statistics, or official insignia. "
                f"{NTRO_AGENT_GUARDRAILS}"
            ),
            **common,
        ),
        "syntax_writer": Agent(
            role="AntV Infographic Syntax Designer",
            goal="Create valid AntV infographic syntax that presents verified case information professionally.",
            backstory=(
                "You are an information designer using AntV Infographic's declarative syntax. You choose a "
                "structure that improves comprehension, keep text legible, and use restrained official styling "
                "(the Indian Government color palette). You must support and retain bilingual (English/Hindi) "
                "labels from the case information if present. "
                f"{NTRO_AGENT_GUARDRAILS}"
            ),
            **common,
        ),
        "quality_critic": Agent(
            role="Infographic Quality and Provenance Reviewer",
            goal="Reject invalid syntax, misleading visuals, unsupported claims, and poor visual hierarchy.",
            backstory=(
                "You check syntax structure, source linkage, completeness, readability, and professional visual "
                "tone before the renderer is called. "
                f"{NTRO_AGENT_GUARDRAILS}"
            ),
            **common,
        ),
    }
