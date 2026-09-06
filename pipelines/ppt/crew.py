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
from pipelines.ppt.schemas import PresentationOutput, PresentationQualityReview
from pipelines.ppt.tasks import build_tasks


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

    def enrich_output(self, output: PresentationOutput) -> PresentationOutput:
        """Render the validated output to a PPTX artifact before memory write-back."""
        artifact: PresentationArtifact = render_presentation(output)
        # Attach the artifact path into the flow state for the PipelineResponse
        self.state.artifact = {"path": artifact.path, "slide_count": artifact.slide_count}
        return output
