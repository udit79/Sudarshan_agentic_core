"""Canonical, static SVG contract for presentation visual artifacts."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field

from pipelines.common.visual_qa import inspect_visual_artifact


class CanonicalSvgArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    source_ir_hash: str = Field(min_length=64, max_length=64)
    renderer_version: str = Field(min_length=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    quality: dict[str, object] = Field(default_factory=dict)


def write_canonical_svg(
    output_path: str | Path,
    svg: str,
    *,
    source_ir: object,
    renderer_version: str,
    required_text: Iterable[str] = (),
) -> CanonicalSvgArtifact:
    """Write and gate one static SVG without executable or remote content."""

    _validate_static_svg(svg)
    dimensions = _dimensions(svg)
    if dimensions is None:
        raise ValueError("canonical SVG must declare width and height")
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(svg, encoding="utf-8")
    report = inspect_visual_artifact(
        destination,
        kind="svg",
        required_text=tuple(required_text),
        renderer_version=renderer_version,
    )
    if not report.approved:
        raise ValueError("canonical SVG quality gate failed: " + "; ".join(report.issues))
    source_hash = hashlib.sha256(_stable_source(source_ir).encode("utf-8")).hexdigest()
    return CanonicalSvgArtifact(
        path=str(destination),
        source_ir_hash=source_hash,
        renderer_version=renderer_version,
        width=dimensions[0],
        height=dimensions[1],
        quality=report.model_dump(mode="json"),
    )


def _validate_static_svg(svg: str) -> None:
    if not isinstance(svg, str) or not re.match(r"^\s*<svg\b", svg):
        raise ValueError("canonical SVG must start with an SVG root")
    if not re.search(r"</svg>\s*$", svg):
        raise ValueError("canonical SVG must have a closing SVG root")
    content = re.sub(r"xmlns(?::\w+)?\s*=\s*[\"']https?://[^\"']+[\"']", "", svg, flags=re.IGNORECASE)
    if re.search(r"<script\b|<foreignObject\b|javascript:|data:text/html|(?:href|src|url)\s*=\s*[\"']https?://", content, re.IGNORECASE):
        raise ValueError("canonical SVG cannot contain executable or remote content")
    if re.search(r"\son[a-z]+\s*=", svg, re.IGNORECASE):
        raise ValueError("canonical SVG cannot contain event-handler attributes")


def _dimensions(svg: str) -> tuple[int, int] | None:
    width = re.search(r'\bwidth="(\d+)"', svg)
    height = re.search(r'\bheight="(\d+)"', svg)
    return (int(width.group(1)), int(height.group(1))) if width and height else None


def _stable_source(source_ir: object) -> str:
    if hasattr(source_ir, "model_dump_json"):
        return str(source_ir.model_dump_json())
    return repr(source_ir)


__all__ = ["CanonicalSvgArtifact", "write_canonical_svg"]
