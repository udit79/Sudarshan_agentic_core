"""API server tests."""

from fastapi.testclient import TestClient
from unittest.mock import patch
from api.server import app
from api.artifacts import ArtifactStore
from PIL import Image

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


def test_create_run_admits_to_scheduler_without_inline_background_execution():
    calls = []

    class FakeApplication:
        def list_pipelines(self):
            return ["executive_summary"]

        def submit(self, payload, *, operator_id):
            calls.append((payload, operator_id))
            return {
                "status": "queued",
                "run_id": "run-queued",
                "task_id": payload["task_id"],
                "pipeline": None,
                "pipelines": [],
            }

    with patch("api.server.get_application", return_value=FakeApplication()):
        response = client.post(
            "/runs",
            headers={"x-operator-id": "operator-1", "x-case-id": "case-1"},
            json={
                "query": "Create a summary",
                "user_id": "operator-1",
                "case_id": "case-1",
                "task_id": "task-queued",
            },
        )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert calls and calls[0][1] == "operator-1"


def test_create_run_maps_scheduler_run_conflict_to_409():
    class FakeApplication:
        def list_pipelines(self):
            return ["executive_summary"]

        def submit(self, payload, *, operator_id):
            from api.scheduler import SchedulerConflictError

            raise SchedulerConflictError("run_id was already used")

    with patch("api.server.get_application", return_value=FakeApplication()):
        response = client.post(
            "/runs",
            headers={"x-operator-id": "operator-1", "x-case-id": "case-1"},
            json={
                "query": "Create a summary",
                "user_id": "operator-1",
                "case_id": "case-1",
                "task_id": "task-conflict",
                "metadata": {"run_id": "run-existing"},
            },
        )

    assert response.status_code == 409


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


def test_async_ingestion_admits_video_without_waiting_for_extraction(tmp_path, monkeypatch):
    calls = []

    class FakeApplication:
        def submit_ingestion(self, payload, *, operator_id):
            calls.append((payload, operator_id))
            return {
                "status": "queued",
                "ingestion_id": "ing-demo",
                "source_reference": payload["source_reference"],
                "source_hash": payload["source_hash"],
                "modality": payload["modality"],
                "deduplicated": False,
            }

    monkeypatch.setenv("SUDARSHAN_INGESTION_STAGING_DIR", str(tmp_path))
    with patch("api.server.get_application", return_value=FakeApplication()):
        response = client.post(
            "/ingestions",
            headers={"x-operator-id": "operator-1", "Idempotency-Key": "video-1"},
            data={"case_id": "case-1", "task_id": "task-video"},
            files={"file": ("brief.mp4", b"\x00\x00\x00\x18ftypmp42", "video/mp4")},
        )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert calls and calls[0][1] == "operator-1"
    assert calls[0][0]["modality"] == "video"
    assert calls[0][0]["source_hash"].startswith("sha256:")


def test_artifact_manifest_and_download_routes_use_stable_artifact_id(tmp_path, monkeypatch):
    root = tmp_path / "artifacts"
    source = root / "presentations" / "brief.pptx"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"pptx fixture")
    monkeypatch.setattr("api.server.ARTIFACT_ROOT", root.resolve())
    monkeypatch.setattr("api.server.ARTIFACT_STORE", ArtifactStore(root))

    class FakeApplication:
        def status(self, run_id):
            return {
                "run_id": run_id,
                "status": "succeeded",
                "pipeline": "presentation",
                "classification_level": "RESTRICTED",
                "response": {"pipeline": "presentation", "artifact": {"path": str(source)}},
            }

    with patch("api.server.get_application", return_value=FakeApplication()):
        manifest_response = client.get("/artifacts/run-api/presentation/manifest")

    assert manifest_response.status_code == 200
    manifest = manifest_response.json()
    artifact_id = manifest["artifact_id"]

    manifest_by_id = client.get(f"/artifacts/{artifact_id}/manifest")
    download = client.get(f"/artifacts/{artifact_id}/download")

    assert manifest_by_id.status_code == 200
    assert manifest_by_id.json()["sha256"] == manifest["sha256"]
    assert download.status_code == 200
    assert download.content == b"pptx fixture"

    denied = client.get(
        f"/artifacts/{artifact_id}/download",
        headers={"x-classification-level": "UNCLASSIFIED"},
    )
    assert denied.status_code == 403


def test_artifact_preview_route_returns_safe_image_preview(tmp_path, monkeypatch):
    root = tmp_path / "artifacts"
    source = root / "images" / "brief.png"
    source.parent.mkdir(parents=True)
    Image.new("RGB", (10, 10), color=(20, 30, 40)).save(source)
    store = ArtifactStore(root)
    manifest = store.register(
        source,
        run_id="run-preview",
        kind="image",
        classification_level="RESTRICTED",
    )
    monkeypatch.setattr("api.server.ARTIFACT_ROOT", root.resolve())
    monkeypatch.setattr("api.server.ARTIFACT_STORE", store)

    response = client.get(f"/artifacts/{manifest.artifact_id}/preview")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.content == source.read_bytes()
