from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from api.server import app


client = TestClient(app)


def test_http_ingest_rejects_empty_text_with_clear_error() -> None:
    response = client.post(
        "/ingest",
        headers={"x-operator-id": "operator-1", "x-case-id": "case-1"},
        files={"file": ("empty.txt", b"", "text/plain")},
    )

    assert response.status_code == 415
    assert response.json()["detail"] == "source content is empty"


def test_http_ingest_rejects_unsupported_file_type() -> None:
    response = client.post(
        "/ingest",
        headers={"x-operator-id": "operator-1", "x-case-id": "case-1"},
        files={"file": ("data.csv", b"a,b\n1,2", "text/csv")},
    )

    assert response.status_code == 415
    assert "Unsupported file type" in response.json()["detail"]


def test_http_async_ingest_preserves_uploaded_content_and_scope(tmp_path, monkeypatch) -> None:
    received: dict[str, object] = {}

    class FakeApplication:
        def submit_ingestion(self, payload, *, operator_id):
            with open(payload["file_path"], "rb") as source:
                received["content"] = source.read()
            received["payload"] = payload
            received["operator_id"] = operator_id
            return {
                "status": "queued",
                "ingestion_id": "ing-http-test",
                "source_reference": payload["source_reference"],
                "source_hash": payload["source_hash"],
                "modality": payload["modality"],
                "deduplicated": False,
            }

    monkeypatch.setenv("SUDARSHAN_INGESTION_STAGING_DIR", str(tmp_path))
    with patch("api.server.get_application", return_value=FakeApplication()):
        response = client.post(
            "/ingestions",
            headers={"x-operator-id": "operator-1", "x-case-id": "case-1"},
            data={"task_id": "task-http"},
            files={"file": ("brief.txt", b"HTTP evidence", "text/plain")},
        )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert received["content"] == b"HTTP evidence"
    assert received["operator_id"] == "operator-1"
    payload = received["payload"]
    assert payload["user_id"] == "operator-1"
    assert payload["case_id"] == "case-1"
    assert payload["task_id"] == "task-http"
    assert payload["source_reference"] == "brief.txt"
    assert str(payload["source_hash"]).startswith("sha256:")


def test_http_run_accepts_evidence_refs_at_admission_boundary(monkeypatch) -> None:
    received: dict[str, object] = {}

    class FakeApplication:
        def list_pipelines(self):
            return ["presentation"]

        def submit(self, payload, *, operator_id):
            received["payload"] = payload
            received["operator_id"] = operator_id
            return {
                "status": "queued",
                "run_id": "run-evidence-boundary",
                "task_id": payload["task_id"],
                "pipelines": ["presentation"],
            }

    with patch("api.server.get_application", return_value=FakeApplication()):
        response = client.post(
            "/runs",
            headers={
                "x-operator-id": "user-a",
                "x-case-id": "case-a",
            },
            json={
                "query": "Summarize the selected evidence.",
                "user_id": "user-a",
                "case_id": "case-a",
                "task_id": "task-run",
                "requested_pipelines": ["presentation"],
                "evidence_refs": [{"evidence_id": "evidence-a1"}],
            },
        )

    assert response.status_code == 202
    assert received["operator_id"] == "user-a"
    assert received["payload"]["evidence_refs"] == [{"evidence_id": "evidence-a1"}]
