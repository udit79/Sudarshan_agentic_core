"""Deterministic AntV infographic generation Flow."""

from __future__ import annotations

from typing import Any

from pipelines.advisory.schemas import QualityReview
from pipelines.common.text_generation import TextTransformationFlow
from pipelines.infographic.agents import build_agents
from pipelines.infographic.quality import inspect_svg, _NEVER_APPROVED_MODES
from pipelines.infographic.renderer import AntVInfographicRenderer
from pipelines.infographic.schemas import InfographicOutput
from pipelines.infographic.tasks import build_tasks
from pipelines.infographic.waiver import OperatorWaiverStore


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
        operator_waiver_store: OperatorWaiverStore | None = None,
        progress_callback: Any = None,
    ) -> None:
        super().__init__(
            memory_manager,
            max_attempts=max_attempts,
            llm=llm,
            progress_callback=progress_callback,
        )
        self.renderer = renderer or AntVInfographicRenderer()
        self.operator_waiver_store = operator_waiver_store or OperatorWaiverStore()

    def enrich_output(self, output: Any) -> InfographicOutput:
        """Render valid syntax, retaining syntax-only output if Node is unavailable."""
        from pipelines.orchestrator.cross_skill import build_child_plan

        if not isinstance(output, InfographicOutput):
            return output
        try:
            operator_waiver_id = str(
                self._request().metadata.get("operator_waiver_id", "")
            ).strip() or None
            artifact_path = self.renderer(
                output.syntax,
                artifact_name=f"{output.infographic_id}-{self.state.run_id}",
            )
            quality_report = inspect_svg(
                artifact_path,
                required_text=(output.title,),
                renderer_mode=self.renderer.last_render_mode,
                renderer_warning=self.renderer.last_render_warning,
                operator_waiver_id=(
                    operator_waiver_id
                    if self.renderer.last_render_mode != "fallback"
                    else (
                        operator_waiver_id
                        if operator_waiver_id
                        and self.operator_waiver_store.verify_and_consume_waiver(
                            operator_waiver_id, run_id=self.state.run_id
                        )
                        else None
                    )
                ),
            )
            if not quality_report.approved:
                raise RuntimeError(f"Infographic SVG quality gate failed: {quality_report.issues}")

            # Typed mode enforcement: mode drives degraded flag, not a caveat string.
            typed_mode = quality_report.renderer_mode
            degraded = quality_report.degraded  # True for 'fallback'

            # syntax_only and failed must never be marked 'rendered'.
            if typed_mode in _NEVER_APPROVED_MODES:
                raise RuntimeError(
                    f"renderer_mode '{typed_mode}' cannot produce a rendered artifact"
                )

            caveats = list(output.caveats)
            if degraded:
                warning = quality_report.renderer_warning or "AntV SSR did not complete within its configured bound."
                caveats.append(f"Rendered with the deterministic local SVG fallback (degraded): {warning}")

            rendered = output.model_copy(update={
                "render_status": "rendered",
                "artifact_path": artifact_path,
                "render_error": None,
                "caveats": caveats,
            })
            self.state.artifact = {
                "path": artifact_path,
                "artifact_type": "svg",
                "renderer_mode": typed_mode,
                "degraded": degraded,
                "renderer_warning": quality_report.renderer_warning,
                "operator_waiver_id": quality_report.operator_waiver_id,
                "renderer_version": getattr(self.renderer, "renderer_version", "unknown"),
                "quality_report": quality_report.model_dump(mode="json"),
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
            # Any failure produces syntax_only — explicitly unapproved, never rendered.
            return output.model_copy(update={
                "render_status": "syntax_only",
                "artifact_path": None,
                "render_error": str(exc)[-2000:],
                "caveats": [*output.caveats, "SVG rendering was unavailable; AntV syntax is available for rendering."],
            })
