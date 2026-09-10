"""Validated output contracts for the PPT presentation generation pipeline.

These are application contracts for structured NTRO briefing presentations.
Any classification, dissemination, or response policy must be supplied as
scoped source memory by the operator.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EvidenceBinding(BaseModel):
    """Provenance attached to a material visual or narrative claim."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1)
    role: Literal["supports", "contradicts", "context", "uncertain"] = "supports"


class LayoutBox(BaseModel):
    """Normalized slide coordinates consumed by renderers."""

    model_config = ConfigDict(extra="forbid")

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def fits_slide(self) -> "LayoutBox":
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("layout box must remain within normalized slide bounds")
        return self


class VisualIR(BaseModel):
    """Renderer-neutral visual program; never raw PPTX/XML."""

    model_config = ConfigDict(extra="forbid")

    visual_id: str = Field(min_length=1)
    kind: Literal["flowchart", "chart", "table", "image", "shape"]
    bounds: LayoutBox
    alt_text: str = Field(min_length=1)
    evidence: list[EvidenceBinding] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("data")
    @classmethod
    def reject_renderer_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        forbidden = {"pptx_xml", "shape_xml", "raw_pptx", "presentationml"}
        if forbidden.intersection(str(key).lower() for key in value):
            raise ValueError("VisualIR cannot contain renderer-specific XML or PPTX payloads")
        return value


class SlideContentIR(BaseModel):
    """Structured slide content shared by PPTX, SVG, and web renderers."""

    model_config = ConfigDict(extra="forbid")

    slide_id: str = Field(min_length=1)
    headline: str = Field(min_length=1)
    body: list[str] = Field(default_factory=list, max_length=8)
    visuals: list[VisualIR] = Field(default_factory=list, max_length=8)
    evidence: list[EvidenceBinding] = Field(default_factory=list)

    @field_validator("headline", "body")
    @classmethod
    def reject_unresolved_placeholders(cls, value):
        values = [value] if isinstance(value, str) else value
        for item in values:
            lowered = item.lower()
            if "[insert" in lowered or "tbd" in lowered:
                raise ValueError("slide IR cannot contain unresolved placeholders")
        return value


class SlideSpec(BaseModel):
    """One planned slide with a single message and typed content IR."""

    model_config = ConfigDict(extra="forbid")

    slide_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    intent: str = Field(min_length=1)
    one_message: str = Field(min_length=1)
    layout: Literal["narrative", "flowchart", "timeline", "matrix", "chart", "closing"] = "narrative"
    content: SlideContentIR
    speaker_notes: str = ""
    evidence: list[EvidenceBinding] = Field(default_factory=list)


class SlideTask(BaseModel):
    """Typed work item for a slide specialist or deterministic renderer."""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    slide_id: str = Field(min_length=1)
    required_skills: list[str] = Field(default_factory=list)
    input_refs: list[str] = Field(default_factory=list)
    output_type: Literal["slide-content-ir", "visual-ir", "rendered-slide"]


class DeckPlan(BaseModel):
    """Presentation plan before any renderer-specific conversion."""

    model_config = ConfigDict(extra="forbid")

    presentation_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    theme_id: str = Field(min_length=1)
    slides: list[SlideSpec] = Field(min_length=1, max_length=30)
    tasks: list[SlideTask] = Field(default_factory=list)
    evidence: list[EvidenceBinding] = Field(default_factory=list)


class RepairPatch(BaseModel):
    """Targeted visual/content repair rather than full-deck regeneration."""

    model_config = ConfigDict(extra="forbid")

    issue_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    operation: Literal["replace", "move", "resize", "remove", "rewrite"]
    value: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceBinding] = Field(default_factory=list)


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
