from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from ingestion_pipelines import ingest_file as real_ingest_file
from ingestion_pipelines.evidence_index import EvidenceIndex
from ingestion_pipelines.runtime import (
    IngestionBudgetController,
    IngestionStageCache,
    IngestionUsageRecorder,
)
from integrations.deepseek_harness.application import SudarshanApplication


class _MemoryManager:
    def remember(self, *args, **kwargs):
        return SimpleNamespace(memory=SimpleNamespace(id="memory-1"))


def _app(tmp_path):
    app = object.__new__(SudarshanApplication)
    app.ingestion_budget_controller = IngestionBudgetController()
    app.ingestion_usage = IngestionUsageRecorder()
    app.ingestion_stage_cache = IngestionStageCache(tmp_path / "stage-cache.db")
    app.evidence_index = EvidenceIndex(tmp_path / "evidence.db")
    app.orchestrator = SimpleNamespace(memory_manager=_MemoryManager())
    return app


def test_ingest_path_reuses_scoped_parser_stage_cache(tmp_path) -> None:
    app = _app(tmp_path)

    source = "sample_data/sample_text.txt"
    with patch("ingestion_pipelines.ingest_file", wraps=real_ingest_file) as extractor:
        first = app.ingest_path(
            source,
            source_reference="brief.txt",
            operator_id="user-1",
            user_id="user-1",
            case_id="case-1",
            task_id="task-1",
            ingestion_id="ing-1",
        )
        second = app.ingest_path(
            source,
            source_reference="brief.txt",
            operator_id="user-1",
            user_id="user-1",
            case_id="case-1",
            task_id="task-1",
            ingestion_id="ing-1",
        )

    assert extractor.call_count == 1
    assert first["cache_status"] == "miss"
    assert second["cache_status"] == "hit"
    assert second["document_id"] == first["document_id"]
    assert second["budget"]["total_tokens"] == 0


def test_optional_image_provider_failure_returns_partial_receipt(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("ingestion_pipelines.extract_image.load_env", lambda: None)
    result = _app(tmp_path).ingest_path(
        "sample_data/sample_ocr.png",
        source_reference="brief.png",
        operator_id="user-1",
        user_id="user-1",
        case_id="case-1",
        task_id="task-image",
        ingestion_id="ing-image",
    )

    assert result["status"] == "partial"
    assert result["fallback_count"] == 1
    assert result["fallbacks"] == ["vision_provider_unavailable"]
