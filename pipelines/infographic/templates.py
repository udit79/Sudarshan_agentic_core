"""Allow-listed infographic templates and themes.

The registry is intentionally small. It describes only the stable AntV
directive currently used by the native bridge; unsupported visual intents use
that explicit fallback rather than allowing model-produced template names or
remote assets to cross the renderer boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pipelines.diagram.style import get_style_profile, validate_style_profile


InfographicRenderMode = Literal["svg", "png", "fallback"]


@dataclass(frozen=True, slots=True)
class InfographicTemplate:
    template_id: str
    directive: str
    visual_types: tuple[str, ...]
    supported_modes: tuple[InfographicRenderMode, ...]
    external_dependencies: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class InfographicTemplateSelection:
    template: InfographicTemplate
    mode: InfographicRenderMode
    used_fallback: bool


class InfographicTheme(BaseModel):
    """Versioned local theme manifest; no fonts, URLs, or executable tokens."""

    model_config = ConfigDict(extra="forbid")

    theme_id: str = Field(min_length=1, max_length=80)
    version: str = Field(min_length=1, max_length=40)
    tokens: dict[str, str] = Field(min_length=1, max_length=24)
    density: Literal["comfortable", "compact"] = "comfortable"
    bilingual: bool = False


_TEMPLATES: dict[str, InfographicTemplate] = {
    "list-grid-simple": InfographicTemplate(
        template_id="list-grid-simple",
        directive="list-grid-simple",
        visual_types=("list", "process", "timeline", "comparison", "hierarchy", "flow", "mind-map", "other"),
        supported_modes=("svg", "fallback"),
    ),
}


def infographic_template_registry() -> dict[str, InfographicTemplate]:
    """Return a copy of the approved template registry."""

    return dict(_TEMPLATES)


def select_infographic_template(
    visual_type: str,
    *,
    requested_template: str | None = None,
    mode: InfographicRenderMode = "svg",
) -> InfographicTemplateSelection:
    """Select a safe template by typed visual intent and render mode."""

    normalized_type = str(visual_type).strip().lower()
    template_id = (requested_template or "list-grid-simple").strip().lower()
    template = _TEMPLATES.get(template_id)
    if template is None:
        raise ValueError(f"unknown infographic template: {requested_template}")
    if mode not in template.supported_modes:
        raise ValueError(f"template '{template_id}' does not support render mode '{mode}'")
    if normalized_type not in template.visual_types:
        raise ValueError(f"template '{template_id}' does not support visual type '{visual_type}'")
    return InfographicTemplateSelection(
        template=template,
        mode=mode,
        used_fallback=mode == "fallback",
    )


def infographic_theme_registry() -> dict[str, dict[str, str]]:
    """Return versioned, local-only theme tokens for infographic output."""

    return {"ntro-default": get_style_profile()}


def infographic_theme_manifest(theme_id: str = "ntro-default") -> InfographicTheme:
    """Return the validated versioned theme contract used by compilers."""

    tokens = get_infographic_theme(theme_id)
    return InfographicTheme(theme_id=theme_id, version="ntro-default@1", tokens=tokens)


def get_infographic_theme(theme_id: str = "ntro-default") -> dict[str, str]:
    """Return a validated theme without loading fonts, URLs, or remote assets."""

    themes = infographic_theme_registry()
    if theme_id not in themes:
        raise ValueError(f"unknown infographic theme: {theme_id}")
    theme = dict(themes[theme_id])
    issues = validate_style_profile(theme)
    if issues:
        raise ValueError("invalid infographic theme: " + "; ".join(issues))
    return theme


__all__ = [
    "InfographicRenderMode",
    "InfographicTemplate",
    "InfographicTemplateSelection",
    "InfographicTheme",
    "get_infographic_theme",
    "infographic_theme_manifest",
    "infographic_template_registry",
    "infographic_theme_registry",
    "select_infographic_template",
]
