"""PPT pipeline package."""

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
from pipelines.ppt.repair import RepairApplicationError, apply_repair_patch, apply_repair_patches
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
    PresentationTheme,
    PresentationQualityReview,
    RepairPatch,
    SlideContent,
    SlideContentIR,
    SlideSpec,
    SlideTask,
    VisualIR,
)
from pipelines.ppt.source_workspace import DeckSourceWorkspace, EvidenceSourceBinding, write_deck_source_workspace
from pipelines.ppt.svg_contract import CanonicalSvgArtifact, write_canonical_svg
from pipelines.ppt.template_workspace import LayoutContract, PptTemplateContract, write_template_workspace
from pipelines.ppt.child_artifacts import ChildArtifactRef, SlideArtifactBundle, reconcile_slide_artifacts
from pipelines.ppt.visual_regression import compare_pptx_fixture, pptx_visual_signature, pptx_visual_snapshot

__all__ = [
    "PresentationFlow",
    "PresentationOutput",
    "PresentationTheme",
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
    "RepairApplicationError",
    "apply_repair_patch",
    "apply_repair_patches",
    "PresentationVerticalSlice",
    "PptMasterAdapter",
    "PptMasterAdapterError",
    "PptMasterConfig",
    "PptMasterExportResult",
    "DeckSourceWorkspace",
    "EvidenceSourceBinding",
    "write_deck_source_workspace",
    "CanonicalSvgArtifact",
    "write_canonical_svg",
    "LayoutContract",
    "PptTemplateContract",
    "write_template_workspace",
    "ChildArtifactRef",
    "SlideArtifactBundle",
    "reconcile_slide_artifacts",
    "compare_pptx_fixture",
    "pptx_visual_signature",
    "pptx_visual_snapshot",
]


def __getattr__(name: str):
    """Load the optional CrewAI-backed presentation flow on demand."""
    if name == "PresentationFlow":
        from pipelines.ppt.crew import PresentationFlow

        return PresentationFlow
    raise AttributeError(name)
