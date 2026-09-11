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
