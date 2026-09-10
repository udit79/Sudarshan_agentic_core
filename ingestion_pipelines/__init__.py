"""Sudarshan Ingestion Layer."""

from ingestion_pipelines.adapter import to_access_context, to_knowledge_unit
from ingestion_pipelines.contracts import (
    EvidenceBlock,
    EvidenceChunk,
    EvidenceCompilation,
    EvidenceLocation,
    EvidenceRelationship,
    ExtractionEvent,
    IngestionBudget,
    IngestionManifest,
    IngestionQualityReport,
    QualityReport,
)
from ingestion_pipelines.extract import extract_text
from ingestion_pipelines.evidence import (
    EVIDENCE_ADAPTER_VERSION,
    build_evidence_blocks,
    build_evidence_from_file,
)
from ingestion_pipelines.structure import STRUCTURE_COMPILER_VERSION, compile_evidence_structure
from ingestion_pipelines.evidence_index import EvidenceIndex, EvidenceNotFoundError
from ingestion_pipelines.extract_video import (
    VIDEO_EXTRACTOR_VERSION,
    extract_video_evidence,
    render_video_timeline,
)
from ingestion_pipelines.ingest import ingest_file
from ingestion_pipelines.models import IngestedDocument
from ingestion_pipelines.source_safety import SourceInspection, SourceSafetyError, inspect_source
from ingestion_pipelines.runtime import (
    IngestionBudgetController,
    IngestionBudgetExceededError,
    IngestionBudgetSnapshot,
    IngestionStageCache,
    IngestionStageCacheEntry,
    IngestionUsageRecorder,
    build_ingestion_stage_fingerprint,
)

__all__ = [
    "IngestedDocument",
    "IngestionBudget",
    "IngestionManifest",
    "EvidenceBlock",
    "EvidenceChunk",
    "EvidenceCompilation",
    "EvidenceLocation",
    "EvidenceRelationship",
    "ExtractionEvent",
    "IngestionQualityReport",
    "QualityReport",
    "SourceInspection",
    "SourceSafetyError",
    "inspect_source",
    "extract_text",
    "EVIDENCE_ADAPTER_VERSION",
    "build_evidence_blocks",
    "build_evidence_from_file",
    "STRUCTURE_COMPILER_VERSION",
    "compile_evidence_structure",
    "EvidenceIndex",
    "EvidenceNotFoundError",
    "extract_video_evidence",
    "render_video_timeline",
    "VIDEO_EXTRACTOR_VERSION",
    "ingest_file",
    "to_access_context",
    "to_knowledge_unit",
    "IngestionBudgetController",
    "IngestionBudgetExceededError",
    "IngestionBudgetSnapshot",
    "IngestionStageCache",
    "IngestionStageCacheEntry",
    "IngestionUsageRecorder",
    "build_ingestion_stage_fingerprint",
]
