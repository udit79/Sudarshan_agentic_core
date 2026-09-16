"""Deterministic structural/visual QA for presentation IR previews."""

from __future__ import annotations

from html import escape
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pipelines.ppt.flowchart import FlowchartLayout, LayoutNode
from pipelines.ppt.schemas import RepairPatch


class VisualDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    severity: Literal["info", "warning", "error"]
    message: str = Field(min_length=1)
    repairable: bool = True


class SourceMapEntry(BaseModel):
    """Safe source map from a rendered visual target to evidence IDs."""

    model_config = ConfigDict(extra="forbid")

    target_id: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)


class VisualQualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool
    diagnostics: list[VisualDiagnostic] = Field(default_factory=list)
    source_map: list[SourceMapEntry] = Field(default_factory=list)


def inspect_flowchart(layout: FlowchartLayout) -> VisualQualityReport:
    """Run deterministic checks before a model critic or release gate."""

    diagnostics: list[VisualDiagnostic] = []
    nodes = list(layout.nodes)
    by_id = layout.by_id

    for item in nodes:
        box = item.box
        if box.x < 0 or box.y < 0 or box.x + box.width > 1 or box.y + box.height > 1:
            diagnostics.append(
                VisualDiagnostic(
                    issue_id="flowchart.off-canvas",
                    target_id=item.node.node_id,
                    severity="error",
                    message="Node extends outside the normalized visual bounds.",
                )
            )
        # Approximate the available text width conservatively. The renderer
        # uses 16–18pt text, so long labels should be repaired before export.
        if len(item.node.label) > max(12, int(box.width * 120)):
            diagnostics.append(
                VisualDiagnostic(
                    issue_id="flowchart.text-overflow",
                    target_id=item.node.node_id,
                    severity="error",
                    message="Node label is too long for its allocated geometry.",
                )
            )

    for index, left in enumerate(nodes):
        for right in nodes[index + 1 :]:
            if _boxes_overlap(left, right):
                diagnostics.append(
                    VisualDiagnostic(
                        issue_id="flowchart.node-overlap",
                        target_id=f"{left.node.node_id}:{right.node.node_id}",
                        severity="error",
                        message="Two flowchart nodes overlap.",
                    )
                )

    for edge_index, edge in enumerate(layout.spec.edges):
        source = by_id[edge.source].box
        target = by_id[edge.target].box
        source_point, target_point = _edge_points_normalized(source, target)
        for other_index, other in enumerate(layout.spec.edges[:edge_index]):
            if edge.source in (other.source, other.target) or edge.target in (other.source, other.target):
                continue
            other_source, other_target = _edge_points_normalized(by_id[other.source].box, by_id[other.target].box)
            if _segments_intersect(source_point, target_point, other_source, other_target):
                diagnostics.append(
                    VisualDiagnostic(
                        issue_id="flowchart.edge-crossing",
                        target_id=f"edge-{edge_index}:edge-{other_index}",
                        severity="error",
                        message="Connector paths cross unrelated edges.",
                    )
                )

    source_map = [
        SourceMapEntry(
            target_id=item.node.node_id,
            evidence_ids=[binding.evidence_id for binding in item.node.evidence],
            x=item.box.x,
            y=item.box.y,
            width=item.box.width,
            height=item.box.height,
        )
        for item in nodes
    ]
    return VisualQualityReport(
        approved=not any(item.severity == "error" for item in diagnostics),
        diagnostics=diagnostics,
        source_map=source_map,
    )


def inspect_flowchart_svg(svg: str, *, required_text: tuple[str, ...] = ()) -> list[str]:
    """Fail closed on unsafe or inaccessible static flowchart SVG output."""

    issues: list[str] = []
    root = svg.lstrip()
    if not re.match(r"(?:<\?[^>]*>\s*)*<svg\b", root):
        issues.append("SVG output has no valid root")
    if not re.search(r"</svg>\s*$", svg):
        issues.append("SVG output has no closing root")
    if not re.search(r"\b(width|viewBox)=", svg):
        issues.append("SVG output has no dimensions")
    if not re.search(r"<title\b[^>]*>[^<]+</title>", svg):
        issues.append("SVG output is missing an accessible title")
    if not re.search(r"<desc\b[^>]*>[^<]+</desc>", svg):
        issues.append("SVG output is missing an accessible description")
    if re.search(r"<script\b|\bon[a-z]+\s*=|javascript:|data:text/html|@import\b", svg, re.IGNORECASE):
        issues.append("SVG output contains executable content")
    if re.search(r"(?:href|xlink:href)\s*=\s*['\"](?:https?:|//|data:)", svg, re.IGNORECASE):
        issues.append("SVG output contains a remote or data reference")
    for value in required_text:
        if value not in svg and escape(value) not in svg:
            issues.append(f"required visible label is missing: {value}")
    return issues


def repair_patches(report: VisualQualityReport) -> list[RepairPatch]:
    """Convert stable diagnostics into bounded, targeted repair requests."""

    operations = {
        "flowchart.node-overlap": "move",
        "flowchart.edge-crossing": "move",
        "flowchart.off-canvas": "move",
        "flowchart.text-overflow": "rewrite",
    }
    return [
        RepairPatch(
            issue_id=item.issue_id,
            target_id=item.target_id,
            operation=operations.get(item.issue_id, "replace"),
            value={"message": item.message},
        )
        for item in report.diagnostics
        if item.repairable
    ]


def _boxes_overlap(left: LayoutNode, right: LayoutNode) -> bool:
    return not (
        left.box.x + left.box.width <= right.box.x
        or right.box.x + right.box.width <= left.box.x
        or left.box.y + left.box.height <= right.box.y
        or right.box.y + right.box.height <= left.box.y
    )


def _edge_points_normalized(source, target):
    sx, sy = source.x + source.width / 2, source.y + source.height / 2
    tx, ty = target.x + target.width / 2, target.y + target.height / 2
    if abs(tx - sx) >= abs(ty - sy):
        return (
            ((source.x + source.width) if tx >= sx else source.x, sy),
            (target.x if tx >= sx else (target.x + target.width), ty),
        )
    return (
        (sx, (source.y + source.height) if ty >= sy else source.y),
        (tx, target.y if ty >= sy else (target.y + target.height)),
    )


def _segments_intersect(a, b, c, d) -> bool:
    def orientation(p, q, r):
        value = (q[1] - p[1]) * (r[0] - q[0]) - (q[0] - p[0]) * (r[1] - q[1])
        if abs(value) < 1e-9:
            return 0
        return 1 if value > 0 else 2

    return orientation(a, b, c) != orientation(a, b, d) and orientation(c, d, a) != orientation(c, d, b)


__all__ = [
    "SourceMapEntry",
    "VisualDiagnostic",
    "VisualQualityReport",
    "inspect_flowchart",
    "inspect_flowchart_svg",
    "repair_patches",
]
