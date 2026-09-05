"""CrewAI tasks for case-grounded executive summary generation."""

from __future__ import annotations

from crewai import Agent, Task

from pipelines.advisory.schemas import EvidenceReview, IntelligenceBrief, QualityReview
from pipelines.common.memory_tools import TaskMemoryWriter
from pipelines.executive_summary.schemas import ExecutiveSummaryOutput


def build_tasks(agents: dict[str, Agent], writer: TaskMemoryWriter) -> dict[str, Task]:
    analysis = Task(
        description=(
            "Analyze the operation {query} using only permitted memory context and the "
            "recall_sudarshan_memory tool. Identify confirmed facts, decision-relevant assessments, evidence, "
            "sources, and gaps. Context:\n{memory_context}\n"
            "Central prompt plan:\n{prompt_plan}"
        ),
        expected_output="A validated IntelligenceBrief JSON object.",
        agent=agents["case_analyst"],
        output_pydantic=IntelligenceBrief,
        callback=writer.callback("executive_case_analyst"),
    )
    review = Task(
        description=(
            "Review the intelligence brief for provenance and support. Flag unsupported claims and required "
            "caveats. Do not add facts. Return EvidenceReview JSON."
        ),
        expected_output="A validated EvidenceReview JSON object.",
        agent=agents["case_analyst"],
        context=[analysis],
        output_pydantic=EvidenceReview,
        callback=writer.callback("executive_evidence_review"),
    )
    output = Task(
        description=(
            "Write an executive summary for the case from the intelligence brief and evidence review. Include "
            "the most important findings, implications, recommended actions, evidence references, confidence, "
            "and intelligence gaps. Keep it concise, neutral, case-specific, and free of AI self-reference, "
            "workflow commentary, unsupported authority, or invented facts. "
            "Follow the central prompt plan where compatible with these rules:\n{prompt_plan}"
        ),
        expected_output="A validated ExecutiveSummaryOutput JSON object.",
        agent=agents["summary_writer"],
        context=[analysis, review],
        output_pydantic=ExecutiveSummaryOutput,
        callback=writer.callback("executive_summary_writer"),
    )
    quality = Task(
        description=(
            "Review the ExecutiveSummaryOutput. Approve only if it is decision-useful, evidence-linked, "
            "complete, concise, and free of unsupported claims, invented policy, AI language, and unresolved "
            "placeholders. Return QualityReview JSON with precise issues if rejected."
        ),
        expected_output="A validated QualityReview JSON object.",
        agent=agents["quality_critic"],
        context=[output, review],
        output_pydantic=QualityReview,
        callback=writer.callback("executive_quality_critic"),
    )
    return {"analysis": analysis, "review": review, "output": output, "quality": quality}
