"""Safe diagram export contracts built on the existing native renderer."""

from __future__ import annotations

import hashlib
import json
from html import escape
from pathlib import Path
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pipelines.common.visual_qa import inspect_visual_artifact
from pipelines.diagram.family import DiagramSpec, compile_flowchart_spec, inspect_diagram
from pipelines.ppt.flowchart import render_flowchart_svg
from pipelines.ppt.quality import inspect_flowchart_svg
from pipelines.diagram.style import get_style_profile, validate_style_profile


class DiagramExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_path: str = Field(min_length=1)
    format: Literal["html", "svg"] = "svg"
    renderer_version: str = "diagram.native-svg@1"


class DiagramArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    format: Literal["html", "svg"]
    source_ir_hash: str = Field(min_length=64, max_length=64)
    renderer_version: str = Field(min_length=1)
    quality: dict[str, object] = Field(default_factory=dict)


def export_diagram(spec: DiagramSpec, request: DiagramExportRequest) -> DiagramArtifact:
    """Compile one validated graph to a safe HTML or SVG artifact."""

    issues = inspect_diagram(spec)
    if issues:
        raise ValueError("diagram quality gate failed: " + "; ".join(issues))
    profile = get_style_profile(spec.style_profile)
    style_issues = validate_style_profile({**profile, **spec.style_tokens})
    if style_issues:
        raise ValueError("diagram style gate failed: " + "; ".join(style_issues))
    graph = compile_flowchart_spec(spec)
    svg = render_flowchart_svg(graph)
    svg_issues = inspect_flowchart_svg(svg, required_text=(spec.diagram_id,))
    if svg_issues:
        raise ValueError("diagram SVG quality gate failed: " + "; ".join(svg_issues))
    if request.format == "html":
        content = _html_document(spec, svg)
    else:
        content = svg
    destination = Path(request.output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding="utf-8")
    quality = inspect_visual_artifact(destination, kind="svg" if request.format == "svg" else "other", required_text=(spec.diagram_id,))
    if not quality.approved:
        raise ValueError("diagram artifact quality gate failed: " + "; ".join(quality.issues))
    source_hash = _source_hash(spec)
    return DiagramArtifact(
        artifact_id=f"diagram-{source_hash[:16]}",
        path=str(destination),
        format=request.format,
        source_ir_hash=source_hash,
        renderer_version=request.renderer_version,
        quality=quality.model_dump(mode="json"),
    )


def _source_hash(spec: DiagramSpec) -> str:
    payload = json.dumps(spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _html_document(spec: DiagramSpec, svg: str) -> str:
    title = spec.accessibility.title if spec.accessibility else spec.title
    description = spec.accessibility.description if spec.accessibility else f"{spec.kind} diagram."
    svg = svg.replace(
        '<svg ',
        '<svg role="img" aria-labelledby="diagram-title diagram-desc" ',
        1,
    )
    svg = re.sub(r"<title>.*?</title>", f"<title id=\"diagram-title\">{escape(title)}</title>", svg, count=1, flags=re.DOTALL)
    svg = re.sub(r"<desc>.*?</desc>", f"<desc id=\"diagram-desc\">{escape(description)}</desc>", svg, count=1, flags=re.DOTALL)
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<title>{escape(title)}</title></head><body>{svg}</body></html>"
    )


__all__ = ["DiagramArtifact", "DiagramExportRequest", "export_diagram"]
