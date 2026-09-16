"""Strict contracts for the typed ingestion/evidence boundary.

These models are transport-neutral. They describe source registration and
derived evidence without importing the scheduler, Harness, Cognee, or any
modality-specific parser. The legacy ``IngestedDocument`` contract remains
available until the asynchronous evidence path is promoted.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


IngestionStatus = Literal[
    "accepted",
    "queued",
    "validating",
    "parsing",
    "enriching",
    "indexing",
    "quality_check",
    "ready",
    "partial",
    "failed",
    "cancelled",
]

IngestionQualityStatus = Literal["pending", "passed", "failed", "partial"]

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class IngestionContractModel(BaseModel):
    """Reject undeclared fields at the source/evidence boundary."""

    model_config = ConfigDict(extra="forbid")


class IngestionBudget(IngestionContractModel):
    """Reserved work envelope for one ingestion."""

    token_budget: int = Field(default=0, ge=0)
    parser_units: int = Field(default=1, ge=0)
    ocr_calls: int = Field(default=0, ge=0)
    vision_calls: int = Field(default=0, ge=0)
    summary_tokens: int = Field(default=0, ge=0)
    embedding_tokens: int = Field(default=0, ge=0)
    max_fan_out: int = Field(default=64, ge=1)
    wall_time_seconds: int = Field(default=300, ge=1)


class VideoIngestionPolicy(IngestionContractModel):
    """Deterministic limits for multimodal video extraction.

    The Harness/application owns this policy.  Extractors may implement it,
    but they must not expand it from model output or source content.
    """

    max_duration_seconds: int = Field(default=7200, ge=1, le=86_400)
    max_visual_samples: int = Field(default=12, ge=1, le=256)
    sample_interval_seconds: float = Field(default=5.0, gt=0, le=3600)
    audio_enabled: bool = True
    visual_enabled: bool = True


class EvidenceLocation(IngestionContractModel):
    """Address of evidence in the original source or a derived media asset."""

    page: int | None = Field(default=None, ge=1)
    slide: int | None = Field(default=None, ge=1)
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, ge=0)
    bbox: list[float] | None = None

    @field_validator("bbox")
    @classmethod
    def validate_bbox(cls, value: list[float] | None) -> list[float] | None:
        if value is None:
            return None
        if len(value) != 4 or any(item < 0 or item > 1 for item in value):
            raise ValueError("bbox must contain four normalized values between 0 and 1")
        left, top, right, bottom = value
        if right < left or bottom < top:
            raise ValueError("bbox coordinates must be ordered left, top, right, bottom")
        return value

    @model_validator(mode="after")
    def validate_time_range(self) -> "EvidenceLocation":
        if self.start_seconds is not None and self.end_seconds is not None:
            if self.end_seconds < self.start_seconds:
                raise ValueError("end_seconds must be greater than or equal to start_seconds")
        return self


class IngestionManifest(IngestionContractModel):
    """Immutable source registration and derived-work policy."""

    ingestion_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    source_reference: str = Field(min_length=1)
    source_hash: str = Field(min_length=71, max_length=71)
    media_type: str = Field(min_length=1)
    modality: str = Field(min_length=1)
    user_id: str | None = None
    case_id: str | None = None
    task_id: str | None = None
    classification_level: str = Field(min_length=1)
    status: IngestionStatus = "accepted"
    extractor_version: str = Field(min_length=1)
    model_policy: str = Field(min_length=1)
    configuration_hash: str = Field(min_length=1)
    budget: IngestionBudget = Field(default_factory=IngestionBudget)
    created_at: str = Field(default_factory=_utc_now)
    updated_at: str = Field(default_factory=_utc_now)

    @field_validator("source_hash")
    @classmethod
    def validate_source_hash(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("source_hash must be sha256:<64 lowercase hexadecimal characters>")
        return value


class EvidenceBlock(IngestionContractModel):
    """A retrievable, source-linked unit of multimodal evidence."""

    evidence_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    parent_id: str | None = None
    modality: str = Field(min_length=1)
    content: str | None = None
    artifact_uri: str | None = None
    location: EvidenceLocation = Field(default_factory=EvidenceLocation)
    confidence: float = Field(ge=0, le=1)
    source_hash: str = Field(min_length=71, max_length=71)
    extractor_version: str = Field(min_length=1)
    model_version: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_hash")
    @classmethod
    def validate_source_hash(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("source_hash must be sha256:<64 lowercase hexadecimal characters>")
        return value

    @model_validator(mode="after")
    def validate_payload(self) -> "EvidenceBlock":
        if not (self.content and self.content.strip()) and not self.artifact_uri:
            raise ValueError("evidence block must contain content or artifact_uri")
        if not self.provenance:
            raise ValueError("evidence block provenance must not be empty")
        return self


class EvidenceRelationship(IngestionContractModel):
    """A deterministic edge between two source-linked evidence blocks."""

    relation_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    source_evidence_id: str = Field(min_length=1)
    target_evidence_id: str = Field(min_length=1)
    relation_type: Literal["contains", "temporal_next", "sequence_next", "references"]
    confidence: float = Field(ge=0, le=1)
    provenance: dict[str, Any] = Field(default_factory=dict)


class EvidenceChunk(IngestionContractModel):
    """Structure-aware retrieval unit with a complete evidence source map."""

    chunk_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    content: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    parent_chunk_id: str | None = None
    heading_path: list[str] = Field(default_factory=list)
    source_hash: str = Field(min_length=71, max_length=71)
    chunk_index: int = Field(ge=0)
    estimated_tokens: int = Field(ge=1)

    @field_validator("source_hash")
    @classmethod
    def validate_source_hash(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("source_hash must be sha256:<64 lowercase hexadecimal characters>")
        return value


class EvidenceCompilation(IngestionContractModel):
    """Compiled graph and chunks published by the structure stage."""

    document_id: str = Field(min_length=1)
    relationships: list[EvidenceRelationship] = Field(default_factory=list)
    chunks: list[EvidenceChunk] = Field(default_factory=list)
    source_map_complete: bool = False


class ExtractionEvent(IngestionContractModel):
    """Safe replayable progress event for one ingestion."""

    event_id: str = Field(min_length=1)
    ingestion_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    stage: str = Field(min_length=1)
    status: IngestionStatus
    progress: int = Field(default=0, ge=0, le=100)
    message: str = Field(default="", max_length=2000)
    evidence_ids: list[str] = Field(default_factory=list)
    error_code: str | None = None
    timestamp: str = Field(default_factory=_utc_now)


class IngestionQualityReport(IngestionContractModel):
    """Coverage and release decision for derived evidence."""

    quality_report_id: str = Field(min_length=1)
    ingestion_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    status: IngestionQualityStatus = "pending"
    coverage: dict[str, Any] = Field(default_factory=dict)
    block_counts: dict[str, int] = Field(default_factory=dict)
    low_confidence_count: int = Field(default=0, ge=0)
    fallback_count: int = Field(default=0, ge=0)
    fallbacks: list[str] = Field(default_factory=list)
    evidence_count: int = Field(default=0, ge=0)
    chunk_count: int = Field(default=0, ge=0)
    relationship_count: int = Field(default=0, ge=0)
    memory_projection_status: str = Field(default="pending")
    review_state: str = Field(default="unreviewed")
    warnings: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    source_map_complete: bool = False
    security_markers: list[str] = Field(default_factory=list)
    cache_hits: int = Field(default=0, ge=0)
    usage_is_estimate: bool = False
    created_at: str = Field(default_factory=_utc_now)


# Compatibility name used by the ticket and by ingestion-facing callers.
QualityReport = IngestionQualityReport

