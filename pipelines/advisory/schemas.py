"""Validated NTRO advisory contracts.

These are application contracts, not official NTRO templates. Any official
classification, dissemination, or response policy must be supplied as scoped
source memory by the operator.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    source_reference: str = Field(min_length=1)
    evidence_summary: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    limitations: list[str] = Field(default_factory=list)


class Recommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    priority: Literal["P1", "P2", "P3"]
    action: str = Field(min_length=1)
    responsible_party: str = Field(min_length=1)
    timeline: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)


class ActionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    priority: Literal["P1", "P2", "P3"]
    action: str = Field(min_length=1)
    responsible_party: str = Field(min_length=1)
    timeline: str = Field(min_length=1)
    completion_signal: str = Field(min_length=1)


class IntelligenceBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed_facts: list[str] = Field(min_length=1)
    analytical_assessments: list[str] = Field(min_length=1)
    entities: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(min_length=1)
    intelligence_gaps: list[str] = Field(default_factory=list)


class EvidenceReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_quality: Literal["high", "moderate", "low", "insufficient"]
    supported_claims: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    provenance_issues: list[str] = Field(default_factory=list)
    required_caveats: list[str] = Field(default_factory=list)


class QualityReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool
    issues: list[str] = Field(default_factory=list)
    required_revisions: list[str] = Field(default_factory=list)


class AdvisoryOutput(BaseModel):
    """The only output eligible for human approval and case-memory write-back."""

    model_config = ConfigDict(extra="forbid")

    advisory_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    organization_context: Literal["NTRO case advisory"] = "NTRO case advisory"
    subject: str = Field(min_length=1)
    severity_rating: Literal["critical", "high", "moderate", "low", "informational"]
    classification_level: str = Field(min_length=1)
    distribution: str = Field(min_length=1)
    executive_summary: str = Field(min_length=1)
    overview: str = Field(min_length=1)
    situation: str = Field(min_length=1)
    assessment: str = Field(min_length=1)
    impact_analysis: str = Field(min_length=1)
    observed_patterns: list[str] = Field(min_length=1)
    recommendations: list[Recommendation] = Field(min_length=1, max_length=5)
    action_items: list[ActionItem] = Field(min_length=1)
    evidence: list[EvidenceItem] = Field(min_length=1)
    references: list[str] = Field(default_factory=list)
    handling_instructions: list[str] = Field(default_factory=list)
    confidence_statement: str = Field(min_length=1)
    intelligence_gaps: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)

    @field_validator("executive_summary", "overview", "situation", "assessment", "impact_analysis")
    @classmethod
    def reject_placeholder_text(cls, value: str) -> str:
        if "[insert" in value.lower() or "tbd" in value.lower():
            raise ValueError("advisory narrative cannot contain unresolved placeholders")
        return value.strip()
