from ingestion_pipelines.models import IngestedDocument
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from memory.memory_manager import MemoryManager
from ingestion_pipelines.extract import extract_text

def ingest_file(
    file_path: str,
    user_id: str | None = None,
    case_id: str | None = None,
    task_id: str | None = None,
    memory_manager: "MemoryManager | None" = None,
    source_reference: str | None = None,
) -> IngestedDocument:
    raw_text, doc_type = extract_text(file_path)
    document = IngestedDocument.create(
        source_path=source_reference or file_path,
        raw_text=raw_text,
        doc_type=doc_type,
        user_id=user_id,
        case_id=case_id,
        task_id=task_id,
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
