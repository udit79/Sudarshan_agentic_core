"""Deterministic AntV infographic generation Flow."""

from __future__ import annotations

from typing import Any

from pipelines.advisory.schemas import QualityReview
from pipelines.common.text_generation import TextTransformationFlow
from pipelines.infographic.agents import build_agents
from pipelines.infographic.normalization import normalize_infographic_output, repairable_quality_review
from pipelines.infographic.renderer import AntVInfographicRenderer
from pipelines.infographic.schemas import InfographicOutput
from pipelines.infographic.tasks import build_tasks


class InfographicFlow(TextTransformationFlow):
    """Generate, validate, and render a case-grounded AntV infographic."""

    pipeline_name = "infographic"
    # A rejected but schema-valid AntV draft is still useful for local
    # demonstration and debugging. It is rendered only as a failed draft;
    # it is never written back as approved case output.
    render_failed_draft = True
    agent_factory = staticmethod(build_agents)
    task_factory = staticmethod(build_tasks)
    output_model = InfographicOutput
    quality_model = QualityReview

    # CrewAI's Flow definition builder scans the concrete class namespace.
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
        renderer: AntVInfographicRenderer | None = None,
        progress_callback: Any = None,
    ) -> None:
        super().__init__(
            memory_manager,
            max_attempts=max_attempts,
            llm=llm,
            progress_callback=progress_callback,
        )
        self.renderer = renderer or AntVInfographicRenderer()

    def enrich_output(self, output: Any) -> InfographicOutput:
        """Render valid syntax, retaining syntax-only output if Node is unavailable."""

        if not isinstance(output, InfographicOutput):
            return output
        try:
            artifact_path = self.renderer(
                output.syntax,
                artifact_name=f"{output.infographic_id}-{self.state.run_id}",
            )
            rendered = output.model_copy(update={
                "render_status": "rendered",
                "artifact_path": artifact_path,
                "render_error": None,
            })
            self.state.artifact = {"path": artifact_path, "artifact_type": "svg"}
            return rendered
        except Exception as exc:
            return output.model_copy(update={
                "render_status": "syntax_only",
                "artifact_path": None,
                "render_error": str(exc)[-2000:],
                "caveats": [*output.caveats, "SVG rendering was unavailable; AntV syntax is available for rendering."],
            })

    def normalize_output_for_validation(self, output: Any) -> InfographicOutput:
        if not isinstance(output, InfographicOutput):
            return output
        return normalize_infographic_output(output, query=self.state.query)

    def repair_quality_review(self, output: Any, quality: Any) -> Any:
        if isinstance(output, InfographicOutput) and isinstance(quality, QualityReview):
            return repairable_quality_review(output, quality)
        return quality
