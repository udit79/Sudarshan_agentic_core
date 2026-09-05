"""CrewAI agents for case-grounded AntV infographic syntax."""

from __future__ import annotations

import os
from typing import Any

from crewai import Agent
from crewai.tools import BaseTool


def build_agents(tools: list[BaseTool], *, llm: Any = None) -> dict[str, Agent]:
    common = {"verbose": False, "allow_delegation": False, "tools": tools}
    configured_llm = llm or os.getenv("CREWAI_MODEL")
    if configured_llm:
        common["llm"] = configured_llm
    return {
        "case_analyst": Agent(
            role="Case Visual-Content Analyst",
            goal="Extract the smallest set of verified facts that a visual can communicate clearly.",
            backstory=(
                "You identify relationships, sequences, comparisons, and hierarchies in case information. "
                "You preserve provenance and never invent facts, labels, statistics, or official insignia."
            ),
            **common,
        ),
        "syntax_writer": Agent(
            role="AntV Infographic Syntax Designer",
            goal="Create valid AntV infographic syntax that presents verified case information professionally.",
            backstory=(
                "You are an information designer using AntV Infographic's declarative syntax. You choose a "
                "structure that improves comprehension, keep text legible, and use restrained official styling."
            ),
            **common,
        ),
        "quality_critic": Agent(
            role="Infographic Quality and Provenance Reviewer",
            goal="Reject invalid syntax, misleading visuals, unsupported claims, and poor visual hierarchy.",
            backstory=(
                "You check syntax structure, source linkage, completeness, readability, and professional visual "
                "tone before the renderer is called."
            ),
            **common,
        ),
    }
