from __future__ import annotations

from time import sleep

import pytest

from pipelines.orchestrator.cache import CacheStore, build_cache_fingerprint, stable_hash


def fingerprint(**overrides):
    values = {
        "skill_id": "visual.flowchart",
        "skill_version": "1.0.0",
        "stage_contract": {"input_schema": "ContextPack", "output": ["diagram.ir"]},
        "input_artifact_hashes": ["a" * 64],
        "input_payload_hash": stable_hash({"query": "private request"}),
        "tool_provider_versions": {"layout": "1.2.0"},
        "model_policy": {"model": "test-model", "max_tokens": 1000},
        "authorization_scope": {"case_id": "case-1", "classification": "RESTRICTED"},
    }
    values.update(overrides)
    return build_cache_fingerprint(**values)


def test_fingerprint_changes_for_skill_policy_and_authorization_scope() -> None:
    original = fingerprint()
    assert fingerprint(skill_version="1.0.1") != original
    assert fingerprint(model_policy={"model": "test-model", "max_tokens": 900}) != original
    assert fingerprint(authorization_scope={"case_id": "case-2", "classification": "RESTRICTED"}) != original


def test_cache_requires_passed_quality_and_returns_only_live_entries() -> None:
    store = CacheStore(":memory:")
    key = fingerprint()

    with pytest.raises(ValueError):
        store.put(
            fingerprint=key,
            skill_id="visual.flowchart",
            skill_version="1.0.0",
            artifact_ids=["artifact-pending"],
            quality_report_id="quality-pending",
            quality_status="pending",
        )

    entry = store.put(
        fingerprint=key,
        skill_id="visual.flowchart",
        skill_version="1.0.0",
        artifact_ids=["artifact-passed"],
        quality_report_id="quality-passed",
        quality_status="passed",
        ttl_seconds=0.01,
        metadata={"renderer_version": "r1", "prompt": "must not be stored"},
    )
    assert entry.artifact_ids == ("artifact-passed",)
    assert store.get(key).quality_report_id == "quality-passed"
    assert "prompt" not in store.get(key).metadata
    sleep(0.02)
    assert store.get(key) is None


def test_cache_claim_prevents_stampede_and_reclaims_expired_lease() -> None:
    store = CacheStore(":memory:")
    key = fingerprint()
    first = store.try_claim(key, owner="worker-1", lease_seconds=0.01)
    assert first == "worker-1"
    assert store.try_claim(key, owner="worker-2", lease_seconds=1) is None
    sleep(0.02)
    assert store.try_claim(key, owner="worker-2", lease_seconds=1) == "worker-2"
    assert store.release_claim(key, "worker-1") is False
    assert store.release_claim(key, "worker-2") is True

