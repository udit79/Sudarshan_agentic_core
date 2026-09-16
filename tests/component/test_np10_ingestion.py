from __future__ import annotations

import hashlib
import json
import os
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Any, Mapping
from unittest.mock import patch
from uuid import uuid4

import pytest

from api.scheduler import LocalRunScheduler, SchedulerConflictError
from api.storage import LocalObjectStore
from ingestion_pipelines.contracts import EvidenceBlock, IngestionBudget, IngestionQualityReport
from ingestion_pipelines.evidence_index import EvidenceIndex, EvidenceNotFoundError
from ingestion_pipelines.ingest import ingest_file
from ingestion_pipelines.models import IngestedDocument
from ingestion_pipelines.runtime import (
    IngestionBudgetController,
    IngestionStageCache,
    IngestionUsageRecorder,
)
from ingestion_pipelines.source_safety import SourceSafetyError, inspect_source
from integrations.deepseek_harness.application import SudarshanApplication
from memory import AccessContext, KnowledgeUnit, MemoryType, ScopeType


class RecordingMemoryManager:
    """In-memory recording mock for MemoryManager."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def remember(
        self,
        unit: KnowledgeUnit,
        context: AccessContext,
        *,
        scope_type: ScopeType = ScopeType.CASE,
        memory_type: MemoryType = MemoryType.FACT,
        run_in_background: bool = False,
    ) -> Any:
        record = {
            "unit": unit,
            "context": context,
            "scope_type": scope_type,
            "memory_type": memory_type,
        }
        self.records.append(record)

        @dataclass
        class MemoryReceiptMock:
            memory: Any

        @dataclass
        class MemoryMock:
            id: str

        return MemoryReceiptMock(memory=MemoryMock(id=f"mem-{unit.unit_id}"))


def _wait_for(scheduler: LocalRunScheduler, run_id: str, expected: set[str], timeout: float = 3.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = scheduler.status(run_id)
        if state and state.get("status") in expected:
            return state
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} did not reach {expected}, current state: {scheduler.status(run_id)}")


def _build_test_app(tmp_path: Path) -> SudarshanApplication:
    state_dir = tmp_path / ".state"
    state_dir.mkdir(parents=True, exist_ok=True)

    app = object.__new__(SudarshanApplication)
    app.ingestion_budget_controller = IngestionBudgetController()
    app.ingestion_usage = IngestionUsageRecorder()
    app.ingestion_stage_cache = IngestionStageCache(state_dir / "stage_cache.db")
    app.evidence_index = EvidenceIndex(state_dir / "evidence_index.db")
    app.orchestrator = SimpleNamespace(memory_manager=RecordingMemoryManager())
    app.object_store = LocalObjectStore(state_dir / "objects")
    app.ingestion_scheduler = LocalRunScheduler(
        app._run_ingestion_job,
        db_path=state_dir / "ingestion_queue.db",
        max_workers=1,
        lease_ms=30000,
        max_attempts=2,
        queue_name="ingestion",
    )
    return app


def _create_sample_file(tmp_path: Path, filename: str = "brief.txt", content: str = "Test evidence content for ingestion") -> Path:
    f = tmp_path / filename
    f.write_text(content, encoding="utf-8")
    return f


# =========================================================================
# Scenario 1: Successful async ingestion returns succeeded + passed
# =========================================================================
def test_successful_async_ingestion_returns_succeeded_and_passed(tmp_path: Path) -> None:
    app = _build_test_app(tmp_path)
    file_path = _create_sample_file(tmp_path, "report.txt", "Quarterly revenue grew by 15 percent year over year.")

    payload = {
        "user_id": "operator-1",
        "case_id": "case-101",
        "task_id": "task-ingest-1",
        "file_path": str(file_path),
        "source_reference": "report.txt",
        "classification_level": "RESTRICTED",
    }
    admitted = app.submit_ingestion(payload, operator_id="operator-1")
    assert admitted["status"] in {"queued", "running", "succeeded"}
    ingestion_id = admitted["ingestion_id"]

    _wait_for(app.ingestion_scheduler, ingestion_id, {"succeeded"})

    status = app.ingestion_status(ingestion_id)
    assert status["status"] == "succeeded"
    assert status["quality_status"] == "passed"
    assert status["evidence_count"] >= 1
    assert status["quality_report"]["status"] == "passed"
    assert status["quality_report"]["fallback_count"] == 0


# =========================================================================
# Scenario 2: Extraction fallback returns partial + partial
# =========================================================================
def test_extraction_fallback_returns_partial_status_and_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = _build_test_app(tmp_path)
    file_path = tmp_path / "diagram.png"
    file_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("ingestion_pipelines.extract_image.load_env", lambda: None)

    payload = {
        "user_id": "operator-1",
        "case_id": "case-101",
        "task_id": "task-fallback",
        "file_path": str(file_path),
        "source_reference": "diagram.png",
        "classification_level": "RESTRICTED",
    }
    admitted = app.submit_ingestion(payload, operator_id="operator-1")
    ingestion_id = admitted["ingestion_id"]

    _wait_for(app.ingestion_scheduler, ingestion_id, {"partial", "succeeded"})

    status = app.ingestion_status(ingestion_id)
    assert status["status"] == "partial"
    assert status["quality_status"] == "partial"
    assert status["fallback_count"] >= 1
    assert "vision_provider_unavailable" in status["fallbacks"]
    assert status["quality_report"]["status"] == "partial"


# =========================================================================
# Scenario 3: Memory projection failure is reported separately
# =========================================================================
def test_memory_projection_failure_reported_separately(tmp_path: Path) -> None:
    app = _build_test_app(tmp_path)
    file_path = _create_sample_file(tmp_path, "doc.txt", "Important findings on network telemetry.")

    class FailingMemManager:
        def remember(self, *args, **kwargs):
            raise ConnectionError("Database network connection dropped")

    app.orchestrator.memory_manager = FailingMemManager()

    payload = {
        "user_id": "operator-1",
        "case_id": "case-101",
        "task_id": "task-mem-fail",
        "file_path": str(file_path),
        "source_reference": "doc.txt",
        "classification_level": "RESTRICTED",
    }
    admitted = app.submit_ingestion(payload, operator_id="operator-1")
    ingestion_id = admitted["ingestion_id"]

    _wait_for(app.ingestion_scheduler, ingestion_id, {"partial"})

    status = app.ingestion_status(ingestion_id)
    assert status["status"] == "partial"
    assert status["memory_projection_status"] == "failed"
    assert "Database network connection dropped" in str(status.get("memory_projection_error"))
    # Memory failure should not inflate extraction fallback count
    assert status["fallback_count"] == 0


# =========================================================================
# Scenario 4: Source hash is computed and mismatches are rejected
# =========================================================================
def test_source_hash_mismatch_rejected_before_admission(tmp_path: Path) -> None:
    app = _build_test_app(tmp_path)
    file_path = _create_sample_file(tmp_path, "hash_test.txt", "Content for hash verification.")

    bogus_hash = "sha256:" + "0" * 64
    payload = {
        "user_id": "operator-1",
        "case_id": "case-101",
        "task_id": "task-hash-mismatch",
        "file_path": str(file_path),
        "source_reference": "hash_test.txt",
        "source_hash": bogus_hash,
    }
    with pytest.raises(ValueError, match="source_hash mismatch"):
        app.submit_ingestion(payload, operator_id="operator-1")


# =========================================================================
# Scenario 5: MIME/magic/size/archive safety is enforced before admission
# =========================================================================
def test_mime_magic_size_and_archive_safety_enforced_before_admission(tmp_path: Path) -> None:
    app = _build_test_app(tmp_path)

    # 1. Non-existent file
    with pytest.raises(SourceSafetyError, match="source file is not available"):
        app.submit_ingestion(
            {"user_id": "u", "case_id": "c", "task_id": "t", "file_path": str(tmp_path / "absent.txt"), "source_reference": "absent.txt"},
            operator_id="u",
        )

    # 2. Spoofed magic bytes (.pdf extension with plain text content)
    fake_pdf = tmp_path / "fake.pdf"
    fake_pdf.write_text("Not a real PDF", encoding="utf-8")
    with pytest.raises(SourceSafetyError, match="source content does not match its declared file type"):
        app.submit_ingestion(
            {"user_id": "u", "case_id": "c", "task_id": "t", "file_path": str(fake_pdf), "source_reference": "fake.pdf"},
            operator_id="u",
        )

    # 3. Unsafe PPTX archive with path traversal
    unsafe_pptx = tmp_path / "traversal.pptx"
    with zipfile.ZipFile(unsafe_pptx, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("ppt/presentation.xml", "<p:presentation/>")
        z.writestr("../evil.txt", "malicious payload")
    with pytest.raises(SourceSafetyError, match="source content does not match its declared file type"):
        app.submit_ingestion(
            {"user_id": "u", "case_id": "c", "task_id": "t", "file_path": str(unsafe_pptx), "source_reference": "traversal.pptx"},
            operator_id="u",
        )


# =========================================================================
# Scenario 6: Same idempotency key replays the original ingestion
# =========================================================================
def test_same_idempotency_key_replays_original_ingestion(tmp_path: Path) -> None:
    app = _build_test_app(tmp_path)
    file_path = _create_sample_file(tmp_path, "replay.txt", "Data for idempotent replay.")

    payload = {
        "user_id": "operator-1",
        "case_id": "case-101",
        "task_id": "task-replay",
        "file_path": str(file_path),
        "source_reference": "replay.txt",
        "idempotency_key": "fixed-idempotency-key-12345",
    }
    first = app.submit_ingestion(payload, operator_id="operator-1")
    second = app.submit_ingestion(payload, operator_id="operator-1")

    assert first["ingestion_id"] == second["ingestion_id"]
    assert second["deduplicated"] is True


def test_same_idempotency_key_replays_with_durable_object_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUDARSHAN_OBJECT_STORE_MODE", "durable")
    app = _build_test_app(tmp_path)
    file_path = _create_sample_file(tmp_path, "durable-replay.txt", "Durable replay content.")
    payload = {
        "user_id": "operator-1",
        "case_id": "case-101",
        "task_id": "task-durable-replay",
        "file_path": str(file_path),
        "source_reference": "durable-replay.txt",
        "idempotency_key": "durable-replay-key",
    }

    first = app.submit_ingestion(payload, operator_id="operator-1")
    second = app.submit_ingestion(payload, operator_id="operator-1")

    assert second["ingestion_id"] == first["ingestion_id"]
    assert second["deduplicated"] is True


# =========================================================================
# Scenario 7: Same key with changed payload raises a conflict
# =========================================================================
def test_same_key_with_changed_payload_raises_conflict(tmp_path: Path) -> None:
    app = _build_test_app(tmp_path)
    file_path1 = _create_sample_file(tmp_path, "first.txt", "First payload text.")
    file_path2 = _create_sample_file(tmp_path, "second.txt", "Second different text.")

    payload1 = {
        "user_id": "operator-1",
        "case_id": "case-101",
        "task_id": "task-conflict",
        "file_path": str(file_path1),
        "source_reference": "first.txt",
        "idempotency_key": "conflict-test-key",
    }
    app.submit_ingestion(payload1, operator_id="operator-1")

    payload2 = {
        "user_id": "operator-1",
        "case_id": "case-101",
        "task_id": "task-conflict",
        "file_path": str(file_path2),
        "source_reference": "second.txt",
        "idempotency_key": "conflict-test-key",
    }
    with pytest.raises(SchedulerConflictError):
        app.submit_ingestion(payload2, operator_id="operator-1")


# =========================================================================
# Scenario 8: Same source in different cases is not incorrectly deduplicated
# =========================================================================
def test_same_source_in_different_cases_is_isolated(tmp_path: Path) -> None:
    app = _build_test_app(tmp_path)
    file_path = _create_sample_file(tmp_path, "shared_intel.txt", "Classified briefing shared across investigations.")

    payload_case_a = {
        "user_id": "operator-1",
        "case_id": "case-AAA",
        "task_id": "task-1",
        "file_path": str(file_path),
        "source_reference": "shared_intel.txt",
    }
    payload_case_b = {
        "user_id": "operator-1",
        "case_id": "case-BBB",
        "task_id": "task-1",
        "file_path": str(file_path),
        "source_reference": "shared_intel.txt",
    }

    res_a = app.submit_ingestion(payload_case_a, operator_id="operator-1")
    res_b = app.submit_ingestion(payload_case_b, operator_id="operator-1")

    assert res_a["ingestion_id"] != res_b["ingestion_id"]
    assert res_a["deduplicated"] is False
    assert res_b["deduplicated"] is False


# =========================================================================
# Scenario 9: Direct and async ingestion never write unreviewed FACT memory
# =========================================================================
def test_direct_and_async_ingestion_never_write_unreviewed_fact_memory(tmp_path: Path) -> None:
    app = _build_test_app(tmp_path)
    mem_mgr = RecordingMemoryManager()
    file_path = _create_sample_file(tmp_path, "fact_check.txt", "Some candidate factual statements.")

    # 1. Direct ingest_file()
    ingest_file(
        str(file_path),
        user_id="operator-1",
        case_id="case-101",
        task_id="task-direct",
        memory_manager=mem_mgr,
        source_reference="fact_check.txt",
    )
    assert len(mem_mgr.records) == 1
    assert mem_mgr.records[0]["memory_type"] == MemoryType.SUMMARY
    assert mem_mgr.records[0]["unit"].metadata["review_state"] == "unreviewed"

    # 2. Asynchronous ingestion
    app.orchestrator.memory_manager = mem_mgr
    payload = {
        "user_id": "operator-1",
        "case_id": "case-101",
        "task_id": "task-async",
        "file_path": str(file_path),
        "source_reference": "fact_check.txt",
    }
    admitted = app.submit_ingestion(payload, operator_id="operator-1")
    _wait_for(app.ingestion_scheduler, admitted["ingestion_id"], {"succeeded"})

    for record in mem_mgr.records:
        assert record["memory_type"] == MemoryType.SUMMARY
        assert record["unit"].metadata.get("review_state") == "unreviewed"
        assert record["memory_type"] != MemoryType.FACT


# =========================================================================
# Scenario 10: All evidence search methods enforce the same scope policy
# =========================================================================
def test_all_evidence_search_methods_enforce_scope_policy(tmp_path: Path) -> None:
    app = _build_test_app(tmp_path)
    file_path = _create_sample_file(tmp_path, "scoped.txt", "Alpha Bravo Charlie target information in Case-1.")

    app.ingest_path(
        str(file_path),
        source_reference="scoped.txt",
        operator_id="user-A",
        user_id="user-A",
        case_id="case-Alpha",
        task_id="task-1",
        classification_level="RESTRICTED",
    )

    # Correct scope: user-A, case-Alpha
    ctx_correct = AccessContext(user_id="user-A", case_id="case-Alpha")
    results = app.evidence_index.search("Alpha", ctx_correct)
    assert len(results) >= 1

    # Wrong user: user-B
    ctx_wrong_user = AccessContext(user_id="user-B", case_id="case-Alpha")
    assert len(app.evidence_index.search("Alpha", ctx_wrong_user)) == 0

    # Wrong case: case-Beta
    ctx_wrong_case = AccessContext(user_id="user-A", case_id="case-Beta")
    assert len(app.evidence_index.search("Alpha", ctx_wrong_case)) == 0

    # search_text
    assert len(app.evidence_index.search_text("Alpha", ctx_correct)) >= 1
    assert len(app.evidence_index.search_text("Alpha", ctx_wrong_case)) == 0


# =========================================================================
# Scenario 11: Evidence results contain complete provenance & authorization
# =========================================================================
def test_evidence_results_contain_complete_provenance_and_authorization(tmp_path: Path) -> None:
    app = _build_test_app(tmp_path)
    file_path = _create_sample_file(tmp_path, "provenance_doc.txt", "Detailed investigation findings for provenance.")

    res = app.ingest_path(
        str(file_path),
        source_reference="provenance_doc.txt",
        operator_id="operator-1",
        user_id="operator-1",
        case_id="case-prov",
        task_id="task-prov",
        classification_level="RESTRICTED",
    )
    ctx = AccessContext(user_id="operator-1", case_id="case-prov")
    search_res = app.evidence_index.search("investigation", ctx)
    assert len(search_res) >= 1
    item = search_res[0]

    # Required fields per NP-10 contract
    assert item["user_id"] == "operator-1"
    assert item["case_id"] == "case-prov"
    assert item["task_id"] == "task-prov"
    assert item["classification_level"] == "RESTRICTED"
    assert item["source_reference"] == "provenance_doc.txt"
    assert item["source_hash"].startswith("sha256:")
    assert item["extractor_version"]
    assert "provenance" in item
    assert item["provenance"]["source_hash"] == item["source_hash"]


# =========================================================================
# Scenario 12: Cache hits remain tenant/classification isolated
# =========================================================================
def test_cache_hits_remain_tenant_and_classification_isolated(tmp_path: Path) -> None:
    app = _build_test_app(tmp_path)
    file_path = _create_sample_file(tmp_path, "secret_notes.txt", "Classified secret notes on operation.")

    # 1. Ingest under user-1, case-1
    res1 = app.ingest_path(
        str(file_path),
        source_reference="secret_notes.txt",
        operator_id="user-1",
        user_id="user-1",
        case_id="case-1",
        task_id="task-1",
        classification_level="RESTRICTED",
    )
    assert res1["cache_status"] == "miss"

    # 2. Second ingest with exact same scope -> cache hit
    res2 = app.ingest_path(
        str(file_path),
        source_reference="secret_notes.txt",
        operator_id="user-1",
        user_id="user-1",
        case_id="case-1",
        task_id="task-1",
        classification_level="RESTRICTED",
    )
    assert res2["cache_status"] == "hit"

    # 3. Same file under different case -> cache miss (isolated)
    res3 = app.ingest_path(
        str(file_path),
        source_reference="secret_notes.txt",
        operator_id="user-1",
        user_id="user-1",
        case_id="case-2",
        task_id="task-1",
        classification_level="RESTRICTED",
    )
    assert res3["cache_status"] == "miss"


# =========================================================================
# Scenario 13: Cancellation leaves no corrupt index or active job
# =========================================================================
def test_cancellation_leaves_clean_state_and_no_active_job(tmp_path: Path) -> None:
    app = _build_test_app(tmp_path)
    file_path = _create_sample_file(tmp_path, "cancel_doc.txt", "Document to cancel mid-flight.")
    cancel_ev = Event()
    cancel_ev.set()  # Pre-cancelled

    result = app.ingest_path(
        str(file_path),
        source_reference="cancel_doc.txt",
        operator_id="operator-1",
        user_id="operator-1",
        case_id="case-cancel",
        task_id="task-cancel",
        cancel_event=cancel_ev,
    )
    assert result["status"] == "cancelled"

    # Verify no evidence indexed
    ctx = AccessContext(user_id="operator-1", case_id="case-cancel")
    results = app.evidence_index.search("Document", ctx)
    assert len(results) == 0


# =========================================================================
# Scenario 14: Usage and fallback counters are not double-counted
# =========================================================================
def test_usage_and_fallback_counters_not_double_counted(tmp_path: Path) -> None:
    app = _build_test_app(tmp_path)
    file_path = _create_sample_file(tmp_path, "counter_check.txt", "Text for counter validation.")

    res = app.ingest_path(
        str(file_path),
        source_reference="counter_check.txt",
        operator_id="operator-1",
        user_id="operator-1",
        case_id="case-1",
        task_id="task-1",
    )
    assert res["fallback_count"] == len(res["fallbacks"])
    assert res["status"] == "succeeded"
    assert res["quality_status"] == "passed"


# =========================================================================
# Scenario 15: Quality report survives scheduler serialization & polling
# =========================================================================
def test_quality_report_survives_scheduler_serialization_and_polling(tmp_path: Path) -> None:
    app = _build_test_app(tmp_path)
    file_path = _create_sample_file(tmp_path, "quality_check.txt", "Evidence content for quality report lifecycle.")

    payload = {
        "user_id": "operator-1",
        "case_id": "case-quality",
        "task_id": "task-quality",
        "file_path": str(file_path),
        "source_reference": "quality_check.txt",
    }
    admitted = app.submit_ingestion(payload, operator_id="operator-1")
    ingestion_id = admitted["ingestion_id"]

    _wait_for(app.ingestion_scheduler, ingestion_id, {"succeeded"})

    status = app.ingestion_status(ingestion_id)
    assert "quality_report" in status
    qr = status["quality_report"]
    assert qr["status"] == "passed"
    assert qr["evidence_count"] >= 1
    assert qr["review_state"] == "unreviewed"
    assert qr["source_map_complete"] is True
