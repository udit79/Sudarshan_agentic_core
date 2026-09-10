from ingestion_pipelines.models import IngestedDocument
from typing import TYPE_CHECKING
from uuid import uuid4
from pathlib import Path
from typing import Callable

if TYPE_CHECKING:
    from memory.memory_manager import MemoryManager
from ingestion_pipelines.extract import extract_text, VIDEO_EXTENSIONS

def ingest_file(
    file_path: str,
    user_id: str | None = None,
    case_id: str | None = None,
    task_id: str | None = None,
    memory_manager: "MemoryManager | None" = None,
    source_reference: str | None = None,
    stage_charger: Callable[[str, int, int, int], object] | None = None,
    usage_recorder: Callable[[str, str, str, int, int, bool], object] | None = None,
) -> IngestedDocument:
    document_id = str(uuid4())
    reference = source_reference or file_path
    evidence_blocks = []
    if Path(file_path).suffix.lower() in VIDEO_EXTENSIONS:
        from ingestion_pipelines.extract_video import extract_video_evidence, render_video_timeline

        evidence_blocks = extract_video_evidence(
            file_path,
            document_id=document_id,
            source_reference=reference,
            stage_charger=stage_charger,
            usage_recorder=usage_recorder,
        )
        raw_text = render_video_timeline(evidence_blocks, source_reference=Path(reference).name)
        doc_type = "video"
    else:
        raw_text, doc_type = extract_text(
            file_path,
            stage_charger=stage_charger,
            usage_recorder=usage_recorder,
        )
        from ingestion_pipelines.evidence import build_evidence_from_file

        evidence_blocks = build_evidence_from_file(
            raw_text,
            file_path=file_path,
            doc_type=doc_type,
            document_id=document_id,
            source_reference=reference,
        )
    from ingestion_pipelines.structure import compile_evidence_structure

    compilation = compile_evidence_structure(evidence_blocks) if evidence_blocks else None
    document = IngestedDocument.create(
        source_path=reference,
        raw_text=raw_text,
        doc_type=doc_type,
        user_id=user_id,
        case_id=case_id,
        task_id=task_id,
        document_id=document_id,
        evidence_blocks=evidence_blocks,
        relationships=compilation.relationships if compilation else [],
        chunks=compilation.chunks if compilation else [],
    )
    if memory_manager is not None:
        from ingestion_pipelines.adapter import to_access_context, to_knowledge_unit
        from memory import MemoryType, ScopeType

        context = to_access_context(document)
        scope_type = ScopeType.CASE if context.case_id else (
            ScopeType.USER if context.user_id else ScopeType.SYSTEM
        )
        memory_manager.remember(
            to_knowledge_unit(document),
            context,
            scope_type=scope_type,
            memory_type=MemoryType.FACT,
            run_in_background=False,
        )
    return document
