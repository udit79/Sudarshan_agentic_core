"""Validated output contracts for the PPT presentation generation pipeline.

These are application contracts for structured NTRO briefing presentations.
Any classification, dissemination, or response policy must be supplied as
scoped source memory by the operator.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SlideContent(BaseModel):
    """A single slide in the generated presentation."""

    model_config = ConfigDict(extra="forbid")

    slide_number: int = Field(ge=1)
    title: str = Field(min_length=1)
    bullets: list[str] = Field(min_length=1, max_length=8)
    speaker_notes: str = Field(default="", description="Presenter notes for this slide.")
    layout: Literal["title", "content", "two_column", "conclusion"] = "content"


class PresentationOutput(BaseModel):
    """The only output eligible for case-memory write-back and PPTX rendering."""

    model_config = ConfigDict(extra="forbid")

    presentation_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    subtitle: str = Field(min_length=1)
    classification_level: str = Field(min_length=1)
    distribution: str = Field(min_length=1)
    agenda: list[str] = Field(min_length=2, max_length=10)
    slides: list[SlideContent] = Field(min_length=2, max_length=15)
    conclusion_summary: str = Field(min_length=1)
    key_takeaways: list[str] = Field(min_length=1, max_length=5)
    references: list[str] = Field(default_factory=list)
    confidence_statement: str = Field(min_length=1)
    intelligence_gaps: list[str] = Field(default_factory=list)

    @field_validator("title", "subtitle", "conclusion_summary")
    @classmethod
    def reject_placeholder_text(cls, value: str) -> str:
        lowered = value.lower()
        if "[insert" in lowered or "tbd" in lowered:
            raise ValueError("presentation narrative cannot contain unresolved placeholders")
        return value.strip()


class PresentationQualityReview(BaseModel):
    """Quality gate result."""

    model_config = ConfigDict(extra="forbid")

    approved: bool
    issues: list[str] = Field(default_factory=list)
    required_revisions: list[str] = Field(default_factory=list)
