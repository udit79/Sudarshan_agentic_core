"""Deterministic AntV infographic generation Flow."""

from __future__ import annotations

from typing import Any

from pipelines.advisory.schemas import QualityReview
from pipelines.common.text_generation import TextTransformationFlow
from pipelines.infographic.agents import build_agents
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
        from pipelines.orchestrator.cross_skill import build_child_plan


        if not isinstance(output, InfographicOutput):
            return output
        try:
            artifact_path = self.renderer(
                output.syntax,
                artifact_name=f"{output.infographic_id}-{self.state.run_id}",
            )
            caveats = list(output.caveats)
            if self.renderer.last_render_mode == "fallback":
                warning = self.renderer.last_render_warning or "AntV SSR did not complete within its configured bound."
                caveats.append(f"Rendered with the deterministic local SVG fallback: {warning}")
            rendered = output.model_copy(update={
                "render_status": "rendered",
                "artifact_path": artifact_path,
                "render_error": None,
                "caveats": caveats,
            })
            self.state.artifact = {
                "path": artifact_path,
                "artifact_type": "svg",
                "renderer_mode": self.renderer.last_render_mode,
                "child_plan": [
                    item.model_dump(mode="json")
                    for item in build_child_plan(
                        "infographic",
                        rendered,
                        parent_run_id=self.state.run_id,
                        parent_node_id="infographic",
                    )
                ],
            }
            return rendered
        except Exception as exc:
            return output.model_copy(update={
                "render_status": "syntax_only",
                "artifact_path": None,
                "render_error": str(exc)[-2000:],
                "caveats": [*output.caveats, "SVG rendering was unavailable; AntV syntax is available for rendering."],
            })
