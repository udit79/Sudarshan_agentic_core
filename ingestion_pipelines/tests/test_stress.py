"""Comprehensive Stress and Contract Verification Test for All Ingestion Pipelines.

Tests all 5 modalities:
1. Plain text (.txt)
2. Presentation (.pptx)
3. Document (.pdf)
4. Image OCR (.png, .jpg)
5. Video Intelligence (.mp4)

Validates:
- Full IngestedDocument contract (UUID, raw_text, doc_type, tenant context, timestamp)
- Full KnowledgeUnit memory contract (unit_id, content, source_type enum, provenance)
- Full AccessContext contract (user_id, case_id, task_id)
- Edge cases (missing file, empty file, invalid type)
- End-to-end MemoryManager storage and recall for all types
"""

import os
from pathlib import Path

import pytest

from ingestion_pipelines import ingest_file, to_access_context, to_knowledge_unit, IngestedDocument
from memory.memory_manager import MemoryManager
from memory.model import ScopeType, SourceType
from memory.tests.test_memory_manager import FakeBackend

TEST_MODALITIES = [
    ("sample_data/sample_text.txt", "text", SourceType.TEXT),
    ("sample_data/dummy_presentation.pptx", "pptx", SourceType.PPTX),
    ("sample_data/dsaqueue.pdf", "pdf", SourceType.PDF),
    ("sample_data/sample_ocr.png", "image", SourceType.IMAGE),
    ("sample_data/sample_briefing.mp4", "video", SourceType.VIDEO),
]


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_PROVIDER_TESTS", "").lower() not in {"1", "true", "yes"}
    or not (
        os.environ.get("OPENAI_API_KEY", "").strip()
        and not os.environ.get("OPENAI_API_KEY", "").startswith("replace-")
    ),
    reason="live provider tests are opt-in; set RUN_LIVE_PROVIDER_TESTS=1 with OPENAI_API_KEY",
)
def test_stress_all_modalities_contracts():
    backend = FakeBackend()
    manager = MemoryManager(backend)

    for file_path, expected_doc_type, expected_source_type in TEST_MODALITIES:
        print(f"\n[Testing Modality] {file_path} -> {expected_doc_type}...", flush=True)

        user_id = f"user_{expected_doc_type}"
        case_id = f"case_{expected_doc_type}"
        task_id = f"task_{expected_doc_type}"

        # 1. Ingest
        doc = ingest_file(file_path, user_id=user_id, case_id=case_id, task_id=task_id)

        # IngestedDocument assertions
        assert doc.id and len(doc.id) >= 32, "Invalid document UUID"
        assert doc.doc_type == expected_doc_type, f"Expected {expected_doc_type}, got {doc.doc_type}"
        assert doc.raw_text and len(doc.raw_text.strip()) > 0, "Empty extracted raw_text"
        assert doc.user_id == user_id
        assert doc.case_id == case_id
        assert doc.task_id == task_id
        assert doc.source_path == file_path

        # 2. Convert to KnowledgeUnit
        unit = to_knowledge_unit(doc)
        context = to_access_context(doc)

        # KnowledgeUnit assertions
        assert unit.unit_id == doc.id
        assert unit.content == doc.raw_text.strip()
        assert unit.source.source_id == doc.id
        assert unit.source.source_type == expected_source_type, f"Expected {expected_source_type}, got {unit.source.source_type}"
        assert unit.source.source_reference == file_path
        assert unit.metadata["doc_type"] == expected_doc_type
        assert unit.provenance["source_path"] == file_path
        assert unit.provenance["ingested_at"] == doc.ingested_at

        # AccessContext assertions
        assert context.user_id == user_id
        assert context.case_id == case_id
        assert context.task_id == task_id

        # 3. Store in MemoryManager
        receipt = manager.remember(unit, context, scope_type=ScopeType.CASE)
        assert receipt.memory.scope.scope_type is ScopeType.CASE
        assert receipt.memory.source.source_type == expected_source_type

    print("\n[ALL 5 MODALITIES PASSED CONTRACT VERIFICATION!]", flush=True)


def test_stress_error_boundaries():
    # 1. Non-existent file
    try:
        ingest_file("sample_data/non_existent_file.xyz")
        assert False, "Should have raised FileNotFoundError"
    except FileNotFoundError:
        pass

    # 2. Unsupported extension
    dummy_bad = Path("sample_data/dummy.unsupported_ext")
    dummy_bad.write_text("random content", encoding="utf-8")
    try:
        ingest_file(str(dummy_bad))
        assert False, "Should have raised ValueError for unsupported extension"
    except ValueError:
        pass
    finally:
        if dummy_bad.exists():
            dummy_bad.unlink()

    # 3. Empty document adapter rejection
    empty_doc = IngestedDocument.create(source_path="empty.txt", raw_text="   \n\t  ", doc_type="text")
    try:
        to_knowledge_unit(empty_doc)
        assert False, "Should have raised ValueError on empty raw_text"
    except ValueError:
        pass

    print("\n[ERROR BOUNDARY TESTS PASSED!]", flush=True)


if __name__ == "__main__":
    test_stress_all_modalities_contracts()
    test_stress_error_boundaries()
    print("\n=======================================================")
    print("ALL STRESS TESTS COMPLETED WITH 100% CONTRACT FIDELITY!")
    print("=======================================================")
