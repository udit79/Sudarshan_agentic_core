"""API server tests."""

from fastapi.testclient import TestClient
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
