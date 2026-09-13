"""Deterministic structural regression fixtures for infographic SVGs."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class SVGRegressionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool
    actual_hash: str = Field(min_length=64, max_length=64)
    expected_hash: str | None = None
    issues: list[str] = Field(default_factory=list)


def svg_regression_hash(path: str | Path) -> str:
    content = Path(path).read_text(encoding="utf-8")
    normalized = re.sub(r"\s+", " ", content).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def compare_svg_fixture(path: str | Path, expected_hash: str) -> SVGRegressionResult:
    actual = svg_regression_hash(path)
    issues = [] if actual == expected_hash else ["SVG structural regression hash changed"]
    return SVGRegressionResult(approved=not issues, actual_hash=actual, expected_hash=expected_hash, issues=issues)


__all__ = ["SVGRegressionResult", "compare_svg_fixture", "svg_regression_hash"]
