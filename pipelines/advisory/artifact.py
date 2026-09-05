"""Formal, human-approved advisory artifact rendering and handoff."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pipelines.advisory.schemas import AdvisoryOutput


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AdvisoryArtifact(BaseModel):
    """A persisted advisory ready for the application or harness to hand off."""

    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(min_length=1)
    advisory_id: str = Field(min_length=1)
    artifact_type: Literal["markdown"] = "markdown"
    file_name: str = Field(min_length=1)
    path: str = Field(min_length=1)
    content: str = Field(min_length=1)
    created_at: str = Field(default_factory=_now_iso)
    human_approved: bool = True
    approved_by: str | None = None


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- None recorded."


def render_advisory(advisory: AdvisoryOutput, *, approved_by: str | None = None) -> str:
    """Render a formal advisory, without AI/meta language or conversational filler."""

    evidence_rows = "\n".join(
        f"| {item.evidence_id} | {item.claim} | {item.source_reference} | "
        f"{item.confidence:.2f} | {item.evidence_summary} |"
        for item in advisory.evidence
    )
    recommendation_rows = "\n".join(
        f"| {item.priority} | {item.action} | {item.responsible_party} | {item.timeline} |"
        for item in advisory.recommendations
    )
    action_rows = "\n".join(
        f"| {item.priority} | {item.action} | {item.responsible_party} | "
        f"{item.timeline} | {item.completion_signal} |"
        for item in advisory.action_items
    )
    references = _bullets(advisory.references)
    handling = _bullets(advisory.handling_instructions)
    gaps = _bullets(advisory.intelligence_gaps)
    caveats = _bullets(advisory.caveats)

    return f"""# {advisory.title}

**NTRO CASE ADVISORY**  
**Advisory ID:** {advisory.advisory_id}  
**Subject:** {advisory.subject}  
**Severity:** {advisory.severity_rating.upper()}  
**Classification:** {advisory.classification_level}  
**Distribution:** {advisory.distribution}  
**Human approval:** APPROVED{f" by {approved_by}" if approved_by else ""}

## Executive Summary

{advisory.executive_summary}

## Overview

{advisory.overview}

## Situation

{advisory.situation}

## Assessment

{advisory.assessment}

## Observed Patterns

{_bullets(advisory.observed_patterns)}

## Impact Assessment

{advisory.impact_analysis}

## Recommended Actions

| Priority | Action | Responsible Party | Timeline |
|---|---|---|---|
{recommendation_rows}

## Action Plan

| Priority | Action | Responsible Party | Timeline | Completion Signal |
|---|---|---|---|---|
{action_rows}

## Evidence and Provenance

| Evidence ID | Claim | Source Reference | Confidence | Evidence Summary |
|---|---|---|---:|---|
{evidence_rows}

## Confidence and Intelligence Gaps

{advisory.confidence_statement}

**Known gaps**

{gaps}

## Handling Instructions

{handling}

## Caveats

{caveats}

## References

{references}

---

Prepared for the NTRO case-advisory workflow. This document is a case-specific analytical artifact and does not itself establish policy, authority, or operational direction.
"""


class AdvisoryArtifactWriter:
    """Persist only explicitly approved advisory outputs as formal Markdown."""

    def __init__(self, artifact_dir: str | Path = "artifacts/advisories") -> None:
        self.artifact_dir = Path(artifact_dir)

    def write(self, advisory: AdvisoryOutput, *, approved_by: str | None = None) -> AdvisoryArtifact:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r"[^A-Za-z0-9._-]+", "-", advisory.advisory_id).strip(".-") or "advisory"
        file_name = f"{stem}.md"
        path = self.artifact_dir / file_name
        content = render_advisory(advisory, approved_by=approved_by)
        path.write_text(content, encoding="utf-8", newline="\n")
        return AdvisoryArtifact(
            artifact_id=f"artifact-{stem}",
            advisory_id=advisory.advisory_id,
            file_name=file_name,
            path=str(path),
            content=content,
            approved_by=approved_by,
        )
