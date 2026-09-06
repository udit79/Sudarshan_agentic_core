"""API server tests."""

from fastapi.testclient import TestClient
from unittest.mock import patch
from api.server import app

client = TestClient(app)

def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["memory_system"] == "connected"
    assert "pipelines" in data
    assert isinstance(data["pipelines"], list)

def test_list_pipelines():
    response = client.get("/pipelines")
    assert response.status_code == 200
    data = response.json()
    assert "pipelines" in data
    assert "advisory" in data["pipelines"]
    assert "video" in data["pipelines"]

def test_security_middleware():
    # POST requests should require x-operator-id
    response = client.post("/runs", json={"query": "test", "task_id": "test"})
    assert response.status_code == 401
    assert "Missing X-Operator-Id header" in response.text
    
    # Check headers on GET
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers.get("X-Classification-Level") == "RESTRICTED"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"


def test_ingest_endpoint_accepts_real_source_upload_and_returns_memory_receipt():
    class FakeApplication:
        def ingest_path(self, file_path, **kwargs):
            with open(file_path, "rb") as source:
                assert source.read() == b"INCIDENT REPORT"
            assert kwargs["source_reference"] == "brief.txt"
            assert kwargs["case_id"] == "case-1"
            return {
                "status": "succeeded",
                "document_id": "doc-1",
                "memory_persisted": True,
            }

    with patch("api.server.get_application", return_value=FakeApplication()):
        response = client.post(
            "/ingest",
            headers={"x-operator-id": "operator-1"},
            data={"case_id": "case-1"},
            files={"file": ("brief.txt", b"INCIDENT REPORT", "text/plain")},
        )

    assert response.status_code == 201
    assert response.json()["memory_persisted"] is True
