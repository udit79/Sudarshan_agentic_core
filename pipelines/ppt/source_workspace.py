"""Bounded evidence/source workspace contracts for optional PPT exporters.

The workspace contains typed manifests only. It never copies raw evidence or
executes exporter-provided code; an external renderer may consume the manifest
after its own release and authorization gates pass.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pipelines.ppt.schemas import DeckPlan


class EvidenceSourceBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1, max_length=160)
    source_ref: str = Field(min_length=1, max_length=500)
    role: str = Field(default="supports", min_length=1, max_length=40)
    claim_digest: str | None = Field(default=None, min_length=64, max_length=64)

    @field_validator("source_ref")
    @classmethod
    def reject_local_paths_and_credentials(cls, value: str) -> str:
        lowered = value.casefold()
        if "\\" in value or value.startswith(("/", "file:", "data:")) or "password=" in lowered or "token=" in lowered:
            raise ValueError("source_ref must be an opaque authorized reference, not a local path or credential")
        return value.strip()


class DeckSourceWorkspace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(min_length=1)
    presentation_id: str = Field(min_length=1)
    deck_manifest: str = Field(min_length=1)
    evidence_manifest: str = Field(min_length=1)
    source_manifest: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)


def write_deck_source_workspace(
    deck: DeckPlan,
    bindings: Iterable[EvidenceSourceBinding],
    output_root: str | Path,
) -> DeckSourceWorkspace:
    """Write deterministic typed manifests inside an explicit workspace root."""

    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    entries = list(bindings)
    by_id = {entry.evidence_id: entry for entry in entries}
    requested = {
        binding.evidence_id
        for binding in [
            *deck.evidence,
            *(evidence for slide in deck.slides for evidence in slide.evidence),
            *(evidence for slide in deck.slides for evidence in slide.content.evidence),
        ]
    }
    missing = requested - set(by_id)
    if missing:
        raise ValueError(f"evidence bindings missing source references: {sorted(missing)}")
    workspace_id = "ppt-source-" + hashlib.sha256(deck.model_dump_json().encode("utf-8")).hexdigest()[:16]
    deck_path = root / "deck-plan.json"
    evidence_path = root / "evidence-manifest.json"
    source_path = root / "source-manifest.json"
    deck_path.write_text(deck.model_dump_json(indent=2), encoding="utf-8")
    evidence_payload = {
        "workspace_id": workspace_id,
        "presentation_id": deck.presentation_id,
        "evidence": [entry.model_dump(mode="json") for entry in entries],
    }
    evidence_path.write_text(json.dumps(evidence_payload, indent=2, sort_keys=True), encoding="utf-8")
    source_payload = {
        "workspace_id": workspace_id,
        "sources": [
            {"evidence_id": entry.evidence_id, "source_ref": entry.source_ref, "role": entry.role}
            for entry in entries
        ],
    }
    source_path.write_text(json.dumps(source_payload, indent=2, sort_keys=True), encoding="utf-8")
    return DeckSourceWorkspace(
        workspace_id=workspace_id,
        presentation_id=deck.presentation_id,
        deck_manifest=str(deck_path),
        evidence_manifest=str(evidence_path),
        source_manifest=str(source_path),
        evidence_ids=sorted(by_id),
    )


__all__ = ["DeckSourceWorkspace", "EvidenceSourceBinding", "write_deck_source_workspace"]
