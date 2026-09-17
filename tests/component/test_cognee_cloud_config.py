from __future__ import annotations

import pytest

from memory.cognee_adapter import CogneeConfig, CogneeHttpAdapter


def test_cognee_cloud_requires_tenant_credentials(monkeypatch) -> None:
    monkeypatch.setenv("COGNEE_BACKEND", "cloud")
    monkeypatch.setenv("COGNEE_BASE_URL", "https://tenant.aws.cognee.ai")
    monkeypatch.setenv("COGNEE_API_KEY", "cloud-key")
    monkeypatch.setenv("COGNEE_TENANT_ID", "tenant-1")
    monkeypatch.setenv("COGNEE_DATASET_NAME", "sudarshan_memory")

    config = CogneeConfig.from_env()
    headers = CogneeHttpAdapter(config)._headers("application/json")

    assert config.backend == "cloud"
    assert config.base_url == "https://tenant.aws.cognee.ai"
    assert headers["X-Api-Key"] == "cloud-key"
    assert headers["X-Tenant-Id"] == "tenant-1"


@pytest.mark.parametrize(
    ("name", "value"),
    [("COGNEE_API_KEY", ""), ("COGNEE_TENANT_ID", "")],
)
def test_cognee_cloud_rejects_missing_credentials(monkeypatch, name: str, value: str) -> None:
    monkeypatch.setenv("COGNEE_BACKEND", "cloud")
    monkeypatch.setenv("COGNEE_BASE_URL", "https://tenant.aws.cognee.ai")
    monkeypatch.setenv("COGNEE_API_KEY", "cloud-key")
    monkeypatch.setenv("COGNEE_TENANT_ID", "tenant-1")
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match="required for Cognee Cloud"):
        CogneeConfig.from_env()


def test_local_cognee_requires_explicit_opt_in(monkeypatch) -> None:
    monkeypatch.setenv("COGNEE_BACKEND", "local")
    monkeypatch.setenv("COGNEE_BASE_URL", "http://localhost:8011")
    monkeypatch.delenv("COGNEE_API_KEY", raising=False)
    monkeypatch.delenv("COGNEE_TENANT_ID", raising=False)

    config = CogneeConfig.from_env()

    assert config.backend == "local"
    assert config.base_url == "http://localhost:8011"


def test_cognee_recall_uses_scope_preserving_chunk_search(monkeypatch) -> None:
    config = CogneeConfig(
        backend="cloud",
        base_url="https://tenant.aws.cognee.ai",
        api_key="cloud-key",
        tenant_id="tenant-1",
        dataset_name="sudarshan_memory",
    )
    adapter = CogneeHttpAdapter(config)
    captured = {}

    def fake_request(method, path, body, content_type, *, retry, max_retries=None):
        captured.update({
            "method": method,
            "path": path,
            "payload": __import__("json").loads(body.decode("utf-8")),
            "content_type": content_type,
            "retry": retry,
        })
        return []

    monkeypatch.setattr(adapter, "_request", fake_request)

    assert adapter.recall(
        query="case finding",
        node_sets=["sudarshan:scope:case:case-a"],
        dataset_name="sudarshan_memory",
        top_k=4,
    ) == []
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v1/recall"
    assert captured["payload"]["search_type"] == "CHUNKS"
    assert captured["payload"]["only_context"] is False
    assert captured["payload"]["node_name"] == ["sudarshan:scope:case:case-a"]
