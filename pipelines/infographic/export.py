"""Fail-closed SVG/PNG export contract for infographic artifacts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field

from pipelines.common.visual_qa import inspect_visual_artifact
from pipelines.infographic.quality import inspect_svg


class InfographicExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_path: str = Field(min_length=1)
    format: Literal["svg", "png"] = "svg"
    renderer_version: str = Field(default="infographic.export@1", min_length=1)


class InfographicExportArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    format: Literal["svg", "png"]
    renderer_version: str = Field(min_length=1)
    quality: dict[str, object] = Field(default_factory=dict)


def export_infographic_artifact(
    svg_path: str | Path,
    request: InfographicExportRequest,
    *,
    required_text: Iterable[str] = (),
) -> InfographicExportArtifact:
    """Export a quality-gated SVG, or use an explicitly installed PNG converter."""

    source = Path(svg_path)
    source_report = inspect_svg(source, required_text=tuple(required_text))
    if not source_report.approved:
        raise ValueError("infographic SVG quality gate failed: " + "; ".join(source_report.issues))
    svg = source.read_text(encoding="utf-8")
    _reject_unsafe_svg(svg)
    destination = Path(request.output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if request.format == "svg":
        destination.write_text(svg, encoding="utf-8")
        report = source_report
    else:
        try:
            import cairosvg
        except ImportError as exc:
            raise RuntimeError("PNG export requires the explicitly installed cairosvg converter") from exc
        cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=str(destination))
        report = inspect_visual_artifact(destination, kind="png", renderer_version=request.renderer_version)
        if not report.approved:
            raise ValueError("infographic PNG quality gate failed: " + "; ".join(report.issues))
    return InfographicExportArtifact(
        path=str(destination),
        format=request.format,
        renderer_version=request.renderer_version,
        quality=report.model_dump(mode="json"),
    )


def _reject_unsafe_svg(svg: str) -> None:
    content = re.sub(r"xmlns(?::\w+)?\s*=\s*[\"']https?://[^\"']+[\"']", "", svg, flags=re.IGNORECASE)
    if re.search(r"<script\b|<foreignObject\b|javascript:|data:text/html|(?:href|src|url)\s*=\s*[\"']https?://|\son[a-z]+\s*=", content, re.IGNORECASE):
        raise ValueError("infographic export rejects executable, remote, or event-handler SVG content")


__all__ = ["InfographicExportArtifact", "InfographicExportRequest", "export_infographic_artifact"]
