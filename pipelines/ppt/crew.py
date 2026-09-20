"""PPT generation Flow — subclasses TextTransformationFlow.

CLICKING WORD: 'MEMORY → SLIDES → PPTX FILE'

Flow steps (inherited from TextTransformationFlow):
  prepare_context → run_crew → validate_crew → route_validation
  → persist_output (writes KnowledgeUnit to Case memory + renders PPTX)
  → persist_failure

No human gate: the quality critic is the release gate.
The PPTX artifact is written to artifacts/presentations/.
"""

from __future__ import annotations

from typing import Any

from pipelines.common.text_generation import TextTransformationFlow
from pipelines.ppt.agents import build_agents
from pipelines.ppt.renderer import PresentationArtifact, render_presentation
from pipelines.ppt.presentation_quality import inspect_presentation
from pipelines.ppt.schemas import PresentationOutput, PresentationQualityReview, resolve_presentation_theme
from pipelines.ppt.tasks import build_tasks
from pipelines.orchestrator.contracts import RequestConstraints


class PresentationFlow(TextTransformationFlow):
    """Generate a case-grounded NTRO briefing presentation and render it as PPTX."""

    pipeline_name = "presentation"
    agent_factory = staticmethod(build_agents)
    task_factory = staticmethod(build_tasks)
    output_model = PresentationOutput
    quality_model = PresentationQualityReview

    # CrewAI Flow definition builder scans the concrete class namespace;
    # explicitly project decorated methods so they are discovered correctly.
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

    def prepare_quality_output(self, output: PresentationOutput) -> PresentationOutput:
        """Keep model output renderable when no validated custom template exists.

        The model may still return an arbitrary ``template_id`` even after the
        task instruction asks for the native renderer.  A custom template is
        only meaningful when a validated ``PptTemplateContract`` is supplied;
        otherwise the existing native renderer is the safe product contract.
        Preserve the slide content and normalize only the unsupported template
        selection before quality checks and artifact persistence.
        """

        if output.template_id != "native-default":
            return output.model_copy(update={"template_id": "native-default", "template_version": None})
        return output

    def quality_output_issues(self, output: PresentationOutput) -> list[str]:
        """Render and validate constraints during the quality gate for the repair loop."""
        raw_constraints = self._request().constraints
        constraints = RequestConstraints.model_validate(raw_constraints) if raw_constraints else None
        theme = resolve_presentation_theme(constraints)
        artifact: PresentationArtifact = render_presentation(output, theme=theme)
        quality = inspect_presentation(
            output, 
            rendered_artifacts=[artifact.path],
            constraints=constraints,
        )
        # TaskState already declares ``artifact`` as the durable hand-off
        # field.  CrewAI's runtime state rejects undeclared attributes such as
        # ``artifact_data`` during a real Flow execution.
        self.state.artifact = {
            "path": artifact.path,
            "slide_count": artifact.slide_count,
            "quality": quality.model_dump(mode="json"),
            "deck_manifest": artifact.deck_manifest,
        }
        if not quality.approved:
            return [f"[{i.severity.upper()}] {i.issue_code}: {i.message}" for i in quality.issues]
        return []

    def enrich_output(self, output: PresentationOutput) -> PresentationOutput:
        """Attach the validated rendering to the flow state."""
        from pipelines.orchestrator.cross_skill import build_child_plan

        child_plan = build_child_plan(
            "presentation.case-brief",
            output,
            parent_run_id=self.state.run_id,
            parent_node_id="presentation",
            requested_visuals=self._request().metadata.get("ppt_visuals"),
        )
        
        artifact_data = self.state.artifact or {}
        self.state.artifact = {
            **artifact_data,
            "child_plan": [item.model_dump(mode="json") for item in child_plan],
        }
        return output
