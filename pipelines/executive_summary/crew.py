"""Deterministic executive-summary generation Flow."""

from __future__ import annotations

from typing import Any

from pipelines.advisory.schemas import QualityReview
from pipelines.common.text_generation import TextTransformationFlow
from pipelines.executive_summary.agents import build_agents
from pipelines.executive_summary.schemas import ExecutiveSummaryOutput
from pipelines.executive_summary.tasks import build_tasks


class ExecutiveSummaryFlow(TextTransformationFlow):
    """Generate and validate a case-grounded executive summary."""

    pipeline_name = "executive_summary"
    agent_factory = staticmethod(build_agents)
    task_factory = staticmethod(build_tasks)
    output_model = ExecutiveSummaryOutput
    quality_model = QualityReview

    # CrewAI's Flow definition builder scans the concrete class namespace;
    # explicitly project the decorated methods onto each public Flow class.
    prepare_context = TextTransformationFlow.prepare_context
    run_crew = TextTransformationFlow.run_crew
    retry_crew = TextTransformationFlow.retry_crew
    validate_crew = TextTransformationFlow.validate_crew
    route_validation = TextTransformationFlow.route_validation
    persist_output = TextTransformationFlow.persist_output
    persist_failure = TextTransformationFlow.persist_failure

    def __init__(
        self,
        memory_manager: Any,
        *,
        max_attempts: int = 2,
        llm: Any = None,
        progress_callback: Any = None,
    ) -> None:
        super().__init__(
            memory_manager,
            max_attempts=max_attempts,
            llm=llm,
            progress_callback=progress_callback,
        )
