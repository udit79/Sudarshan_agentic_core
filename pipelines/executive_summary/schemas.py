"""Validated output for the frontend-facing executive summary generator."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pipelines.advisory.schemas import EvidenceItem


class ExecutiveSummaryOutput(BaseModel):
    """A concise, evidence-linked summary for display or downstream use."""

    model_config = ConfigDict(extra="forbid")

    summary_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    executive_summary: str = Field(min_length=1)
    key_findings: list[str] = Field(min_length=1, max_length=8)
    implications: list[str] = Field(min_length=1)
    recommended_actions: list[str] = Field(min_length=1)
    evidence: list[EvidenceItem] = Field(min_length=1)
    confidence_statement: str = Field(min_length=1)
    intelligence_gaps: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)

    @field_validator("executive_summary", "title")
    @classmethod
    def reject_placeholder_text(cls, value: str) -> str:
        lowered = value.lower()
        if "[insert" in lowered or "tbd" in lowered:
            raise ValueError("summary cannot contain unresolved placeholders")
        return value.strip()
