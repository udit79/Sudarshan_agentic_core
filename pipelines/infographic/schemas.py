"""Validated AntV infographic contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
