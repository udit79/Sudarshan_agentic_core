"""CrewAI agents for case-grounded LinkedIn post generation."""

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
            role="Case Context Analyst",
            goal="Extract the verified, publishable substance from the supplied case information.",
            backstory=(
                "You separate confirmed information from interpretation. You use only permitted memory, "
                "preserve source references, and never invent facts or organizational positions."
            ),
            **agent_options("linkedin_analyst"),
        ),
        "post_writer": Agent(
            role="Professional LinkedIn Communications Writer",
            goal="Turn reviewed case information into a clear, accurate, professional LinkedIn draft.",
            backstory=(
                "You write concise public-facing communication. You avoid sensationalism, confidential details, "
                "unsupported claims, model self-reference, and conversational filler."
            ),
            **agent_options("linkedin_writer"),
        ),
        "quality_critic": Agent(
            role="LinkedIn Content Quality Reviewer",
            goal="Reject posts that are unsupported, unsafe to publish, unclear, or outside the requested case.",
            backstory=(
                "You check factual grounding, audience fit, tone, source traceability, length, and disclosure "
                "of uncertainty before returning a draft to the frontend."
            ),
            **agent_options("linkedin_quality"),
        ),
    }
