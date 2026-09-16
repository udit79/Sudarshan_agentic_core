"""Validated output contracts for the PPT presentation generation pipeline.

These are application contracts for structured NTRO briefing presentations.
Any classification, dissemination, or response policy must be supplied as
scoped source memory by the operator.
"""

from __future__ import annotations

import re
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EvidenceBinding(BaseModel):
    """Provenance attached to a material visual or narrative claim."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1)
    role: Literal["supports", "contradicts", "context", "uncertain"] = "supports"


class PresentationTheme(BaseModel):
    """Canonical visual tokens applied to native PPT objects and QA."""

    model_config = ConfigDict(extra="forbid")

    theme_id: str = Field(default="ntro-briefing", min_length=1, max_length=80)
    version: str = Field(default="1", min_length=1, max_length=40)
    background: str = "#0B1220"
    foreground: str = "#F8FAFC"
    accent: str = "#38BDF8"
    muted: str = "#94A3B8"
    border: str = "#334155"
    title_font: str = "Aptos Display"
    body_font: str = "Aptos"

    @field_validator("background", "foreground", "accent", "muted", "border")
    @classmethod
    def validate_color(cls, value: str) -> str:
        value = str(value).strip().upper()
        if not re.fullmatch(r"#[0-9A-F]{6}", value):
            raise ValueError("presentation theme colors must be six-digit hex values")
        return value

    def palette(self) -> tuple[str, ...]:
        return (self.background, self.foreground, self.accent, self.muted, self.border)

    def hash(self) -> str:
        import hashlib
        import json

        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def resolve_presentation_theme(constraints: Any = None) -> PresentationTheme:
    """Resolve one deterministic theme without letting a model invent tokens."""

    data: Mapping[str, Any]
    if hasattr(constraints, "model_dump"):
        data = constraints.model_dump(mode="json")
    elif isinstance(constraints, Mapping):
        data = constraints
    else:
        data = {}
    tokens = dict(data.get("theme_tokens") or {})
    palette = [str(item).strip() for item in data.get("color_palette") or [] if str(item).strip()]
    if palette:
        tokens.setdefault("accent", palette[0])
        if len(palette) > 1:
            tokens.setdefault("muted", palette[1])
        if len(palette) > 2:
            tokens.setdefault("border", palette[2])
    allowed = {"background", "foreground", "accent", "muted", "border", "title_font", "body_font"}
    selected = {key: value for key, value in tokens.items() if key in allowed}
    return PresentationTheme(
        theme_id=str(data.get("theme_id") or "ntro-briefing"),
        **selected,
    )


class FlowchartNode(BaseModel):
    """Semantic node in a renderer-neutral flowchart."""

    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1)
    label: str = Field(min_length=1, max_length=180)
    kind: Literal["start", "process", "decision", "review", "end"] = "process"
    group: str | None = None
    evidence: list[EvidenceBinding] = Field(default_factory=list)


class FlowchartEdge(BaseModel):
    """Directed relationship between two flowchart nodes."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    source: str = Field(min_length=1, validation_alias="from")
    target: str = Field(min_length=1, validation_alias="to")
    label: str = Field(default="", max_length=120)


class FlowchartSpec(BaseModel):
    """Graph IR consumed by both SVG and editable PPTX renderers."""

    model_config = ConfigDict(extra="forbid")

    flowchart_id: str = Field(min_length=1)
    direction: Literal["left-to-right", "top-to-bottom"] = "left-to-right"
    nodes: list[FlowchartNode] = Field(min_length=1, max_length=80)
    edges: list[FlowchartEdge] = Field(default_factory=list, max_length=160)
    layout_hints: dict[str, Any] = Field(default_factory=dict)
    style_tokens: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_graph_references(self) -> "FlowchartSpec":
        node_ids = [node.node_id for node in self.nodes]
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("flowchart node IDs must be unique")
        known = set(node_ids)
        for edge in self.edges:
            if edge.source not in known or edge.target not in known:
                raise ValueError("flowchart edges must reference existing node IDs")
            if edge.source == edge.target:
                raise ValueError("flowchart edges cannot point to the same node")
        return self


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
    dependencies: list[str] = Field(default_factory=list, max_length=12)


class SlideTask(BaseModel):
    """Typed work item for a slide specialist or deterministic renderer."""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    slide_id: str = Field(min_length=1)
    required_skills: list[str] = Field(default_factory=list)
    input_refs: list[str] = Field(default_factory=list)
    output_type: Literal["slide-content-ir", "visual-ir", "rendered-slide"]
    dependencies: list[str] = Field(default_factory=list, max_length=12)


class DeckPlan(BaseModel):
    """Presentation plan before any renderer-specific conversion."""

    model_config = ConfigDict(extra="forbid")

    presentation_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    theme_id: str = Field(min_length=1)
    template_id: str = Field(default="native-default", min_length=1, max_length=120)
    design_tokens: dict[str, str] = Field(default_factory=dict, max_length=32)
    renderer_capabilities: list[str] = Field(default_factory=list, max_length=24)
    slides: list[SlideSpec] = Field(min_length=1, max_length=30)
    tasks: list[SlideTask] = Field(default_factory=list)
    evidence: list[EvidenceBinding] = Field(default_factory=list)
    slide_dependencies: dict[str, list[str]] = Field(default_factory=dict, max_length=30)

    @model_validator(mode="after")
    def validate_declared_dependencies(self) -> "DeckPlan":
        slide_ids = [slide.slide_id for slide in self.slides]
        if len(slide_ids) != len(set(slide_ids)):
            raise ValueError("deck slide IDs must be unique")
        known_slides = set(slide_ids)
        task_ids = [task.task_id for task in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("deck task IDs must be unique")
        unknown_task_slides = {task.slide_id for task in self.tasks} - known_slides
        if unknown_task_slides:
            raise ValueError(f"deck tasks reference unknown slides: {sorted(unknown_task_slides)}")
        declared = {slide.slide_id: list(slide.dependencies) for slide in self.slides}
        for slide_id, dependencies in self.slide_dependencies.items():
            if slide_id not in known_slides:
                raise ValueError(f"deck dependency declaration references unknown slide: {slide_id}")
            declared[slide_id] = list(dependencies)
        for slide_id, dependencies in declared.items():
            if len(dependencies) != len(set(dependencies)):
                raise ValueError(f"duplicate slide dependency in {slide_id}")
            unknown = set(dependencies) - known_slides
            if unknown:
                raise ValueError(f"slide {slide_id} depends on unknown slides: {sorted(unknown)}")
            if slide_id in dependencies:
                raise ValueError(f"slide {slide_id} cannot depend on itself")
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(slide_id: str) -> None:
            if slide_id in visiting:
                raise ValueError("deck slide dependencies must be acyclic")
            if slide_id in visited:
                return
            visiting.add(slide_id)
            for dependency in declared.get(slide_id, []):
                visit(dependency)
            visiting.remove(slide_id)
            visited.add(slide_id)

        for slide_id in slide_ids:
            visit(slide_id)
        return self


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

    slide_id: str = Field(min_length=1)
    order: int = Field(ge=1)
    title: str = Field(min_length=1)
    bullets: list[str] = Field(default_factory=list, max_length=8)
    speaker_notes: str = Field(default="", description="Presenter notes for this slide.")
    layout: Literal["cover", "agenda", "content", "two_column", "conclusion", "closing"] = "content"

class SlidePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slide_id: str = Field(min_length=1)
    operation: Literal["replace_content", "replace_visual", "rewrite_notes"]
    content: dict[str, Any] = Field(default_factory=dict)

class IncrementalDeckEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_artifact_id: str = Field(min_length=1)
    base_manifest_id: str = Field(min_length=1)
    base_manifest_version: int = Field(ge=1)
    edits: list[SlidePatch] = Field(default_factory=list)
    requested_scope: list[str] = Field(default_factory=list)
    idempotency_key: str = Field(min_length=1)


class PresentationOutput(BaseModel):
    """The only output eligible for case-memory write-back and PPTX rendering."""

    model_config = ConfigDict(extra="forbid")

    presentation_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    template_id: str = Field(default="native-default", min_length=1, max_length=120)
    template_version: str | None = Field(default=None, max_length=40)
    classification_level: str = Field(min_length=1)
    distribution: str = Field(min_length=1)
    slides: list[SlideContent] = Field(min_length=2, max_length=15)
    @field_validator("title")
    @classmethod
    def reject_placeholder_text(cls, value: str) -> str:
        lowered = value.lower()
        if "[insert" in lowered or "tbd" in lowered:
            raise ValueError("presentation narrative cannot contain unresolved placeholders")
        return value.strip()

    @model_validator(mode="after")
    def validate_slide_identity(self) -> "PresentationOutput":
        slide_ids = [slide.slide_id for slide in self.slides]
        if len(slide_ids) != len(set(slide_ids)):
            raise ValueError("presentation slide IDs must be unique")
        orders = [slide.order for slide in self.slides]
        if len(orders) != len(set(orders)):
            raise ValueError("presentation slide orders must be unique")
        return self


class PresentationQualityReview(BaseModel):
    """Quality gate result."""

    model_config = ConfigDict(extra="forbid")

    approved: bool
    issues: list[str] = Field(default_factory=list)
    required_revisions: list[str] = Field(default_factory=list)


class SlideManifest(BaseModel):
    """Manifest for a single incrementally generated slide."""

    model_config = ConfigDict(extra="forbid")

    slide_id: str = Field(min_length=1)
    order: int = Field(ge=1)
    source_ir_hash: str | None = None
    rendered_part_hash: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    asset_refs: list[str] = Field(default_factory=list)
    layout_id: str | None = None
    status: Literal["pending", "rendered", "failed", "unchanged", "invalidated"] = "pending"


class DeckManifest(BaseModel):
    """Authoritative server-side manifest for an incremental presentation."""

    model_config = ConfigDict(extra="forbid")

    deck_id: str = Field(min_length=1)
    version: int = Field(default=1, ge=1)
    base_artifact_id: str | None = None
    template_id: str = Field(min_length=1)
    template_version: str | None = None
    theme_id: str = Field(min_length=1)
    theme_hash: str | None = None
    theme_tokens: dict[str, Any] = Field(default_factory=dict)
    master_id: str | None = None
    slide_order: list[str] = Field(default_factory=list)
    slides: list[SlideManifest] = Field(default_factory=list)
    manifest_version: str = "1.0"
