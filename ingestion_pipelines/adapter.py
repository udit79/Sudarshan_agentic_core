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


def to_knowledge_unit(doc: IngestedDocument) -> KnowledgeUnit:
    content = doc.raw_text.strip() if doc.raw_text else ""
    if not content:
        raise ValueError(f"Cannot create KnowledgeUnit from empty document: {doc.source_path}")

    source = Source(
        source_id=doc.id,
        source_type=_safe_source_type(doc.doc_type),
        source_reference=doc.source_path,
    )
    return KnowledgeUnit(
        unit_id=doc.id,
        content=content,
        source=source,
        metadata={"doc_type": doc.doc_type},
        provenance={"source_path": doc.source_path, "ingested_at": doc.ingested_at},
        created_at=datetime.fromisoformat(doc.ingested_at),
    )


def to_access_context(doc: IngestedDocument) -> AccessContext:
    """Derives a valid AccessContext from an IngestedDocument."""
    return AccessContext(
        user_id=doc.user_id,
        case_id=doc.case_id,
        task_id=doc.task_id,
    )