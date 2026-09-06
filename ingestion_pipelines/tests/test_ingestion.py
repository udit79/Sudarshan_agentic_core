from unittest.mock import patch
from ingestion_pipelines import ingest_file, to_access_context, to_knowledge_unit, IngestedDocument
from memory.model import KnowledgeUnit, ScopeType, SourceType
from memory.memory_manager import MemoryManager
from memory.tests.test_memory_manager import FakeBackend


def test_ingest_txt_file():
    doc = ingest_file("sample_data/sample_text.txt", user_id="user1", case_id="case1", task_id="task1")
    assert doc.doc_type == "text"
    assert "INCIDENT REPORT" in doc.raw_text
    assert doc.user_id == "user1"
    assert doc.case_id == "case1"
    assert doc.task_id == "task1"


def test_ingest_pptx_file():
    doc = ingest_file("sample_data/dummy_presentation.pptx", user_id="user1", case_id="case1", task_id="task1")
    assert doc.doc_type == "pptx"
    assert "Sudarshan Defense Briefing" in doc.raw_text
    assert "[Speaker Notes]:" in doc.raw_text
    assert "Welcome senior leadership" in doc.raw_text

    unit = to_knowledge_unit(doc)
    assert unit.source.source_type is SourceType.PPTX
    assert unit.source.source_reference == "sample_data/dummy_presentation.pptx"


def test_ingest_pdf_file():
    doc = ingest_file("sample_data/dsaqueue.pdf", user_id="user1", case_id="case1", task_id="task1")
    assert doc.doc_type == "pdf"
    assert "--- Page 1 ---" in doc.raw_text
    assert "Enqueue" in doc.raw_text

    unit = to_knowledge_unit(doc)
    assert unit.source.source_type is SourceType.PDF
    assert unit.source.source_reference == "sample_data/dsaqueue.pdf"


def test_ingest_video_file():
    doc = ingest_file("sample_data/sample_briefing.mp4", user_id="user1", case_id="case1", task_id="task1")
    assert doc.doc_type == "video"
    assert "VIDEO INTELLIGENCE TRANSCRIPT" in doc.raw_text
    assert "[00:00]" in doc.raw_text

    unit = to_knowledge_unit(doc)
    assert unit.source.source_type is SourceType.VIDEO
    assert unit.source.source_reference == "sample_data/sample_briefing.mp4"




def test_adapter_to_knowledge_unit_and_context():
    doc = ingest_file("sample_data/sample_text.txt", user_id="user1", case_id="case1", task_id="task1")
    unit = to_knowledge_unit(doc)
    context = to_access_context(doc)

    assert isinstance(unit, KnowledgeUnit)
    assert unit.unit_id == doc.id
    assert unit.source.source_type is SourceType.TEXT
    assert unit.source.source_reference == "sample_data/sample_text.txt"
    assert context.user_id == "user1"
    assert context.case_id == "case1"
    assert context.task_id == "task1"


def test_adapter_empty_document_raises():
    empty_doc = IngestedDocument.create(source_path="empty.txt", raw_text="   \n   ", doc_type="text")
    try:
        to_knowledge_unit(empty_doc)
        assert False, "Should have raised ValueError on empty content"
    except ValueError as err:
        assert "empty document" in str(err)


def test_adapter_unknown_doc_type_falls_back_to_other():
    doc = IngestedDocument.create(source_path="data.custom", raw_text="Valid content", doc_type="custom_unknown")
    unit = to_knowledge_unit(doc)
    assert unit.source.source_type is SourceType.OTHER


def test_ingestion_to_memory_manager_end_to_end():
    doc = ingest_file("sample_data/dummy_presentation.pptx", user_id="user1", case_id="case1")
    unit = to_knowledge_unit(doc)
    context = to_access_context(doc)

    backend = FakeBackend()
    manager = MemoryManager(backend)

    receipt = manager.remember(unit, context, scope_type=ScopeType.CASE)
    assert receipt.memory.scope.scope_type is ScopeType.CASE
    assert backend.writes[0]["node_sets"] == ["sudarshan:scope:case:case1"]

    recall_resp = manager.recall("advisory pipeline", context)
    assert len(recall_resp.results) == 1
    assert "Sudarshan Defense Briefing" in recall_resp.context.text
