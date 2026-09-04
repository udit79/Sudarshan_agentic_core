from unittest.mock import patch
from injestion import ingest_file, to_access_context, to_knowledge_unit, IngestedDocument
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


def test_ingest_image_with_ocr():
    with patch("pytesseract.image_to_string", return_value="SECURITY CAMERA LOG: SECTOR 7"):
        doc = ingest_file("sample_data/sample_ocr.png", user_id="user1", case_id="case1")
        assert doc.doc_type == "image"
        assert "SECURITY CAMERA LOG" in doc.raw_text

        unit = to_knowledge_unit(doc)
        assert unit.source.source_type is SourceType.IMAGE
        assert unit.source.source_reference == "sample_data/sample_ocr.png"


def test_ingestion_to_memory_manager_end_to_end():
    doc = ingest_file("sample_data/sample_text.txt", user_id="user1", case_id="case1")
    unit = to_knowledge_unit(doc)
    context = to_access_context(doc)

    backend = FakeBackend()
    manager = MemoryManager(backend)

    receipt = manager.remember(unit, context, scope_type=ScopeType.CASE)
    assert receipt.memory.scope.scope_type is ScopeType.CASE
    assert backend.writes[0]["node_sets"] == ["sudarshan:scope:case:case1"]

    recall_resp = manager.recall("relay downtime", context)
    assert len(recall_resp.results) == 1
    assert "relay B7" in recall_resp.context.text
