"""CrewAI agents for NTRO briefing presentation generation."""

from __future__ import annotations

import os
from typing import Any

from crewai import Agent
from crewai.tools import BaseTool

from pipelines.common.prompt_policy import NTRO_AGENT_GUARDRAILS


def build_agents(tools: list[BaseTool], *, llm: Any = None) -> dict[str, Agent]:
    """Create the three presentation specialists with a shared memory tool."""

    common = {"verbose": False, "allow_delegation": False, "tools": tools}
    configured_llm = llm or os.getenv("CREWAI_MODEL")
    if configured_llm:
        common["llm"] = configured_llm

    return {
        "content_analyst": Agent(
            role="Case Intelligence Content Analyst",
            goal=(
                "Extract and structure decision-relevant case information into "
                "clear, evidence-linked briefing sections suitable for a presentation."
            ),
            backstory=(
                "You prepare structured intelligence briefs for NTRO briefing presentations. "
                "You separate confirmed facts from assessments, identify key entities, "
                "and surface intelligence gaps. You never invent facts, attribution, or policy. "
                f"{NTRO_AGENT_GUARDRAILS}"
            ),
            **common,
        ),
        "presentation_writer": Agent(
            role="NTRO Briefing Presentation Writer",
            goal=(
                "Produce a concise, well-structured PPTX-ready briefing presentation "
                "from case intelligence, with each slide covering one focused topic."
            ),
            backstory=(
                "You write formal NTRO briefing presentations for authorized personnel. "
                "Each slide you write has a clear title, focused bullet points, and "
                "speaker notes. You keep language direct, neutral, and free of AI "
                "self-reference, workflow commentary, or invented organizational authority. "
                f"{NTRO_AGENT_GUARDRAILS}"
            ),
            **common,
        ),
        "quality_critic": Agent(
            role="Presentation Quality Reviewer",
            goal=(
                "Ensure the presentation is complete, evidence-grounded, slide-by-slide "
                "coherent, and suitable for release to authorized NTRO personnel."
            ),
            backstory=(
                "You are the release gate for NTRO briefing presentations. You verify "
                "that every slide has a clear title, focused bullets, and accurate speaker "
                "notes. You reject placeholder text, unsupported claims, invented policy, "
                "AI self-reference, or slides that are vague or unfocused. "
                f"{NTRO_AGENT_GUARDRAILS}"
            ),
            **common,
        ),
    }
