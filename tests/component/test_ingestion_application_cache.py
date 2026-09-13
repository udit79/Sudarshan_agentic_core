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


def test_ingestion_status_projects_safe_usage_and_cache_receipts() -> None:
    app = object.__new__(SudarshanApplication)

    class _Scheduler:
        def status(self, _ingestion_id):
            return {
                "run_id": "ing-1",
                "task_id": "task-1",
                "case_id": "case-1",
                "status": "partial",
                "skill_result": {
                    "cache_status": "hit",
                    "budget": {"total_tokens": 0, "usage_is_estimate": True},
                    "usage": {"estimated_tokens": 4096, "actual_tokens": 0, "usage_is_estimate": True},
                    "fallback_count": 1,
                    "fallbacks": ["vision_provider_unavailable"],
                    "evidence_count": 2,
                    "chunk_count": 1,
                    "relationship_count": 1,
                },
            }

        def events(self, _ingestion_id):
            return []

    app.ingestion_scheduler = _Scheduler()
    status = app.ingestion_status("ing-1")

    assert status["quality_status"] == "partial"
    assert status["cache_status"] == "hit"
    assert status["usage"]["estimated_tokens"] == 4096
    assert status["fallbacks"] == ["vision_provider_unavailable"]
    assert status["evidence_count"] == 2


def test_memory_projection_failure_returns_partial_status_and_records_fallback(tmp_path) -> None:
    app = _app(tmp_path)

    class FailingMemoryManager:
        def remember(self, *args, **kwargs):
            raise ConnectionError("Simulated Cognee web connection timeout")

    app.orchestrator.memory_manager = FailingMemoryManager()
    result = app.ingest_path(
        "sample_data/sample_text.txt",
        source_reference="brief.txt",
        operator_id="user-1",
        user_id="user-1",
        case_id="case-1",
        task_id="task-failing-mem",
        ingestion_id="ing-failing-mem",
    )
    assert result["status"] == "partial"
    assert result["memory_persisted"] is False
    assert result["evidence_indexed"] is True
    assert result["fallback_count"] >= 1
    assert any("memory_projection_unavailable" in fb for fb in result["fallbacks"])

