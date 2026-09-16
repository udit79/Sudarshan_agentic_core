"""Validated NTRO advisory contracts.

These are application contracts, not official NTRO templates. Any official
classification, dissemination, or response policy must be supplied as scoped
source memory by the operator.
"""

from __future__ import annotations

import hashlib
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def deterministic_evidence_id(source_reference: str, claim: str) -> str:
    """Derive a canonical source-grounded evidence identifier."""
    norm_source = source_reference.strip().lower()
    norm_claim = claim.strip().lower()
    digest = hashlib.sha256(f"{norm_source}\n{norm_claim}".encode("utf-8")).hexdigest()
    return f"evi-{digest[:16]}"


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(default="", min_length=0)
    claim: str = Field(min_length=1)
    source_reference: str = Field(min_length=1)
    evidence_summary: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_or_derive_evidence_id(self) -> "EvidenceItem":
        if not self.evidence_id or not self.evidence_id.strip():
            self.evidence_id = deterministic_evidence_id(self.source_reference, self.claim)
        return self


class ClaimBinding(BaseModel):
    """Trace one analytical or factual claim back to verified evidence."""

    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=2000)
    role: Literal["fact", "interpretation", "call_to_action", "recommendation"] = "fact"
    evidence_ids: list[str] = Field(default_factory=list)


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
    # Older advisory callers may omit evidence linkage for an operational
    # action. Recommendations and factual claim bindings remain strict; keep
    # action items backward-compatible while validating any supplied IDs.
    evidence_ids: list[str] = Field(default_factory=list)


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
    claim_bindings: list[ClaimBinding] = Field(default_factory=list)

    @field_validator("executive_summary", "overview", "situation", "assessment", "impact_analysis")
    @classmethod
    def reject_placeholder_text(cls, value: str) -> str:
        if "[insert" in value.lower() or "tbd" in value.lower():
            raise ValueError("advisory narrative cannot contain unresolved placeholders")
        return value.strip()

    @model_validator(mode="after")
    def validate_linkage_and_coverage(self) -> "AdvisoryOutput":
        known_evidence_ids = {e.evidence_id for e in self.evidence}

        for rec in self.recommendations:
            if not rec.evidence_ids:
                raise ValueError(f"recommendation '{rec.action}' must cite at least one evidence ID")
            for eid in rec.evidence_ids:
                if eid not in known_evidence_ids:
                    raise ValueError(f"recommendation references unknown evidence ID '{eid}'")

        for action in self.action_items:
            for eid in action.evidence_ids:
                if eid not in known_evidence_ids:
                    raise ValueError(f"action item references unknown evidence ID '{eid}'")

        for claim in self.claim_bindings:
            if claim.role == "fact" and not claim.evidence_ids:
                raise ValueError(f"factual claim '{claim.claim_id}' must cite at least one evidence ID")
            for eid in claim.evidence_ids:
                if eid not in known_evidence_ids:
                    raise ValueError(f"claim '{claim.claim_id}' references unknown evidence ID '{eid}'")

        return self
