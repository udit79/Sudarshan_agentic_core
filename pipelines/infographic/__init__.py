"""Case-grounded infographic generation and rendering pipeline."""

from pipelines.infographic.renderer import AntVInfographicRenderer
from pipelines.infographic.schemas import InfographicOutput
from pipelines.infographic.schemas import DiagramEdge, DiagramIR, DiagramNode, InfographicBlock, InfographicIR
from pipelines.infographic.normalization import normalize_infographic_output
from pipelines.infographic.ir import diagram_ir_from_output, infographic_ir_from_output, infographic_ir_to_syntax
from pipelines.infographic.quality import SVGQualityReport, inspect_svg
from pipelines.infographic.templates import (
    InfographicTemplate,
    InfographicTemplateSelection,
    InfographicTheme,
    get_infographic_theme,
    infographic_theme_manifest,
    infographic_template_registry,
    infographic_theme_registry,
    select_infographic_template,
)
from pipelines.infographic.structures import (
    InfographicStructure,
    StructureEdge,
    StructureNode,
    compile_infographic_structure,
)
from pipelines.infographic.export import InfographicExportArtifact, InfographicExportRequest, export_infographic_artifact
from pipelines.infographic.visual_regression import SVGRegressionResult, compare_svg_fixture, svg_regression_hash

__all__ = [
    "AntVInfographicRenderer",
    "InfographicFlow",
    "InfographicOutput",
    "InfographicBlock",
    "InfographicIR",
    "DiagramNode",
    "DiagramEdge",
    "DiagramIR",
    "normalize_infographic_output",
    "diagram_ir_from_output",
    "infographic_ir_from_output",
    "infographic_ir_to_syntax",
    "SVGQualityReport",
    "inspect_svg",
    "InfographicTemplate",
    "InfographicTemplateSelection",
    "InfographicTheme",
    "get_infographic_theme",
    "infographic_theme_manifest",
    "infographic_template_registry",
    "infographic_theme_registry",
    "select_infographic_template",
    "InfographicStructure",
    "StructureEdge",
    "StructureNode",
    "compile_infographic_structure",
    "InfographicExportArtifact",
    "InfographicExportRequest",
    "export_infographic_artifact",
    "SVGRegressionResult",
    "compare_svg_fixture",
    "svg_regression_hash",
]


def __getattr__(name: str):
    """Load the CrewAI-backed flow only when it is actually requested.

    Deterministic rendering and quality helpers are usable without the optional
    generation runtime. Keeping this import lazy lets artifact checks run in
    lightweight environments while preserving ``from pipelines.infographic
    import InfographicFlow`` for full pipeline deployments.
    """
    if name == "InfographicFlow":
        from pipelines.infographic.crew import InfographicFlow

        return InfographicFlow
    raise AttributeError(name)
