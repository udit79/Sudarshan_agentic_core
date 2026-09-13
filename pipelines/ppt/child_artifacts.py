"""Typed reconciliation of visual child artifacts into a slide plan."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ChildArtifactKind = Literal["chart", "table", "flowchart", "infographic", "image"]


class ChildArtifactRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(min_length=1, max_length=160)
    slide_id: str = Field(min_length=1, max_length=120)
    kind: ChildArtifactKind
    quality_report_id: str = Field(min_length=1, max_length=160)
    quality_status: Literal["passed"]
    source_ir_hash: str = Field(min_length=64, max_length=64)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)


class SlideArtifactBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slide_id: str = Field(min_length=1, max_length=120)
    artifacts: list[ChildArtifactRef] = Field(min_length=1, max_length=8)
    required: bool = True

    @model_validator(mode="after")
    def validate_slide_refs(self) -> "SlideArtifactBundle":
        if any(item.slide_id != self.slide_id for item in self.artifacts):
            raise ValueError("child artifact belongs to a different slide")
        if len({item.artifact_id for item in self.artifacts}) != len(self.artifacts):
            raise ValueError("duplicate child artifact IDs")
        return self


def reconcile_slide_artifacts(
    slide_ids: list[str],
    bundles: list[SlideArtifactBundle],
) -> dict[str, SlideArtifactBundle]:
    """Reconcile only quality-passed, uniquely owned child artifacts."""

    known = set(slide_ids)
    if len(known) != len(slide_ids):
        raise ValueError("slide IDs must be unique")
    result: dict[str, SlideArtifactBundle] = {}
    for bundle in bundles:
        if bundle.slide_id not in known:
            raise ValueError(f"child artifact references unknown slide: {bundle.slide_id}")
        if bundle.slide_id in result:
            raise ValueError(f"multiple child bundles for slide: {bundle.slide_id}")
        result[bundle.slide_id] = bundle
    return result


__all__ = ["ChildArtifactRef", "ChildArtifactKind", "SlideArtifactBundle", "reconcile_slide_artifacts"]
