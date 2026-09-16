"""NP-07 renderer contract tests.

Covers all acceptance criteria from next-plan.md NP-07:
- Native vs fallback mode is asserted, never silent
- Fallback SVG passes the same safe-export rules as native SVG
- foreignObject is rejected in both native and fallback paths
- syntax_only cannot produce a rendered artifact
- Palette validation uses actual paint attributes, not raw token presence
- Accessibility metadata is checked
- Timeout budget validation prevents invalid configurations
- Unknown renderer modes fail closed
- Artifact metadata includes degraded=True for fallback
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pipelines.infographic.quality import (
    SVGQualityReport,
    RendererMode,
    _NEVER_APPROVED_MODES,
    _DELIVERABLE_MODES,
    coerce_renderer_mode,
    inspect_svg,
    validate_svg_safety,
    _extract_paint_values,
)
from pipelines.infographic.renderer import (
    AntVInfographicRenderer,
    FALLBACK_BUDGET_SECONDS,
    MINIMUM_TIMEOUT_SECONDS,
    SHUTDOWN_HEADROOM_SECONDS,
)
from pipelines.common.renderers import default_renderer_registry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NTRO_THEME = {
    "colorBg": "#F8FAFC",
    "colorPrimary": "#1E3A8A",
    "accent": "#38BDF8",
    "text": "#0F172A",
}

_VALID_NATIVE_SVG = textwrap.dedent("""\
    <svg xmlns="http://www.w3.org/2000/svg" width="1200" height="675" viewBox="0 0 1200 675">
      <title>NTRO Intelligence Brief</title>
      <rect width="100%" height="100%" fill="#F8FAFC"/>
      <text x="48" y="70" fill="#1E3A8A" font-size="28">NTRO</text>
    </svg>
""")

_FALLBACK_SVG = textwrap.dedent("""\
    <svg xmlns="http://www.w3.org/2000/svg" width="1200" height="675" viewBox="0 0 1200 675">
      <title>Sudarshan Infographic Draft</title>
      <rect width="100%" height="100%" fill="#F8FAFC"/>
      <g><rect x="24" y="170" width="350" height="112" rx="12" fill="#F8FAFC" stroke="#CBD5E1"/>
         <text x="42" y="200" fill="#1E3A8A" font-weight="700">Observation 1</text>
         <text x="42" y="214" fill="#334155"><tspan x="42" dy="1.2em">Evidence sentence here</tspan></text>
      </g>
      <text x="32" y="650" fill="#475569">Draft preview</text>
    </svg>
""")

_FOREIGN_OBJECT_SVG = textwrap.dedent("""\
    <svg xmlns="http://www.w3.org/2000/svg" width="1200" height="675" viewBox="0 0 1200 675">
      <title>Bad SVG</title>
      <rect width="100%" height="100%" fill="#F8FAFC"/>
      <foreignObject x="10" y="10" width="200" height="100">
        <div xmlns="http://www.w3.org/1999/xhtml">Hello</div>
      </foreignObject>
    </svg>
""")


def _write_svg(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# 1. coerce_renderer_mode
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw,expected", [
    ("antv", "native"),
    ("native", "native"),
    ("fallback", "fallback"),
    ("syntax_only", "syntax_only"),
    ("failed", "failed"),
    ("ANTV", "native"),      # case-insensitive
    ("FALLBACK", "fallback"),
    ("garbage", "unknown"),
    ("", "unknown"),
    (None, "unknown"),
])
def test_coerce_renderer_mode(raw, expected):
    assert coerce_renderer_mode(raw) == expected


def test_unknown_mode_is_in_never_approved():
    assert "unknown" in _NEVER_APPROVED_MODES


def test_native_and_fallback_are_deliverable():
    assert "native" in _DELIVERABLE_MODES
    assert "fallback" in _DELIVERABLE_MODES


# ---------------------------------------------------------------------------
# 2. foreignObject rejection
# ---------------------------------------------------------------------------


def test_validate_svg_safety_rejects_foreign_object():
    issues = validate_svg_safety(_FOREIGN_OBJECT_SVG)
    assert any("foreignobject" in i.lower() or "forbidden" in i.lower() for i in issues), issues


def test_validate_svg_safety_rejects_script():
    issues = validate_svg_safety('<svg><script>alert(1)</script></svg>')
    assert issues


def test_validate_svg_safety_rejects_event_handler():
    issues = validate_svg_safety('<svg><rect onclick="evil()"/></svg>')
    assert issues


def test_validate_svg_safety_rejects_javascript_url():
    issues = validate_svg_safety('<svg><a href="javascript:alert(1)"/></svg>')
    assert issues


def test_validate_svg_safety_accepts_clean_svg():
    issues = validate_svg_safety(_VALID_NATIVE_SVG)
    assert issues == [], issues


def test_validate_svg_safety_accepts_fallback_svg():
    """The new fallback SVG must pass the shared safety validator."""
    issues = validate_svg_safety(_FALLBACK_SVG)
    assert issues == [], issues


# ---------------------------------------------------------------------------
# 3. inspect_svg — native mode
# ---------------------------------------------------------------------------


def test_native_svg_passes_quality_gate(tmp_path):
    path = _write_svg(tmp_path, "native.svg", _VALID_NATIVE_SVG)
    report = inspect_svg(path, required_text=("NTRO",), renderer_mode="native")
    assert report.renderer_mode == "native"
    assert report.degraded is False
    assert report.approved is True


def test_fallback_svg_is_marked_degraded(tmp_path):
    path = _write_svg(tmp_path, "fallback.svg", _FALLBACK_SVG)
    report = inspect_svg(path, renderer_mode="fallback", operator_waiver_id="waiver-test")
    assert report.renderer_mode == "fallback"
    assert report.degraded is True
    # Fallback can still be approved if quality checks pass
    # (no required_text miss, no safety violations)
    assert report.approved is True


def test_fallback_svg_contains_no_foreign_object(tmp_path):
    """The rewritten fallback must not contain foreignObject."""
    path = _write_svg(tmp_path, "fallback.svg", _FALLBACK_SVG)
    report = inspect_svg(path, renderer_mode="fallback")
    assert report.foreignobject_present is False


def test_foreign_object_svg_fails_gate(tmp_path):
    path = _write_svg(tmp_path, "bad.svg", _FOREIGN_OBJECT_SVG)
    report = inspect_svg(path, renderer_mode="native")
    assert report.approved is False
    assert report.foreignobject_present is True
    assert any("foreignObject" in i for i in report.issues)


# ---------------------------------------------------------------------------
# 4. syntax_only cannot be approved
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["syntax_only", "failed", "unknown"])
def test_never_approved_modes_fail_gate(tmp_path, mode):
    path = _write_svg(tmp_path, f"{mode}.svg", _VALID_NATIVE_SVG)
    # Pass mode as explicit string so the guard fires (renderer_mode is not None)
    report = inspect_svg(path, renderer_mode=mode)
    assert report.approved is False, f"mode={mode} should never be approved"
    assert any(mode in i for i in report.issues)


# ---------------------------------------------------------------------------
# 5. Palette paint-attribute validation
# ---------------------------------------------------------------------------


def test_extract_paint_values_finds_fill():
    svg = '<svg><rect fill="#1E3A8A"/><text fill="#0F172A">x</text></svg>'
    values = _extract_paint_values(svg)
    assert "#1e3a8a" in values
    assert "#0f172a" in values


def test_extract_paint_values_normalises_shorthand():
    svg = '<svg><rect fill="#F8F"/></svg>'
    values = _extract_paint_values(svg)
    # #F8F → #ff88ff
    assert "#ff88ff" in values


def test_required_palette_token_in_paint_passes(tmp_path):
    path = _write_svg(tmp_path, "themed.svg", _VALID_NATIVE_SVG)
    # #1E3A8A is used as fill in the text element
    report = inspect_svg(path, renderer_mode="native", required_palette=["#1E3A8A"])
    palette_issues = [i for i in report.issues if "theme color" in i]
    assert palette_issues == []


def test_required_palette_token_missing_from_paint_fails(tmp_path):
    svg = '<svg width="100" height="100" viewBox="0 0 100 100"><title>T</title><rect fill="#FFFFFF"/></svg>'
    path = _write_svg(tmp_path, "wrong_palette.svg", svg)
    report = inspect_svg(path, renderer_mode="native", required_palette=["#1E3A8A"])
    assert any("theme color" in i for i in report.issues)


def test_allowed_palette_rejects_off_brand_color(tmp_path):
    # SVG with a red fill that is not in the allowed palette
    svg = '<svg width="100" height="100" viewBox="0 0 100 100"><title>T</title><rect fill="#FF0000"/></svg>'
    path = _write_svg(tmp_path, "offbrand.svg", svg)
    report = inspect_svg(
        path,
        renderer_mode="native",
        allowed_palette=["#f8fafc", "#1e3a8a", "#0f172a", "#475569", "#334155", "#cbd5e1", "#38bdf8"],
    )
    assert any("approved theme palette" in i for i in report.issues)


# ---------------------------------------------------------------------------
# 6. Accessibility metadata
# ---------------------------------------------------------------------------


def test_accessibility_passes_with_title_element(tmp_path):
    path = _write_svg(tmp_path, "accessible.svg", _VALID_NATIVE_SVG)
    report = inspect_svg(path, renderer_mode="native")
    accessibility_issues = [i for i in report.issues if "accessibility" in i.lower()]
    assert accessibility_issues == []


def test_accessibility_fails_without_any_metadata(tmp_path):
    svg = '<svg width="100" height="100" viewBox="0 0 100 100"><rect fill="#F8FAFC"/></svg>'
    path = _write_svg(tmp_path, "noaccess.svg", svg)
    report = inspect_svg(path, renderer_mode="native", check_accessibility=True)
    assert any("accessibility" in i.lower() for i in report.issues)


def test_accessibility_passes_with_aria_label(tmp_path):
    svg = '<svg width="100" height="100" viewBox="0 0 100 100" aria-label="Chart"><rect fill="#F8FAFC"/></svg>'
    path = _write_svg(tmp_path, "aria.svg", svg)
    report = inspect_svg(path, renderer_mode="native", check_accessibility=True)
    accessibility_issues = [i for i in report.issues if "accessibility" in i.lower()]
    assert accessibility_issues == []


def test_fallback_svg_passes_accessibility_check(tmp_path):
    """Fallback SVG has a <title> element so accessibility check must pass."""
    path = _write_svg(tmp_path, "fallback_access.svg", _FALLBACK_SVG)
    report = inspect_svg(path, renderer_mode="fallback", check_accessibility=True)
    accessibility_issues = [i for i in report.issues if "accessibility" in i.lower()]
    assert accessibility_issues == []


# ---------------------------------------------------------------------------
# 7. Renderer timeout budget validation
# ---------------------------------------------------------------------------


def test_timeout_below_minimum_raises():
    min_t = MINIMUM_TIMEOUT_SECONDS
    with pytest.raises(ValueError, match="timeout_seconds must be at least"):
        AntVInfographicRenderer(timeout_seconds=min_t - 1)


def test_timeout_at_minimum_is_accepted():
    r = AntVInfographicRenderer(timeout_seconds=MINIMUM_TIMEOUT_SECONDS)
    assert r._effective_deadline == MINIMUM_TIMEOUT_SECONDS - SHUTDOWN_HEADROOM_SECONDS


def test_effective_deadline_is_less_than_timeout():
    t = MINIMUM_TIMEOUT_SECONDS + 10
    r = AntVInfographicRenderer(timeout_seconds=t)
    assert r._effective_deadline < r.timeout_seconds
    assert r._effective_deadline == t - SHUTDOWN_HEADROOM_SECONDS


# ---------------------------------------------------------------------------
# 8. Renderer registry — fallback is degraded
# ---------------------------------------------------------------------------


def test_renderer_registry_native_is_not_degraded():
    registry = default_renderer_registry()
    selection = registry.resolve("infographic.antv", "svg", "render")
    assert selection.degraded is False
    assert selection.selected_renderer_id == "infographic.antv"


def test_renderer_registry_fallback_resolution_is_degraded():
    """When the primary renderer can't handle the operation, fallback is degraded."""
    from pipelines.common.renderers import RendererCapability, RendererRegistry
    # Build a mini registry where 'primary' falls back to 'secondary' for export.
    registry = RendererRegistry([
        RendererCapability("primary", "1", ("svg",), frozenset({"render"}), "secondary"),
        RendererCapability("secondary", "1", ("svg",), frozenset({"render", "export"})),
    ])
    # 'primary' can't export, so resolution falls back to 'secondary' → degraded.
    selection = registry.resolve("primary", "svg", "export")
    assert selection.degraded is True
    assert selection.selected_renderer_id == "secondary"


def test_renderer_cannot_fall_back_to_itself():
    from pipelines.common.renderers import RendererCapability, RendererRegistry
    with pytest.raises(ValueError, match="cannot fall back to itself"):
        RendererCapability(
            "bad.renderer", "1", ("svg",),
            frozenset({"render"}),
            fallback_renderer_id="bad.renderer"
        )


# ---------------------------------------------------------------------------
# 9. Node unavailable → explicit syntax_only (renderer raises)
# ---------------------------------------------------------------------------


def test_renderer_raises_on_unavailable_node():
    """When Node is not installed, renderer raises RuntimeError (not silently syntax_only)."""
    r = AntVInfographicRenderer(node_binary="nonexistent-node-binary-xyz")
    with pytest.raises(RuntimeError, match="unavailable"):
        r("infographic chart { title: 'Test' }", artifact_name="test")


# ---------------------------------------------------------------------------
# 10. svg_contract.py uses shared validator (no foreignObject in canonical SVG)
# ---------------------------------------------------------------------------


def test_svg_contract_rejects_foreign_object(tmp_path):
    from pipelines.ppt.svg_contract import write_canonical_svg
    with pytest.raises(ValueError, match="executable or remote content"):
        write_canonical_svg(
            tmp_path / "out.svg",
            _FOREIGN_OBJECT_SVG,
            source_ir="test",
            renderer_version="test@1",
        )


def test_svg_contract_accepts_clean_svg(tmp_path):
    from pipelines.ppt.svg_contract import write_canonical_svg
    artifact = write_canonical_svg(
        tmp_path / "out.svg",
        _VALID_NATIVE_SVG,
        source_ir="test",
        renderer_version="test@1",
        required_text=("NTRO",),
    )
    assert Path(artifact.path).exists()
