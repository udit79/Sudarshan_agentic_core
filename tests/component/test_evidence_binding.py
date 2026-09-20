from __future__ import annotations

from threading import Lock

import pytest

from ingestion_pipelines import ingest_file
from ingestion_pipelines.evidence_index import EvidenceIndex
from pipelines.common.contracts import AdvisoryRequest
from integrations.deepseek_harness.application import SudarshanApplication


def _request(*, user_id: str = "user-a", case_id: str = "case-a", task_id: str = "task-run"):
    return AdvisoryRequest(
        query="Prepare a grounded case briefing from the selected evidence.",
        user_id=user_id,
        case_id=case_id,
        task_id=task_id,
        token_budget=1500,
        requested_pipelines=("presentation",),
    )


def test_explicit_evidence_reference_builds_scoped_context_pack(tmp_path) -> None:
    source = tmp_path / "case-a.txt"
    source.write_text("CASE-A-ONLY: verified incident detail.", encoding="utf-8")
    document = ingest_file(
        str(source),
        user_id="user-a",
        case_id="case-a",
        task_id="task-ingest",
        source_reference="case-a.txt",
    )
    index = EvidenceIndex(tmp_path / "evidence.db")
    index.index_document(document)

    application = object.__new__(SudarshanApplication)
    application.evidence_index = index
    request = _request()

    refs, pack = application._bind_evidence_references(
        request,
        {"evidence_refs": [document.evidence_blocks[0].evidence_id]},
        run_id="run-a",
    )

    assert refs == [{"evidence_id": document.evidence_blocks[0].evidence_id}]
    assert pack is not None
    assert "CASE-A-ONLY" in pack["context_text"]
    assert pack["scope"] == {
        "user_id": "user-a",
        "case_id": "case-a",
        "task_id": "task-run",
    }
    record = pack["records"][0]
    assert record["scope_type"] == "case"
    assert record["scope_id"] == "case-a"
    assert record["provenance"]["source_task_id"] == "task-ingest"
    assert record["provenance"]["selection"] == "explicit_evidence_ref"


def test_same_case_evidence_can_be_used_by_later_task_with_provenance(tmp_path) -> None:
    source = tmp_path / "case-a.txt"
    source.write_text("Reusable case evidence.", encoding="utf-8")
    document = ingest_file(
        str(source),
        user_id="user-a",
        case_id="case-a",
        task_id="task-ingest",
    )
    index = EvidenceIndex(tmp_path / "evidence.db")
    index.index_document(document)
    application = object.__new__(SudarshanApplication)
    application.evidence_index = index

    refs, pack = application._bind_evidence_references(
        _request(task_id="task-generation"),
        {"evidence_refs": [document.evidence_blocks[0].evidence_id]},
        run_id="run-generation",
    )

    assert refs
    assert pack["records"][0]["content"] == "Reusable case evidence."
    assert pack["records"][0]["provenance"]["source_task_id"] == "task-ingest"


def test_foreign_user_or_case_evidence_is_rejected(tmp_path) -> None:
    source = tmp_path / "foreign.txt"
    source.write_text("FOREIGN-CASE-SECRET", encoding="utf-8")
    document = ingest_file(
        str(source),
        user_id="user-b",
        case_id="case-b",
        task_id="task-b",
    )
    index = EvidenceIndex(tmp_path / "evidence.db")
    index.index_document(document)
    application = object.__new__(SudarshanApplication)
    application.evidence_index = index

    with pytest.raises(PermissionError, match="not permitted or does not exist"):
        application._bind_evidence_references(
            _request(user_id="user-a", case_id="case-a"),
            {"evidence_refs": [document.evidence_blocks[0].evidence_id]},
            run_id="run-cross-scope",
        )


def test_document_selector_must_match_evidence_document(tmp_path) -> None:
    source = tmp_path / "case-a.txt"
    source.write_text("Case evidence.", encoding="utf-8")
    document = ingest_file(
        str(source),
        user_id="user-a",
        case_id="case-a",
        task_id="task-ingest",
    )
    index = EvidenceIndex(tmp_path / "evidence.db")
    index.index_document(document)
    application = object.__new__(SudarshanApplication)
    application.evidence_index = index

    with pytest.raises(ValueError, match="document_id does not match"):
        application._bind_evidence_references(
            _request(),
            {
                "evidence_refs": [
                    {
                        "evidence_id": document.evidence_blocks[0].evidence_id,
                        "document_id": "wrong-document",
                    }
                ]
            },
            run_id="run-document-mismatch",
        )


def test_prepare_persists_explicit_evidence_context_for_later_start(tmp_path) -> None:
    source = tmp_path / "case-a.txt"
    source.write_text("Preparation-visible case evidence.", encoding="utf-8")
    document = ingest_file(
        str(source),
        user_id="user-a",
        case_id="case-a",
        task_id="task-ingest",
    )

    class PreparationStore:
        def __init__(self) -> None:
            self.records: dict[str, dict] = {}

        def preparation_create_if_absent(self, key, fingerprint, record):
            self.records[key] = dict(record)
            return self.records[key]

    application = object.__new__(SudarshanApplication)
    application.evidence_index = EvidenceIndex(tmp_path / "evidence.db")
    application.evidence_index.index_document(document)
    application.orchestrator = type(
        "Orchestrator",
        (),
        {"registry": {"presentation": object()}},
    )()
    application.scheduler = PreparationStore()
    application._preparations = {}
    application._preparations_lock = Lock()

    result = application.prepare(
        {
            "query": "Prepare from the selected case evidence.",
            "user_id": "user-a",
            "case_id": "case-a",
            "task_id": "task-run",
            "idempotency_key": "prep-evidence-1",
            "requested_pipelines": ["presentation"],
            "evidence_refs": [document.evidence_blocks[0].evidence_id],
        },
        operator_id="user-a",
    )

    assert result["status"] == "prepared"
    stored = application.scheduler.records["prep-evidence-1"]
    assert stored["evidence_refs"] == [
        {"evidence_id": document.evidence_blocks[0].evidence_id}
    ]
    assert "Preparation-visible case evidence" in stored["context_pack"]["context_text"]
