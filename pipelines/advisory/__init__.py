"""NTRO-specific advisory generation pipeline."""

from pipelines.advisory.artifact import AdvisoryArtifact, AdvisoryArtifactWriter, render_advisory
from pipelines.advisory.schemas import AdvisoryOutput

__all__ = ["AdvisoryArtifact", "AdvisoryArtifactWriter", "AdvisoryFlow", "AdvisoryOutput", "render_advisory"]


def __getattr__(name: str):
    """Load the optional CrewAI-backed advisory flow on demand."""
    if name == "AdvisoryFlow":
        from pipelines.advisory.crew import AdvisoryFlow

        return AdvisoryFlow
    raise AttributeError(name)
