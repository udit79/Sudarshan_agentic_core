"""Versioned semantic style profiles for diagram targets."""

from __future__ import annotations

import re
from typing import Mapping


STYLE_PROFILES: dict[str, dict[str, str]] = {
    "ntro-default": {
        "paper": "#F8FAFC",
        "paper-2": "#FFFFFF",
        "ink": "#0F172A",
        "muted": "#475569",
        "soft": "#CBD5E1",
        "accent": "#1E3A8A",
        "link": "#0F766E",
    },
}


def get_style_profile(name: str = "ntro-default") -> dict[str, str]:
    try:
        return dict(STYLE_PROFILES[name])
    except KeyError as exc:
        raise ValueError(f"unknown diagram style profile: {name}") from exc


def validate_style_profile(profile: Mapping[str, str]) -> list[str]:
    """Validate semantic colors and WCAG AA contrast for normal text."""

    required = {"paper", "ink", "muted", "accent", "link"}
    issues = [f"missing style token: {key}" for key in sorted(required - set(profile))]
    for key, value in profile.items():
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(value)):
            issues.append(f"style token {key} must be a six-digit hex color")
    if issues:
        return issues
    if _contrast(profile["ink"], profile["paper"]) < 4.5:
        issues.append("ink/paper contrast is below WCAG AA")
    if _contrast(profile["muted"], profile["paper"]) < 4.5:
        issues.append("muted/paper contrast is below WCAG AA")
    return issues


def _contrast(foreground: str, background: str) -> float:
    first = _luminance(foreground)
    second = _luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def _luminance(value: str) -> float:
    channels = [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


__all__ = ["STYLE_PROFILES", "get_style_profile", "validate_style_profile"]
