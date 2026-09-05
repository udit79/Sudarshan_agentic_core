"""CrewAI tasks for AntV infographic generation."""

from __future__ import annotations

from crewai import Agent, Task

from pipelines.advisory.schemas import EvidenceReview, IntelligenceBrief, QualityReview
from pipelines.common.memory_tools import TaskMemoryWriter
from pipelines.infographic.schemas import InfographicOutput


def build_tasks(agents: dict[str, Agent], writer: TaskMemoryWriter) -> dict[str, Task]:
    analysis = Task(
        description=(
            "Analyze the operation {query} using only permitted memory context and the "
            "recall_sudarshan_memory tool. Identify verified facts, relationships, sequences, comparisons, "
            "and gaps that a visual may communicate. Context:\n{memory_context}\n"
            "Central prompt plan:\n{prompt_plan}"
        ),
        expected_output="A validated IntelligenceBrief JSON object.",
        agent=agents["case_analyst"],
        output_pydantic=IntelligenceBrief,
        callback=writer.callback("infographic_case_analyst"),
    )
    review = Task(
        description=(
            "Review the visual-content brief for evidence support and provenance. Identify unsupported claims "
            "and required caveats. Do not add facts. Return EvidenceReview JSON."
        ),
        expected_output="A validated EvidenceReview JSON object.",
        agent=agents["case_analyst"],
        context=[analysis],
        output_pydantic=EvidenceReview,
        callback=writer.callback("infographic_evidence_review"),
    )
    output = Task(
        description=(
            "Create a complete InfographicOutput from the verified brief and evidence review. The syntax must "
            "use AntV Infographic's declarative syntax, begin with an infographic directive, and contain only "
            "case-grounded information. Choose the most useful structure: process, timeline, list, comparison, "
            "hierarchy, flow, or another suitable layout. Keep the visual clear and restrained: no flashy "
            "gradients, sensational imagery, decorative clutter, invented logos, seals, statistics, or labels. "
            "Do not expose restricted information. Include accessible alt text, evidence, references, confidence, "
            "and gaps. Do not mention agents, prompts, models, or workflow. "
            "Follow the central prompt plan where compatible with these rules:\n{prompt_plan}"
        ),
        expected_output="A validated InfographicOutput JSON object containing renderable AntV syntax.",
        agent=agents["syntax_writer"],
        context=[analysis, review],
        output_pydantic=InfographicOutput,
        callback=writer.callback("infographic_syntax_writer"),
    )
    quality = Task(
        description=(
            "Review the InfographicOutput before rendering. Check that the AntV syntax is structurally valid, "
            "the visual type fits the information, every material claim is supported, text remains legible, and "
            "the style is professional and restrained. Reject unsupported claims, invented official marks, "
            "confidential details, malformed syntax, unresolved placeholders, or AI/meta language. Return "
            "QualityReview JSON with precise revision issues if rejected."
        ),
        expected_output="A validated QualityReview JSON object.",
        agent=agents["quality_critic"],
        context=[output, review],
        output_pydantic=QualityReview,
        callback=writer.callback("infographic_quality_critic"),
    )
    return {"analysis": analysis, "review": review, "output": output, "quality": quality}
