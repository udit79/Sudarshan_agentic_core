"""CrewAI tasks for NTRO briefing presentation generation."""

from __future__ import annotations

from crewai import Agent, Task

from pipelines.advisory.schemas import IntelligenceBrief
from pipelines.common.memory_tools import TaskMemoryWriter
from pipelines.ppt.schemas import PresentationOutput, PresentationQualityReview


def build_tasks(agents: dict[str, Agent], writer: TaskMemoryWriter) -> dict[str, Task]:
    """Build a sequential, typed crew with deterministic task callbacks."""

    analysis = Task(
        description=(
            "Analyze the NTRO briefing operation {query}. Use only the injected permitted "
            "memory context and the recall_sudarshan_memory tool. Return confirmed facts, "
            "explicitly labeled assessments, entities, evidence with source references and "
            "confidence scores, and intelligence gaps. This analysis will drive the slides.\n"
            "Permitted memory context:\n{memory_context}\n"
            "Central prompt plan:\n{prompt_plan}"
        ),
        expected_output="A validated IntelligenceBrief JSON object.",
        agent=agents["content_analyst"],
        output_pydantic=IntelligenceBrief,
        callback=writer.callback("ppt_content_analyst"),
    )

    output = Task(
        description=(
            "Write a complete NTRO briefing presentation from the intelligence analysis. "
            "The classification is {classification_level}; distribution is {distribution}. "
            "Use the exact PresentationOutput schema. Include: a descriptive title and subtitle, "
            "an agenda listing all slide topics, individual slides each with a focused title, "
            "3-6 bullet points, and informative speaker notes, a conclusion slide summarising "
            "the key message, key takeaways (max 5), evidence references, confidence statement, "
            "and intelligence gaps. "
            "Keep slides focused: one topic per slide. Bullets must be complete sentences or "
            "clear noun phrases — no fragments, no filler. Speaker notes must add context not "
            "visible on the slide. Never invent NTRO policy, response authority, or contacts. "
            "Write like a formal NTRO briefing: direct, neutral, precise. "
            "Follow the central prompt plan where compatible with these rules:\n{prompt_plan}"
        ),
        expected_output="A complete validated PresentationOutput JSON object.",
        agent=agents["presentation_writer"],
        context=[analysis],
        output_pydantic=PresentationOutput,
        callback=writer.callback("ppt_presentation_writer"),
    )

    quality = Task(
        description=(
            "Critically review the PresentationOutput. Check every slide for a clear title, "
            "focused and evidence-linked bullets, and informative speaker notes. "
            "Verify the agenda matches the slides. Check the conclusion and key takeaways. "
            "Reject placeholder text, unsupported claims, invented organizational authority, "
            "AI self-reference, meta-commentary, vague or unfocused slides, and missing gaps. "
            "Return PresentationQualityReview with approved=true only if release-ready. "
            "If false, list precise slide-level and structural issues for retry."
        ),
        expected_output="A validated PresentationQualityReview JSON object.",
        agent=agents["quality_critic"],
        context=[output],
        output_pydantic=PresentationQualityReview,
        callback=writer.callback("ppt_quality_critic"),
    )

    return {"analysis": analysis, "output": output, "quality": quality}
