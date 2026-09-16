# injestion/adapter.py
"""Converts our IngestedDocument into the memory layer's KnowledgeUnit.
This is the ONLY place ingestion needs to know memory.model exists.
"""

from datetime import datetime

from ingestion_pipelines.models import IngestedDocument
from memory.model import KnowledgeUnit, Source, SourceType
from memory.scope_policy import AccessContext


def _safe_source_type(doc_type: str | None) -> SourceType:
    if not doc_type:
        return SourceType.OTHER
    try:
        return SourceType(doc_type.strip().lower())
    except (ValueError, AttributeError):
        return SourceType.OTHER


def to_knowledge_unit(
    doc: IngestedDocument,
    *,
    review_state: str = "unreviewed",
    quality_status: str = "passed",
    classification_level: str = "RESTRICTED",
) -> KnowledgeUnit:
    content = doc.raw_text.strip() if doc.raw_text else ""
    if not content:
        raise ValueError(f"Cannot create KnowledgeUnit from empty document: {doc.source_path}")

    source = Source(
        source_id=doc.id,
        source_type=_safe_source_type(doc.doc_type),
        source_reference=doc.source_path,
    )
    first_block = doc.evidence_blocks[0] if doc.evidence_blocks else None
    source_hash = first_block.source_hash if first_block else ""
    extractor_version = first_block.extractor_version if first_block else "ingestion@2"
    model_version = first_block.model_version if first_block else None

    fallbacks = sorted({
        str(reason)
        for block in doc.evidence_blocks
        for reason in (
            [block.metadata.get("fallback_reason")]
            if block.metadata.get("fallback_reason")
            else list(block.metadata.get("fallbacks") or [])
        )
        if reason
    })
    low_confidence_count = sum(1 for block in doc.evidence_blocks if block.confidence < 0.7)

    return KnowledgeUnit(
        unit_id=doc.id,
        content=content,
        source=source,
        metadata={
            "doc_type": doc.doc_type,
            "evidence_ids": [block.evidence_id for block in doc.evidence_blocks],
            "chunk_ids": [chunk.chunk_id for chunk in doc.chunks],
            "review_state": review_state,
            "quality_status": quality_status,
            "classification_level": classification_level,
            "fallbacks": fallbacks,
            "low_confidence_count": low_confidence_count,
            "extractor_version": extractor_version,
            "model_version": model_version,
            "source_reference": doc.source_path,
            "source_hash": source_hash,
        },
        provenance={
            "source_path": doc.source_path,
            "source_hash": source_hash,
            "ingested_at": doc.ingested_at,
            "extractor_version": extractor_version,
            "model_version": model_version,
            "source_map_complete": (
                bool(doc.evidence_blocks)
                and len(doc.evidence_blocks)
                == sum(len(chunk.evidence_ids) for chunk in doc.chunks)
                and {
                    block.evidence_id for block in doc.evidence_blocks
                }
                == {
                    evidence_id
                    for chunk in doc.chunks
                    for evidence_id in chunk.evidence_ids
                }
            ),
        },
        created_at=datetime.fromisoformat(doc.ingested_at),
    )


def to_access_context(doc: IngestedDocument) -> AccessContext:
    """Derives a valid AccessContext from an IngestedDocument."""
    return AccessContext(
        user_id=doc.user_id,
        case_id=doc.case_id,
        task_id=doc.task_id,
    )
