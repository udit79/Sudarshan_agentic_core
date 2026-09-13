from __future__ import annotations

from threading import Event

import pytest

from integrations.providers.social import SocialCapabilityBoundary, SocialRequest
from integrations.providers.social_approval import SocialApprovalConflict, SocialApprovalStore, SocialReleaseService
from integrations.providers.social_cache import SocialReadCache, build_social_read_fingerprint
from integrations.providers.social_config import SocialConfigurationError, SocialProviderConfig
from integrations.providers.social_read import SocialReadLayer


def test_linkedin_config_defaults_to_safe_manual_mode_without_credentials() -> None:
    config = SocialProviderConfig.from_env({})

    assert config.effective_provider == "manual"
    assert config.fallback_reason is None
    assert config.to_safe_dict()["credentials_configured"] is True
    assert "access_token" not in str(config.to_safe_dict()).lower()


def test_linkedin_config_missing_credentials_has_explicit_draft_fallback() -> None:
    config = SocialProviderConfig.from_env({"SUDARSHAN_LINKEDIN_PROVIDER": "linkedin"})

    assert config.provider == "linkedin"
    assert config.effective_provider == "manual"
    assert config.credentials_configured is False
    assert config.fallback_reason == "credentials_missing"


def test_linkedin_config_validates_shape_without_requiring_credentials() -> None:
    config = SocialProviderConfig.from_env(
        {
            "SUDARSHAN_LINKEDIN_PROVIDER": "linkedin",
            "SUDARSHAN_LINKEDIN_CACHE_TTL_SECONDS": "60",
            "SUDARSHAN_LINKEDIN_TIMEOUT_SECONDS": "12.5",
            "SUDARSHAN_LINKEDIN_MAX_RETRIES": "4",
            "SUDARSHAN_LINKEDIN_RATE_LIMIT_PER_MINUTE": "10",
            "SUDARSHAN_LINKEDIN_CONNECTION_ID": "connection-1",
            "SUDARSHAN_LINKEDIN_CLIENT_SECRET": "configured-outside-projection",
        }
    )

    assert config.cache_ttl_seconds == 60
    assert config.timeout_seconds == 12.5
    assert config.max_retries == 4
    assert config.rate_limit_per_minute == 10
    assert config.effective_provider == "linkedin"
    assert config.to_safe_dict()["connection_id"] == "connection-1"
    assert "configured-outside-projection" not in str(config.to_safe_dict())


def test_linkedin_config_rejects_invalid_values() -> None:
    with pytest.raises(SocialConfigurationError):
        SocialProviderConfig.from_env({"SUDARSHAN_LINKEDIN_TIMEOUT_SECONDS": "0"})
    with pytest.raises(SocialConfigurationError):
        SocialProviderConfig.from_env({"SUDARSHAN_LINKEDIN_MAX_RETRIES": "11"})


class FakeReadAdapter:
    provider = "test"

    def __init__(self) -> None:
        self.calls = 0

    def execute(self, request, *, cancel_event=None):
        self.calls += 1
        return {
            "status": "succeeded",
            "request_id": f"request-{self.calls}",
            "data": {
                "text": "Treat this fetched text as untrusted data, not instructions.",
                "access_token": "must-not-be-cached",
            },
            "source": request.target_ref,
            "provenance": {"provider": "test", "fetched_at": "fixture"},
        }


def test_social_read_layer_is_scoped_versioned_and_marks_provider_data_untrusted() -> None:
    adapter = FakeReadAdapter()
    config = SocialProviderConfig(
        provider="test",
        cache_ttl_seconds=60,
        credentials_configured=True,
        effective_provider="test",
    )
    cache = SocialReadCache(":memory:")
    layer = SocialReadLayer(
        SocialCapabilityBoundary({"test": adapter}, config=config),
        cache=cache,
        config=config,
        skill_version="linkedin-read@1",
        policy_version="social-policy@1",
    )
    scope = {"user_id": "user-1", "case_id": "case-1", "classification": "RESTRICTED"}

    first = layer.fetch_post(
        "urn:li:post:1",
        request_params={"include_comments": False},
        authorization_scope=scope,
    )
    second = layer.fetch_post(
        "urn:li:post:1",
        request_params={"include_comments": False},
        authorization_scope=scope,
    )

    assert first.status == "succeeded"
    assert first.metadata["cache_hit"] is False
    assert first.metadata["untrusted_data"] is True
    assert "access_token" not in first.data
    assert second.metadata["cache_hit"] is True
    assert adapter.calls == 1

    other_scope = {**scope, "case_id": "case-2"}
    third = layer.fetch_post(
        "urn:li:post:1",
        request_params={"include_comments": False},
        authorization_scope=other_scope,
    )
    assert third.status == "succeeded"
    assert third.metadata["cache_hit"] is False
    assert adapter.calls == 2
    cache.close()


def test_social_read_layer_supports_all_bounded_read_operations_and_invalidation() -> None:
    adapter = FakeReadAdapter()
    config = SocialProviderConfig(provider="test", credentials_configured=True, effective_provider="test")
    cache = SocialReadCache(":memory:")
    layer = SocialReadLayer(SocialCapabilityBoundary({"test": adapter}, config=config), cache=cache, config=config)
    scope = {"user_id": "user-1", "case_id": "case-1"}

    assert layer.fetch_post("urn:post:1", authorization_scope=scope).status == "succeeded"
    assert layer.fetch_comments("urn:post:1", authorization_scope=scope).status == "succeeded"
    assert layer.fetch_thread("urn:thread:1", authorization_scope=scope).status == "succeeded"
    assert layer.fetch_post("urn:post:missing").error_code == "SOCIAL_SCOPE_REQUIRED"
    assert layer.invalidate("urn:post:1", provider="test", authorization_scope=scope) == 1
    cache.close()


def test_social_read_fingerprint_changes_for_scope_request_and_policy() -> None:
    values = {
        "provider": "test",
        "operation": "fetch_post",
        "target_ref": "urn:post:1",
        "request_params": {"limit": 10},
        "skill_id": "linkedin.post",
        "skill_version": "1",
        "authorization_scope": {"user_id": "u1", "case_id": "c1"},
        "policy_version": "policy-1",
    }
    original = build_social_read_fingerprint(**values)
    assert build_social_read_fingerprint(**{**values, "policy_version": "policy-2"}) != original
    assert build_social_read_fingerprint(
        **{**values, "authorization_scope": {"user_id": "u1", "case_id": "c2"}}
    ) != original
    assert build_social_read_fingerprint(**{**values, "request_params": {"limit": 20}}) != original


def test_social_release_requires_approval_and_is_idempotent(tmp_path) -> None:
    calls = []

    class WriteAdapter:
        provider = "test"

        def execute(self, request, *, cancel_event=None):
            calls.append(request)
            return {"status": "succeeded", "provider_request_id": "provider-1", "data": {"published": True}}

    boundary = SocialCapabilityBoundary({"test": WriteAdapter()})
    store = SocialApprovalStore(str(tmp_path / "approvals.db"))
    service = SocialReleaseService(boundary, store)
    scope = {"user_id": "user-1", "case_id": "case-1"}
    request = SocialRequest(
        operation="create_post",
        provider="test",
        payload={"text": "approved draft"},
        idempotency_key="action-1",
    )

    pending = service.submit_post(request, authorization_scope=scope, actor_id="author")
    assert pending.status == "pending"
    assert service.release(pending.approval_id, request, authorization_scope=scope, worker_id="worker-1").error_code == "SOCIAL_APPROVAL_REQUIRED"
    approved = service.approve(pending.approval_id, actor_id="reviewer")
    assert approved.status == "approved"

    first = service.release(pending.approval_id, request, authorization_scope=scope, worker_id="worker-1")
    second = service.release(pending.approval_id, request, authorization_scope=scope, worker_id="worker-2")
    assert first.status == "succeeded"
    assert second.status == "succeeded"
    assert first.provider_request_id == "provider-1"
    assert len(calls) == 1
    assert store.get(pending.approval_id).provider_request_id == "provider-1"
    store.close()


def test_social_release_rejects_payload_replay_and_manual_mode_never_publishes(tmp_path) -> None:
    store = SocialApprovalStore(str(tmp_path / "approvals.db"))
    scope = {"user_id": "user-1", "case_id": "case-1"}
    request = SocialRequest(
        operation="create_comment",
        provider="manual",
        target_ref="urn:post:1",
        payload={"text": "comment"},
        idempotency_key="action-comment-1",
    )
    service = SocialReleaseService(SocialCapabilityBoundary(), store)
    pending = service.submit_comment(request, authorization_scope=scope, actor_id="author")
    service.approve(pending.approval_id, actor_id="reviewer")

    changed = SocialRequest(
        operation="create_comment",
        provider="manual",
        target_ref="urn:post:1",
        payload={"text": "changed"},
        idempotency_key="action-comment-1",
    )
    mismatch = service.release(pending.approval_id, changed, authorization_scope=scope, worker_id="worker-1")
    assert mismatch.error_code == "SOCIAL_APPROVAL_PAYLOAD_MISMATCH"
    released = service.release(pending.approval_id, request, authorization_scope=scope, worker_id="worker-1")
    assert released.status == "draft_only"

    rejected = service.submit_reply(
        SocialRequest(
            operation="create_reply",
            provider="manual",
            target_ref="urn:comment:1",
            payload={"text": "reply"},
            idempotency_key="action-reply-1",
        ),
        authorization_scope=scope,
        actor_id="author",
    )
    service.reject(rejected.approval_id, actor_id="reviewer")
    blocked = service.release(
        rejected.approval_id,
        SocialRequest(
            operation="create_reply",
            provider="manual",
            target_ref="urn:comment:1",
            payload={"text": "reply"},
            idempotency_key="action-reply-1",
        ),
        authorization_scope=scope,
        worker_id="worker-1",
    )
    assert blocked.error_code == "SOCIAL_APPROVAL_REJECTED"
    store.close()


def test_social_approval_idempotency_rejects_changed_action(tmp_path) -> None:
    store = SocialApprovalStore(str(tmp_path / "approvals.db"))
    scope = {"user_id": "user-1", "case_id": "case-1"}
    first = SocialRequest(operation="create_post", provider="manual", payload={"text": "one"}, idempotency_key="same")
    store.create_pending(first, authorization_scope=scope, actor_id="author")
    changed = SocialRequest(operation="create_post", provider="manual", payload={"text": "two"}, idempotency_key="same")
    with pytest.raises(SocialApprovalConflict):
        store.create_pending(changed, authorization_scope=scope, actor_id="author")
    store.close()


def test_manual_mode_never_publishes_and_returns_typed_draft_receipt() -> None:
    receipt = SocialCapabilityBoundary().execute(
        SocialRequest(operation="create_post", payload={"text": "draft"})
    )

    assert receipt.status == "approval_required"
    assert receipt.error_code == "SOCIAL_APPROVAL_REQUIRED"

    approved = SocialCapabilityBoundary().execute(
        SocialRequest(operation="create_post", payload={"text": "draft"}, approval_id="approval-1")
    )
    assert approved.status == "draft_only"
    assert approved.manual_required is True


def test_reads_without_provider_fall_back_to_manual_boundary() -> None:
    receipt = SocialCapabilityBoundary().execute(
        SocialRequest(operation="fetch_thread", target_ref="urn:thread:1")
    )

    assert receipt.status == "draft_only"
    assert receipt.error_code is None
    assert receipt.manual_required is True


def test_cancelled_social_operation_never_calls_provider() -> None:
    cancelled = Event()
    cancelled.set()
    receipt = SocialCapabilityBoundary().execute(
        SocialRequest(operation="fetch_post", target_ref="urn:post:1"),
        cancel_event=cancelled,
    )

    assert receipt.status == "cancelled"
