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
            "Central prompt plan:\n{prompt_plan}\n"
            "Treat classification, distribution, audience, and requested deliverables as administrative "
            "metadata. They are not source evidence and must not be converted into factual visual claims."
        ),
        expected_output="A validated IntelligenceBrief JSON object.",
        agent=agents["case_analyst"],
        output_pydantic=IntelligenceBrief,
        callback=writer.callback("infographic_case_analyst"),
    )
    review = Task(
        description=(
            "Review the visual-content brief for evidence support and provenance. Identify unsupported claims "
            "and required caveats. Distinguish source facts from analytical judgments and delivery metadata. "
            "Do not add facts. Return EvidenceReview JSON."
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
            "case-grounded information. Choose the structure that matches the information: use process, "
            "timeline, list, comparison, or flow for sectional/status content; use hierarchy only for a real "
            "parent-child structure. Keep the visual clear and restrained: no flashy "
            "gradients, sensational imagery, decorative clutter, invented logos, seals, statistics, or labels. "
            "Enforce the Government of India / NTRO color palette. You must preserve bilingual (English/Hindi) "
            "labels if they appear in the source context. "
            "Use parser-safe ASCII punctuation in syntax values. Keep the title and alt text no stronger than "
            "the evidence; do not infer a flood, emergency, authority, or event from an ambiguous source title. "
            "If a source title contains a stronger event label than the verified facts, use a neutral display title "
            "and retain the original title only as a quoted source reference. "
            "Put classification and distribution only in a clearly labeled metadata/header area, never in the "
            "evidence or as a source-derived claim. Make visible wording consistent with alt text. Include "
            "accessible alt text, evidence, references, confidence, and gaps. Do not mention agents, prompts, "
            "models, or workflow. Use a compact renderer-safe canvas (prefer 1200x675), keep every footer inside "
            "the canvas, avoid dense paragraphs, and use readable body text (at least 16px where the syntax "
            "supports typography settings). If this is a retry, resolve every issue in the prior quality-gate "
            "feedback below rather than repeating the rejected draft:\n{quality_feedback}\n"
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
            "the style is professional and restrained using the NTRO color palette. Hindi labels must be correctly "
            "preserved. Treat classification and distribution as administrative metadata only; do not reject a "
            "clearly separated metadata/header marking merely because it is not source evidence. Reject "
            "unsupported claims, invented official marks, "
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
