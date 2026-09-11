"""PPT pipeline package."""

from pipelines.ppt.crew import PresentationFlow
from pipelines.ppt.flowchart import (
    FlowchartLayout,
    FlowchartRenderArtifact,
    flowchart_from_visual_ir,
    layout_flowchart,
    render_flowchart_pptx,
    render_flowchart_svg,
    validate_flowchart,
)
from pipelines.ppt.quality import (
    SourceMapEntry,
    VisualDiagnostic,
    VisualQualityReport,
    inspect_flowchart,
    inspect_flowchart_svg,
    repair_patches,
)
from pipelines.ppt.vertical import PresentationVerticalSlice
from pipelines.ppt.ppt_master_adapter import (
    PptMasterAdapter,
    PptMasterAdapterError,
    PptMasterConfig,
    PptMasterExportResult,
)
from pipelines.ppt.schemas import (
    DeckPlan,
    EvidenceBinding,
    FlowchartEdge,
    FlowchartNode,
    FlowchartSpec,
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
    "FlowchartNode",
    "FlowchartEdge",
    "FlowchartSpec",
    "LayoutBox",
    "VisualIR",
    "SlideContentIR",
    "SlideSpec",
    "SlideTask",
    "DeckPlan",
    "RepairPatch",
    "FlowchartLayout",
    "FlowchartRenderArtifact",
    "flowchart_from_visual_ir",
    "layout_flowchart",
    "render_flowchart_pptx",
    "render_flowchart_svg",
    "validate_flowchart",
    "SourceMapEntry",
    "VisualDiagnostic",
    "VisualQualityReport",
    "inspect_flowchart",
    "inspect_flowchart_svg",
    "repair_patches",
    "PresentationVerticalSlice",
    "PptMasterAdapter",
    "PptMasterAdapterError",
    "PptMasterConfig",
    "PptMasterExportResult",
]
