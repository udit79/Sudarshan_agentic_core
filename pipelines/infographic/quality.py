"""Deterministic quality checks for rendered infographic SVG artifacts.

This module owns the single SVG safety contract shared by both the quality
gate and the export layer.  The `_SVG_FORBIDDEN_PATTERN` regex and the
`SVG_SAFE_PRIMITIVES` constant are the canonical sources of truth; callers
must not maintain a parallel security list.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Typed renderer mode
# ---------------------------------------------------------------------------

RendererMode = Literal["native", "fallback", "syntax_only", "failed", "unknown"]

_NODE_MODE_MAP: dict[str, RendererMode] = {
    "antv": "native",
    "native": "native",
    "fallback": "fallback",
    "syntax_only": "syntax_only",
    "failed": "failed",
}

# Modes that may produce a delivered artifact (fallback only as degraded).
_DELIVERABLE_MODES: frozenset[RendererMode] = frozenset({"native", "fallback"})

# Modes that must never be marked approved=True in a quality report.
_NEVER_APPROVED_MODES: frozenset[RendererMode] = frozenset({"syntax_only", "failed", "unknown"})


def coerce_renderer_mode(raw: str | None) -> RendererMode:
    """Convert an external renderer string to a typed mode; unknown → 'unknown'."""
    if raw is None:
        return "unknown"
    return _NODE_MODE_MAP.get(str(raw).strip().lower(), "unknown")


# ---------------------------------------------------------------------------
# Shared SVG safety contract
# ---------------------------------------------------------------------------

# Forbidden patterns that must not appear in any delivered SVG, native or fallback.
_SVG_FORBIDDEN_PATTERN = re.compile(
    r"""
    <foreignObject\b          # HTML foreign-object embedding
    | <script\b               # Executable script tags
    | javascript:             # JavaScript URL protocol
    | data:text/html          # HTML data URLs
    | (?:href|src|url)\s*=\s*['"]https?://  # Remote asset URLs
    """,
    re.IGNORECASE | re.VERBOSE,
)

_SVG_EVENT_HANDLER_PATTERN = re.compile(r"\son[a-z]+\s*=", re.IGNORECASE)

# SVG primitive elements considered safe for Sudarshan output.
SVG_SAFE_PRIMITIVES = frozenset({
    "svg", "g", "rect", "circle", "ellipse", "line", "polyline", "polygon",
    "path", "text", "tspan", "title", "desc", "defs", "use", "symbol",
    "marker", "clipPath", "mask", "pattern", "linearGradient",
    "radialGradient", "stop", "image", "a", "style",
})


def validate_svg_safety(svg: str) -> list[str]:
    """Return a list of safety violations; empty means safe.

    This is the single shared validator for both the quality gate and the
    export layer (``svg_contract.py``).  Do not maintain a parallel list.
    """
    issues: list[str] = []
    # Strip XML namespace declarations before scanning so ``xmlns:xhtml=``
    # attributes don't accidentally absorb a real pattern match.
    content = re.sub(r'xmlns(?::\w+)?\s*=\s*["\'][^"\']*["\']', "", svg, flags=re.IGNORECASE)
    if _SVG_FORBIDDEN_PATTERN.search(content):
        issues.append("SVG contains forbidden executable or remote content (foreignObject, script, javascript:, remote URLs)")
    if _SVG_EVENT_HANDLER_PATTERN.search(svg):
        issues.append("SVG contains event-handler attributes (on*=)")
    return issues


# ---------------------------------------------------------------------------
# Palette paint-attribute validation
# ---------------------------------------------------------------------------

_PAINT_ATTRIBUTE_PATTERN = re.compile(
    r'(?:fill|stroke|color|stop-color|flood-color|lighting-color)'
    r'\s*[=:]\s*["\']?\s*'
    r'(#[0-9a-fA-F]{3,8}|rgb[^)]*\)|[a-zA-Z]+)'
    r'\s*["\']?',
    re.IGNORECASE,
)


def _extract_paint_values(svg: str) -> frozenset[str]:
    """Return all visible paint attribute values, normalised to lowercase hex."""
    raw = {m.group(1).strip() for m in _PAINT_ATTRIBUTE_PATTERN.finditer(svg)}
    normalised: set[str] = set()
    for value in raw:
        v = value.lower()
        if len(v) == 4 and v.startswith("#"):
            # Expand shorthand #rgb → #rrggbb
            v = "#" + "".join(c * 2 for c in v[1:])
        normalised.add(v)
    return frozenset(normalised)


def _check_palette(
    paint_values: frozenset[str],
    required_palette: Iterable[str],
    allowed_palette: Iterable[str] | None,
    issues: list[str],
) -> None:
    req = [p.lower() for p in required_palette]
    for token in req:
        t = token
        if len(t) == 4 and t.startswith("#"):
            t = "#" + "".join(c * 2 for c in t[1:])
        if t not in paint_values:
            issues.append(f"required theme color token is absent from visible paint attributes: {token}")

    if allowed_palette is not None:
        allowed = frozenset(p.lower() for p in allowed_palette)
        for value in paint_values:
            # Skip named values like 'none', 'inherit', 'transparent', 'currentColor'.
            if re.match(r"^[a-zA-Z]+$", value) and value not in {"white", "black"}:
                continue
            if value not in allowed:
                issues.append(f"visible paint color is outside the approved theme palette: {value}")


# ---------------------------------------------------------------------------
# Accessibility token validation
# ---------------------------------------------------------------------------

_ACCESSIBILITY_TOKENS = ("aria-label", "role", "title", "description")


def _check_accessibility(svg: str, issues: list[str], *, strict: bool = False) -> None:
    """Validate accessibility attributes and metadata."""
    has_role = bool(re.search(r'\brole\s*=\s*["\']img["\']', svg, re.IGNORECASE))
    has_labelledby = bool(re.search(r'\baria-labelledby\s*=', svg, re.IGNORECASE))
    has_aria = bool(re.search(r'\baria-label\s*=', svg, re.IGNORECASE))
    has_title = bool(re.search(r'<title\b', svg, re.IGNORECASE))
    has_desc = bool(re.search(r'<desc\b', svg, re.IGNORECASE))

    if strict:
        if not has_role:
            issues.append("SVG is missing role='img' attribute")
        if not has_labelledby:
            issues.append("SVG is missing aria-labelledby attribute")
        if not has_title:
            issues.append("SVG is missing <title> element")
        if not has_desc:
            issues.append("SVG is missing <desc> element")
    else:
        if not (has_aria or has_role or has_title):
            issues.append("SVG has no accessibility metadata (aria-label, role, or <title>)")


# ---------------------------------------------------------------------------
# Quality report
# ---------------------------------------------------------------------------

class SVGQualityReport(BaseModel):
    """Machine-readable checks used before an infographic is delivered."""

    model_config = ConfigDict(extra="forbid")

    approved: bool
    issues: list[str] = Field(default_factory=list)
    width: int | None = None
    height: int | None = None
    required_text: list[str] = Field(default_factory=list)
    renderer_mode: RendererMode = "unknown"
    renderer_warning: str | None = None
    degraded: bool = False
    foreignobject_present: bool = False
    operator_waiver_id: str | None = None


def inspect_svg(
    path: str | Path,
    *,
    required_text: tuple[str, ...] = (),
    required_palette: Iterable[str] = (),
    allowed_palette: Iterable[str] | None = None,
    renderer_mode: str | None = None,
    renderer_warning: str | None = None,
    check_accessibility: bool = True,
    strict_accessibility: bool = False,
    operator_waiver_id: str | None = None,
) -> SVGQualityReport:
    """Validate SVG render integrity.

    Uses the shared ``validate_svg_safety`` contract so the quality gate and
    the export layer enforce the same rules.
    """

    typed_mode = coerce_renderer_mode(renderer_mode)
    degraded = typed_mode == "fallback"
    issues: list[str] = []
    if isinstance(path, str) and path.strip().startswith("<svg"):
        content = path
    else:
        artifact = Path(path)

        if not artifact.is_file():
            return SVGQualityReport(
                approved=False,
                issues=["SVG artifact is missing"],
                required_text=list(required_text),
                renderer_mode=typed_mode,
                renderer_warning=renderer_warning,
                degraded=degraded,
                operator_waiver_id=operator_waiver_id,
            )

        content = artifact.read_text(encoding="utf-8")
    root = content.lstrip()

    # 1. SVG structural integrity
    if not re.match(r"(?:<\?[^>]*>\s*)*<svg\b", root):
        issues.append("artifact does not contain a valid SVG root")
    if not re.search(r"</svg>\s*$", content):
        issues.append("artifact has no closing SVG root")
    if not re.search(r"\b(width|viewBox)=", content):
        issues.append("artifact has no SVG dimensions")
    for bad_value in ("NaN", "undefined", "Infinity"):
        if bad_value in content:
            issues.append(f"artifact contains invalid geometry value: {bad_value}")

    # 2. Shared safety contract (foreignObject, script, remote URLs, event handlers)
    issues.extend(validate_svg_safety(content))
    foreignobject_present = bool(re.search(r"<foreignObject\b", content, re.IGNORECASE))

    # 3. Required visible text
    for value in required_text:
        if value not in content:
            issues.append(f"required visible text is missing: {value}")

    # 4. Palette validation against actual paint attributes
    paint_values = _extract_paint_values(content)
    _check_palette(paint_values, required_palette, allowed_palette, issues)

    # 5. Accessibility metadata
    if check_accessibility:
        _check_accessibility(content, issues, strict=strict_accessibility)

    # 6. Mode-based approval rules: syntax_only/failed are never approved.
    if renderer_mode is not None and typed_mode in _NEVER_APPROVED_MODES:
        issues.append(f"renderer_mode '{typed_mode}' cannot produce an approved artifact")

    # 7. Fallback release rule: fallback requires explicit operator waiver
    if typed_mode == "fallback" and not operator_waiver_id:
        issues.append("fallback renderer output requires an operator_waiver_id for release")

    width_match = re.search(r'\bwidth="(\d+)"', content)
    height_match = re.search(r'\bheight="(\d+)"', content)
    return SVGQualityReport(
        approved=not issues,
        issues=issues,
        width=int(width_match.group(1)) if width_match else None,
        height=int(height_match.group(1)) if height_match else None,
        required_text=list(required_text),
        renderer_mode=typed_mode,
        renderer_warning=renderer_warning,
        degraded=degraded,
        foreignobject_present=foreignobject_present,
        operator_waiver_id=operator_waiver_id,
    )


__all__ = [
    "SVGQualityReport",
    "RendererMode",
    "SVG_SAFE_PRIMITIVES",
    "coerce_renderer_mode",
    "inspect_svg",
    "validate_svg_safety",
]
