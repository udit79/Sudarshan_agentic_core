"""Validated AntV infographic contracts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pipelines.advisory.schemas import EvidenceItem


class InfographicOutput(BaseModel):
    """Agent-produced syntax plus the renderer artifact handoff."""

    model_config = ConfigDict(extra="forbid")

    infographic_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    visual_type: Literal[
        "auto", "process", "timeline", "list", "comparison", "hierarchy", "flow", "other"
    ] = "auto"
    syntax: str = Field(min_length=1, max_length=30000)
    alt_text: str = Field(min_length=1)
    evidence: list[EvidenceItem] = Field(min_length=1)
    references: list[str] = Field(default_factory=list)
    confidence_statement: str = Field(min_length=1)
    intelligence_gaps: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    render_status: Literal["pending", "rendered", "syntax_only"] = "pending"
    artifact_path: str | None = None
    render_error: str | None = None

    @field_validator("syntax", "title", "alt_text", mode="before")
    @classmethod
    def normalize_and_reject_unresolved_content(cls, value: str) -> str:
        if not isinstance(value, str):
            return value
        # AntV's DSL is parsed as source text. Curly quotation marks inside a
        # quoted DSL value can produce an invalid token stream, so use safe
        # ASCII punctuation before the quality critic and renderer see it.
        value = (
            value.replace("\u201c", "'")
            .replace("\u201d", "'")
            .replace("\u2018", "'")
            .replace("\u2019", "'")
            .replace("\u2013", "-")
            .replace("\u2014", "-")
            .replace("\u00a0", " ")
        )
        lowered = value.lower()
        if "[insert" in lowered or "tbd" in lowered:
            raise ValueError("infographic content cannot contain unresolved placeholders")
        return value.strip()

    @field_validator("syntax")
    @classmethod
    def require_infographic_syntax(cls, value: str) -> str:
        if not value.lstrip().startswith("infographic"):
            raise ValueError("syntax must start with the AntV infographic directive")
        return value


class InfographicBlock(BaseModel):
    """Renderer-neutral semantic block derived from verified evidence."""

    model_config = ConfigDict(extra="forbid")

    block_id: str = Field(min_length=1)
    label: str = Field(min_length=1, max_length=180)
    description: str = Field(min_length=1, max_length=500)
    kind: Literal["observation", "process", "comparison", "caveat"] = "observation"
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)


class InfographicIR(BaseModel):
    """Semantic visual program compiled to AntV syntax by a deterministic adapter."""

    model_config = ConfigDict(extra="forbid")

    infographic_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=300)
    visual_type: Literal[
        "process", "timeline", "list", "comparison", "hierarchy", "flow", "mind-map", "other"
    ] = "list"
    alt_text: str = Field(min_length=1, max_length=2000)
    blocks: list[InfographicBlock] = Field(min_length=1, max_length=30)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    caveats: list[str] = Field(default_factory=list, max_length=20)
    style_tokens: dict[str, Any] = Field(default_factory=dict)


class DiagramNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1)
    label: str = Field(min_length=1, max_length=180)
    kind: Literal["start", "process", "decision", "review", "end"] = "process"
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)


class DiagramEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    label: str = Field(default="", max_length=120)


class DiagramIR(BaseModel):
    """Small graph IR shared by infographic and future diagram renderers."""

    model_config = ConfigDict(extra="forbid")

    diagram_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=300)
    nodes: list[DiagramNode] = Field(min_length=1, max_length=80)
    edges: list[DiagramEdge] = Field(default_factory=list, max_length=160)

    @model_validator(mode="after")
    def validate_graph(self) -> "DiagramIR":
        ids = {node.node_id for node in self.nodes}
        if len(ids) != len(self.nodes):
            raise ValueError("diagram node IDs must be unique")
        for edge in self.edges:
            if edge.source not in ids or edge.target not in ids:
                raise ValueError("diagram edge references an unknown node")
            if edge.source == edge.target:
                raise ValueError("diagram edge cannot reference the same node")
        return self
