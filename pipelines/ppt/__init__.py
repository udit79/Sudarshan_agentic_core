"""PPT pipeline package."""

from pipelines.ppt.crew import PresentationFlow
from pipelines.ppt.schemas import (
    DeckPlan,
    EvidenceBinding,
    LayoutBox,
    PresentationOutput,
    PresentationQualityReview,
    RepairPatch,
    SlideContent,
    SlideContentIR,
    SlideSpec,
    SlideTask,
    VisualIR,
)

__all__ = [
    "PresentationFlow",
    "PresentationOutput",
    "PresentationQualityReview",
    "SlideContent",
    "EvidenceBinding",
    "LayoutBox",
    "VisualIR",
    "SlideContentIR",
    "SlideSpec",
    "SlideTask",
    "DeckPlan",
    "RepairPatch",
]
