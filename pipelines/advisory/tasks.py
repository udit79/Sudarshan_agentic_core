"""CrewAI tasks for the NTRO case-advisory crew."""

from __future__ import annotations

from typing import Any

from crewai import Agent, Task

from pipelines.advisory.schemas import AdvisoryOutput, EvidenceReview, IntelligenceBrief, QualityReview
from pipelines.common.memory_tools import TaskMemoryWriter


def build_tasks(agents: dict[str, Agent], writer: TaskMemoryWriter) -> dict[str, Task]:
    """Build a sequential, typed crew with deterministic task callbacks."""

    intelligence = Task(
        description=(
            "Analyze the NTRO case-advisory operation {query}. Use only the injected permitted memory context "
            "and the recall_sudarshan_memory tool. Return confirmed facts, explicitly labeled assessments, "
            "entities, evidence items with source references/confidence, and intelligence gaps. "
            "Permitted memory context:\n{memory_context}"
        ),
        expected_output="A validated IntelligenceBrief JSON object.",
        agent=agents["intelligence_analyst"],
        output_pydantic=IntelligenceBrief,
        callback=writer.callback("intelligence_analyst"),
    )
    provenance = Task(
        description=(
            "Review the intelligence brief for provenance and evidentiary support. Reject claims not "
            "traceable to the supplied evidence or permitted memory. Identify unsupported claims, "
            "provenance issues, and mandatory caveats. Do not add new facts."
        ),
        expected_output="A validated EvidenceReview JSON object.",
        agent=agents["provenance_reviewer"],
        context=[intelligence],
        output_pydantic=EvidenceReview,
        callback=writer.callback("provenance_reviewer"),
    )
    advisory = Task(
        description=(
            "Write a formal NTRO case advisory using the intelligence brief and evidence review. "
            "The classification is {classification_level}; distribution is {distribution}. "
            "Use the exact AdvisoryOutput schema and include a subject, severity rating, overview, situation, "
            "assessment, impact analysis, observed patterns, recommendations, action items, evidence, "
            "references, handling instructions, confidence, gaps, and caveats. Keep fact/assessment boundaries "
            "explicit, link evidence to claims, make recommendations actionable, and never invent NTRO policy "
            "or response authority. Write like an official advisory: direct, neutral, precise, and free of "
            "AI self-reference, meta-commentary, filler, or conversational language."
        ),
        expected_output="A complete validated AdvisoryOutput JSON object.",
        agent=agents["advisory_writer"],
        context=[intelligence, provenance],
        output_pydantic=AdvisoryOutput,
        callback=writer.callback("advisory_writer"),
    )
    quality = Task(
        description=(
            "Critically inspect the proposed AdvisoryOutput. Check every section, evidence linkage, "
            "confidence statement, actionable recommendation, formal advisory style, and NTRO-specific framing. "
            "Reject AI self-reference, meta-commentary, unsupported official policy, invented contacts, and "
            "untraceable facts. Return a JSON "
            "object with approved=true only if release-ready. If false, list precise issues for retry."
        ),
        expected_output="A validated QualityReview JSON object.",
        agent=agents["quality_critic"],
        context=[advisory],
        output_pydantic=QualityReview,
        callback=writer.callback("quality_critic"),
    )
    return {
        "intelligence": intelligence,
        "provenance": provenance,
        "advisory": advisory,
        "quality": quality,
    }
