from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pipelines.advisory.schemas import ClaimBinding, EvidenceItem


class KeyFinding(BaseModel):
    """One decision-relevant finding linked to verified evidence."""

    model_config = ConfigDict(extra="forbid")

    finding_id: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[str] = Field(min_length=1)


class ExecutiveSummaryOutput(BaseModel):
    """A concise, evidence-linked summary for display or downstream use."""

    model_config = ConfigDict(extra="forbid")

    summary_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    executive_summary: str = Field(min_length=1)
    key_findings: list[KeyFinding] = Field(min_length=1, max_length=8)
    implications: list[str] = Field(min_length=1)
    recommended_actions: list[str] = Field(min_length=1)
    evidence: list[EvidenceItem] = Field(min_length=1)
    confidence_statement: str = Field(min_length=1)
    intelligence_gaps: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    claim_bindings: list[ClaimBinding] = Field(default_factory=list)

    @field_validator("key_findings", mode="before")
    @classmethod
    def coerce_key_findings(cls, values: Any) -> list[Any]:
        if not isinstance(values, (list, tuple)):
            return values
        coerced = []
        for index, item in enumerate(values, start=1):
            if isinstance(item, str):
                coerced.append(KeyFinding(
                    finding_id=f"kf-{index}",
                    text=item.strip(),
                    evidence_ids=[],
                ))
            elif isinstance(item, dict):
                coerced.append(KeyFinding.model_validate(item))
            else:
                coerced.append(item)
        return coerced

    @field_validator("executive_summary", "title")
    @classmethod
    def reject_placeholder_text(cls, value: str) -> str:
        lowered = value.lower()
        if "[insert" in lowered or "tbd" in lowered:
            raise ValueError("summary cannot contain unresolved placeholders")
        return value.strip()

    @model_validator(mode="after")
    def validate_evidence_linkage(self) -> "ExecutiveSummaryOutput":
        known_evidence_ids = {e.evidence_id for e in self.evidence}

        updated_findings: list[KeyFinding] = []
        for kf in self.key_findings:
            eids = list(kf.evidence_ids)
            for eid in eids:
                if eid not in known_evidence_ids:
                    raise ValueError(f"key finding '{kf.finding_id}' references unknown evidence ID '{eid}'")
            updated_findings.append(kf.model_copy(update={"evidence_ids": eids}))
        object.__setattr__(self, "key_findings", updated_findings)

        for claim in self.claim_bindings:
            if claim.role == "fact" and not claim.evidence_ids:
                raise ValueError(f"factual claim '{claim.claim_id}' must cite at least one evidence ID")
            for eid in claim.evidence_ids:
                if eid not in known_evidence_ids:
                    raise ValueError(f"claim '{claim.claim_id}' references unknown evidence ID '{eid}'")

        return self
