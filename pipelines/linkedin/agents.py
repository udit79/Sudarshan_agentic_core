"""CrewAI agents for case-grounded LinkedIn post generation."""

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
            role="Case Context Analyst",
            goal="Extract the verified, publishable substance from the supplied case information.",
            backstory=(
                "You separate confirmed information from interpretation. You use only permitted memory, "
                "preserve source references, and never invent facts or organizational positions."
            ),
            **common,
        ),
        "post_writer": Agent(
            role="Professional LinkedIn Communications Writer",
            goal="Turn reviewed case information into a clear, accurate, professional LinkedIn draft.",
            backstory=(
                "You write concise public-facing communication. You avoid sensationalism, confidential details, "
                "unsupported claims, model self-reference, and conversational filler."
            ),
            **common,
        ),
        "quality_critic": Agent(
            role="LinkedIn Content Quality Reviewer",
            goal="Reject posts that are unsupported, unsafe to publish, unclear, or outside the requested case.",
            backstory=(
                "You check factual grounding, audience fit, tone, source traceability, length, and disclosure "
                "of uncertainty before returning a draft to the frontend."
            ),
            **common,
        ),
    }
