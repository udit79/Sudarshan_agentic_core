from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid
from ingestion_pipelines.contracts import EvidenceBlock, EvidenceChunk, EvidenceRelationship

@dataclass
class IngestedDocument:
    id: str
    source_path: str
    raw_text: str
    doc_type: str
    ingested_at: str
    user_id: str = None
    case_id: str = None
    task_id: str = None
    evidence_blocks: list[EvidenceBlock] = field(default_factory=list)
    relationships: list[EvidenceRelationship] = field(default_factory=list)
    chunks: list[EvidenceChunk] = field(default_factory=list)

    @staticmethod
    def create(source_path, raw_text, doc_type="text",
               user_id=None, case_id=None, task_id=None,
               document_id=None, evidence_blocks=None, relationships=None, chunks=None):
        return IngestedDocument(
            id=document_id or str(uuid.uuid4()),
            source_path=source_path,
            raw_text=raw_text,
            doc_type=doc_type,
            ingested_at=datetime.now(timezone.utc).isoformat(),
            user_id=user_id,
            case_id=case_id,
            task_id=task_id,
            evidence_blocks=list(evidence_blocks or []),
            relationships=list(relationships or []),
            chunks=list(chunks or []),
        )
