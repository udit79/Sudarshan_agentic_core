"""CrewAI tasks for case-grounded LinkedIn post generation."""

from __future__ import annotations

from crewai import Agent, Task

from pipelines.advisory.schemas import EvidenceReview, IntelligenceBrief, QualityReview
from pipelines.common.memory_tools import TaskMemoryWriter
from pipelines.linkedin.schemas import LinkedInPostOutput


def build_tasks(agents: dict[str, Agent], writer: TaskMemoryWriter) -> dict[str, Task]:
    analysis = Task(
        description=(
            "Analyze the operation {query} using only the permitted memory context and the "
            "recall_sudarshan_memory tool. Extract confirmed facts, evidence, source references, and gaps. "
            "Do not invent public claims. Context:\n{memory_context}\n"
            "Pipeline options:\n{pipeline_options}\n"
            "Central prompt plan:\n{prompt_plan}"
        ),
        expected_output="A validated IntelligenceBrief JSON object.",
        agent=agents["case_analyst"],
        output_pydantic=IntelligenceBrief,
        callback=writer.callback("linkedin_case_analyst"),
    )
    review = Task(
        description=(
            "Review the case brief for provenance. Identify unsupported claims, weak sources, and caveats. "
            "Do not add facts. Return an EvidenceReview JSON object."
        ),
        expected_output="A validated EvidenceReview JSON object.",
        agent=agents["case_analyst"],
        context=[analysis],
        output_pydantic=EvidenceReview,
        callback=writer.callback("linkedin_evidence_review"),
    )
    output = Task(
        description=(
            "Write a professional LinkedIn post from the reviewed case information. It must be accurate, "
            "specific to the case, suitable for the stated audience, and within the schema. Do not expose "
            "restricted information, invent an official position, exaggerate certainty, mention agents or AI, "
            "or include internal workflow commentary. Use a useful title, concise post text, a clear call to "
            "action, source references, and caveats where needed. Apply the image policy in pipeline_options: "
            "always means include an image specification; never means image.strategy must be none; auto means "
            "decide internally whether a visual materially improves comprehension. When auto selects an image, "
            "choose the most suitable image type (photo, illustration, diagram, or infographic), include accurate "
            "alt text, and provide a concrete case-grounded generation prompt. The visual must be restrained and "
            "professional, with no flashy colors, sensational imagery, invented logos/seals, or decorative image "
            "added merely to fill space. Follow the central prompt plan where compatible "
            "with these rules:\n{prompt_plan}"
        ),
        expected_output="A validated LinkedInPostOutput JSON object.",
        agent=agents["post_writer"],
        context=[analysis, review],
        output_pydantic=LinkedInPostOutput,
        callback=writer.callback("linkedin_post_writer"),
    )
    quality = Task(
        description=(
            "Review the LinkedInPostOutput. Approve only when every material claim is supported, the draft is "
            "professional and audience-appropriate, no restricted details or invented authority appear, and it "
            "contains no AI/meta language. Return QualityReview JSON with precise revision issues if rejected."
        ),
        expected_output="A validated QualityReview JSON object.",
        agent=agents["quality_critic"],
        context=[output, review],
        output_pydantic=QualityReview,
        callback=writer.callback("linkedin_quality_critic"),
    )
    return {"analysis": analysis, "review": review, "output": output, "quality": quality}
