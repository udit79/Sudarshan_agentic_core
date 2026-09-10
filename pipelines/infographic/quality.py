"""Deterministic quality checks for rendered infographic SVG artifacts."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class SVGQualityReport(BaseModel):
    """Machine-readable checks used before an infographic is delivered."""

    model_config = ConfigDict(extra="forbid")

    approved: bool
    issues: list[str] = Field(default_factory=list)
    width: int | None = None
    height: int | None = None
    required_text: list[str] = Field(default_factory=list)
    renderer_mode: str | None = None
    renderer_warning: str | None = None


def inspect_svg(
    path: str | Path,
    *,
    required_text: tuple[str, ...] = (),
    renderer_mode: str | None = None,
    renderer_warning: str | None = None,
) -> SVGQualityReport:
    """Validate basic render integrity without interpreting generated claims."""

    artifact = Path(path)
    issues: list[str] = []
    if not artifact.is_file():
        return SVGQualityReport(
            approved=False,
            issues=["SVG artifact is missing"],
            required_text=list(required_text),
            renderer_mode=renderer_mode,
            renderer_warning=renderer_warning,
        )

    content = artifact.read_text(encoding="utf-8")
    root = content.lstrip()
    if not re.match(r"(?:<\?[^>]*>\s*)*<svg\b", root):
        issues.append("artifact does not contain a valid SVG root")
    if not re.search(r"</svg>\s*$", content):
        issues.append("artifact has no closing SVG root")
    if not re.search(r"\b(width|viewBox)=", content):
        issues.append("artifact has no SVG dimensions")
    for bad_value in ("NaN", "undefined", "Infinity"):
        if bad_value in content:
            issues.append(f"artifact contains invalid geometry value: {bad_value}")
    for value in required_text:
        if value not in content:
            issues.append(f"required visible text is missing: {value}")

    width_match = re.search(r'\bwidth="(\d+)"', content)
    height_match = re.search(r'\bheight="(\d+)"', content)
    return SVGQualityReport(
        approved=not issues,
        issues=issues,
        width=int(width_match.group(1)) if width_match else None,
        height=int(height_match.group(1)) if height_match else None,
        required_text=list(required_text),
        renderer_mode=renderer_mode,
        renderer_warning=renderer_warning,
    )
