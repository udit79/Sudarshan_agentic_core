from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ingestion_pipelines.evidence import build_evidence_blocks
from ingestion_pipelines.evidence_index import EvidenceIndex
from ingestion_pipelines.extract import extract_text, validate_source
from ingestion_pipelines.ingest import ingest_file
from ingestion_pipelines.source_safety import SourceSafetyError, inspect_source
from integrations.deepseek_harness.application import SudarshanApplication
from memory import AccessContext


def _write_text(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def _inspection(path: Path, *, max_bytes: int = 2 * 1024 * 1024):
    return inspect_source(
        str(path),
        source_reference=path.name,
        max_bytes=max_bytes,
        user_id="user-1",
        case_id="case-1",
        task_id="task-1",
    )


def test_valid_text_file_is_extracted_with_scope_and_evidence(tmp_path: Path) -> None:
    path = _write_text(tmp_path, "valid.txt", "Verified report content.")

    inspection = _inspection(path)
    document = ingest_file(
        str(path),
        source_reference=path.name,
        user_id="user-1",
        case_id="case-1",
        task_id="task-1",
    )

    assert inspection.modality == "text"
    assert document.raw_text == "Verified report content."
    assert document.evidence_blocks[0].content == "Verified report content."
    assert (document.user_id, document.case_id, document.task_id) == (
        "user-1",
        "case-1",
        "task-1",
    )


@pytest.mark.parametrize("content", ["", " \t\n\r\n "])
def test_empty_or_whitespace_only_text_is_rejected_clearly(
    tmp_path: Path, content: str
) -> None:
    path = _write_text(tmp_path, "empty.txt", content)

    with pytest.raises(SourceSafetyError, match="source content is empty"):
        _inspection(path)


def test_short_input_is_preserved_without_generated_content(tmp_path: Path) -> None:
    path = _write_text(tmp_path, "short.txt", "OK")

    document = ingest_file(str(path), source_reference=path.name)

    # There is currently no semantic sufficiency policy. This characterization
    # test proves ingestion does not add text while that policy is undecided.
    assert document.raw_text == "OK"
    assert document.evidence_blocks[0].content == "OK"


def test_large_text_file_is_processed_with_exact_content(tmp_path: Path) -> None:
    content = ("0123456789abcdef" * 65_536)  # 1 MiB, safely below the default cap
    path = _write_text(tmp_path, "large.txt", content)

    inspection = _inspection(path)
    extracted, doc_type = extract_text(str(path))

    assert inspection.byte_size == len(content.encode("utf-8"))
    assert len(extracted) == len(content)
    assert doc_type == "text"


def test_extremely_large_text_file_is_rejected_before_reading_content(
    tmp_path: Path,
) -> None:
    """Use a sparse file to test the configured boundary without large I/O."""

    configured_limit = 50 * 1024 * 1024
    path = tmp_path / "extremely-large.txt"
    with path.open("wb") as source:
        source.seek(configured_limit)
        source.write(b"x")

    assert path.stat().st_size == configured_limit + 1
    with pytest.raises(SourceSafetyError, match="size limit"):
        inspect_source(
            str(path),
            source_reference=path.name,
            max_bytes=configured_limit,
        )


def test_malformed_file_is_rejected_at_admission(tmp_path: Path) -> None:
    path = _write_text(tmp_path, "broken.pdf", "This is not a PDF")

    with pytest.raises(SourceSafetyError, match="does not match its declared file type"):
        _inspection(path)


def test_unsupported_and_missing_files_are_rejected(tmp_path: Path) -> None:
    unsupported = _write_text(tmp_path, "data.csv", "a,b\n1,2")

    with pytest.raises(ValueError, match="Unsupported file type"):
        validate_source(str(unsupported))
    with pytest.raises(FileNotFoundError, match="Source file not found"):
        validate_source(str(tmp_path / "missing.txt"))


def test_duplicate_admission_uses_one_logical_ingestion(tmp_path: Path) -> None:
    # This is intentionally an admission-level check. The durable scheduler
    # owns duplicate protection; extraction is not run by this test.
    from tests.component.test_np10_ingestion import _build_test_app

    app = _build_test_app(tmp_path)
    path = _write_text(tmp_path, "duplicate.txt", "same source")
    payload = {
        "user_id": "user-1",
        "case_id": "case-1",
        "task_id": "task-1",
        "file_path": str(path),
        "source_reference": path.name,
    }

    first = app.submit_ingestion(payload, operator_id="user-1")
    second = app.submit_ingestion(payload, operator_id="user-1")

    assert second["ingestion_id"] == first["ingestion_id"]
    assert second["deduplicated"] is True


def test_same_content_has_same_hash_but_keeps_filename_provenance(tmp_path: Path) -> None:
    first = _write_text(tmp_path, "first-name.txt", "identical bytes")
    second = _write_text(tmp_path, "second-name.txt", "identical bytes")

    first_inspection = _inspection(first)
    second_inspection = _inspection(second)

    assert first_inspection.source_hash == second_inspection.source_hash
    assert first_inspection.source_reference != second_inspection.source_reference


def test_modified_source_gets_a_new_content_hash(tmp_path: Path) -> None:
    path = _write_text(tmp_path, "versioned.txt", "version one")
    first_hash = _inspection(path).source_hash

    path.write_text("version two", encoding="utf-8")
    second_hash = _inspection(path).source_hash

    assert first_hash != second_hash


def test_unicode_and_special_characters_round_trip(tmp_path: Path) -> None:
    content = "संकेत — café — 日本語 — emoji: 🔐\nkey=value & <safe>"
    path = _write_text(tmp_path, "unicode.txt", content)

    document = ingest_file(str(path), source_reference=path.name)

    assert document.raw_text == content
    assert document.evidence_blocks[0].content == content


def test_very_long_individual_line_is_not_truncated(tmp_path: Path) -> None:
    content = "header:" + ("x" * 200_000)
    path = _write_text(tmp_path, "long-line.txt", content)

    document = ingest_file(str(path), source_reference=path.name)

    assert document.raw_text == content
    assert document.evidence_blocks[0].content == content


def test_missing_and_invalid_ingestion_metadata_are_rejected(tmp_path: Path) -> None:
    path = _write_text(tmp_path, "metadata.txt", "metadata test")
    app = object.__new__(SudarshanApplication)

    missing_case = {
        "user_id": "user-1",
        "task_id": "task-1",
        "file_path": str(path),
        "source_reference": path.name,
    }
    with pytest.raises(ValueError, match="case_id"):
        app.submit_ingestion(missing_case, operator_id="user-1")

    invalid_classification = {
        "user_id": "user-1",
        "case_id": "case-1",
        "task_id": "task-1",
        "file_path": str(path),
        "source_reference": path.name,
        "classification_level": "NOT-A-CLASSIFICATION",
    }
    with pytest.raises(ValueError):
        app.submit_ingestion(invalid_classification, operator_id="user-1")


def test_extraction_failure_is_not_silently_converted_to_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write_text(tmp_path, "failure.txt", "extraction failure")

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic extractor failure")

    monkeypatch.setattr("ingestion_pipelines.ingest.extract_text", fail)

    with pytest.raises(RuntimeError, match="synthetic extractor failure"):
        ingest_file(str(path), source_reference=path.name)


def test_partial_extraction_is_labeled_as_fallback_evidence() -> None:
    blocks = build_evidence_blocks(
        "(Image OCR unavailable: provider is not configured)",
        doc_type="image",
        document_id="doc-partial",
        source_reference="image.png",
        source_hash="sha256:" + "a" * 64,
    )

    assert blocks[0].metadata["ocr_fallback"] is True
    assert blocks[0].metadata["fallback_reason"] == "vision_provider_unavailable"


def test_file_size_boundary_accepts_exact_limit_and_rejects_one_byte_over(
    tmp_path: Path,
) -> None:
    exact = _write_text(tmp_path, "exact.txt", "x" * 32)
    over = _write_text(tmp_path, "over.txt", "x" * 33)

    assert _inspection(exact, max_bytes=32).byte_size == 32
    with pytest.raises(SourceSafetyError, match="size limit"):
        _inspection(over, max_bytes=32)


def test_content_normalization_trims_evidence_but_preserves_raw_text(
    tmp_path: Path,
) -> None:
    content = "  line one\nline two  \n"
    path = _write_text(tmp_path, "normalized.txt", content)

    document = ingest_file(str(path), source_reference=path.name)

    assert document.raw_text == content
    assert document.evidence_blocks[0].content == "line one\nline two"


def test_provenance_and_scope_survive_indexing(tmp_path: Path) -> None:
    path = _write_text(tmp_path, "provenance.txt", "scoped provenance evidence")
    document = ingest_file(
        str(path),
        source_reference="operator-visible-name.txt",
        user_id="user-1",
        case_id="case-1",
        task_id="task-1",
    )
    index = EvidenceIndex(tmp_path / "evidence.db")
    index.index_document(document)

    result = index.search(
        "provenance",
        AccessContext(user_id="user-1", case_id="case-1", task_id="task-1"),
    )[0]

    assert result["source_reference"] == "operator-visible-name.txt"
    assert result["source_hash"].startswith("sha256:")
    assert result["user_id"] == "user-1"
    assert result["case_id"] == "case-1"
    assert result["task_id"] == "task-1"
    assert result["provenance"]["source_hash"] == result["source_hash"]


@pytest.mark.parametrize(
    ("relative_path", "expected_text", "expected_type"),
    [
        ("sample_data/sample_text.txt", "INCIDENT REPORT", "text"),
        ("sample_data/dsaqueue.pdf", "Enqueue", "pdf"),
        ("sample_data/dummy_presentation.pptx", "Sudarshan Defense Briefing", "pptx"),
    ],
)
def test_sanitized_repository_fixtures_extract_expected_content(
    relative_path: str, expected_text: str, expected_type: str
) -> None:
    document = ingest_file(
        relative_path,
        source_reference=Path(relative_path).name,
        user_id="user-fixture",
        case_id="case-fixture",
        task_id="task-fixture",
    )

    assert document.doc_type == expected_type
    assert expected_text in document.raw_text
    assert document.evidence_blocks
    assert all(block.content.strip() for block in document.evidence_blocks)
