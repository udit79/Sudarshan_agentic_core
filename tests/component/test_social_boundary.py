from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Event

import pytest

from integrations.providers.social import SocialCapabilityBoundary, SocialReceipt, SocialRequest
from integrations.providers.social_approval import SocialApprovalConflict, SocialApprovalStore, SocialReleaseService
from integrations.providers.social_cache import SocialReadCache, build_social_read_fingerprint
from integrations.providers.social_config import SocialConfigurationError, SocialProviderConfig
from integrations.providers.social_fixtures import build_social_fixture_adapters
from integrations.providers.social_read import SocialReadLayer
from integrations.providers.social_schedule import SocialScheduleConflict, SocialScheduleService, SocialScheduleStore


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


def test_schedule_requires_timezone_and_survives_store_restart(tmp_path) -> None:
    naive = datetime.now()
    with pytest.raises(ValueError, match="timezone"):
        SocialRequest(
            operation="schedule_post",
            provider="manual",
            payload={"text": "scheduled"},
            idempotency_key="schedule-naive",
            scheduled_for=naive,
        )

    scope = {"user_id": "user-1", "case_id": "case-1"}
    request = SocialRequest(
        operation="schedule_post",
        provider="manual",
        payload={"text": "scheduled"},
        idempotency_key="schedule-restart",
        scheduled_for=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    approval_store = SocialApprovalStore(str(tmp_path / "approvals.db"))
    schedule_path = str(tmp_path / "schedules.db")
    service = SocialScheduleService(
        SocialReleaseService(SocialCapabilityBoundary(), approval_store),
        SocialScheduleStore(schedule_path),
    )
    created = service.submit(request, authorization_scope=scope, actor_id="author")
    assert created.status == "pending_approval"
    service.store.close()

    restarted_store = SocialScheduleStore(schedule_path)
    restarted = restarted_store.get(created.schedule_id)
    assert restarted is not None
    assert restarted.approval_id == created.approval_id
    assert restarted.status == "pending_approval"
    restarted_store.close()
    approval_store.close()


def test_schedule_approval_due_release_is_idempotent_and_restart_safe(tmp_path) -> None:
    calls = []

    class ScheduleAdapter:
        provider = "test"

        def execute(self, request, *, cancel_event=None):
            calls.append(request)
            return {"status": "succeeded", "provider_request_id": "scheduled-provider-1"}

    scope = {"user_id": "user-1", "case_id": "case-1"}
    request = SocialRequest(
        operation="schedule_post",
        provider="test",
        payload={"text": "publish later"},
        idempotency_key="schedule-publish-1",
        scheduled_for=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    approval_store = SocialApprovalStore(str(tmp_path / "approvals.db"))
    schedule_path = str(tmp_path / "schedules.db")
    release = SocialReleaseService(SocialCapabilityBoundary({"test": ScheduleAdapter()}), approval_store)
    store = SocialScheduleStore(schedule_path)
    service = SocialScheduleService(release, store)
    created = service.submit(request, authorization_scope=scope, actor_id="author")
    service.approve(created.schedule_id, actor_id="reviewer")

    store.close()
    restarted = SocialScheduleStore(schedule_path)
    restarted_service = SocialScheduleService(release, restarted)
    result = restarted_service.release_due(authorization_scope=scope, worker_id="worker-1")
    assert result is not None
    assert result.status == "succeeded"
    assert result.receipt["provider_request_id"] == "scheduled-provider-1"
    assert restarted_service.release_due(authorization_scope=scope, worker_id="worker-2") is None
    assert len(calls) == 1
    restarted.close()
    approval_store.close()


def test_schedule_cancel_blocks_provider_release(tmp_path) -> None:
    class NeverCalledAdapter:
        provider = "test"

        def execute(self, request, *, cancel_event=None):
            raise AssertionError("cancelled schedule reached provider")

    scope = {"user_id": "user-1", "case_id": "case-1"}
    request = SocialRequest(
        operation="schedule_post",
        provider="test",
        payload={"text": "cancel me"},
        idempotency_key="schedule-cancel-1",
        scheduled_for=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    approvals = SocialApprovalStore(str(tmp_path / "approvals.db"))
    store = SocialScheduleStore(str(tmp_path / "schedules.db"))
    service = SocialScheduleService(
        SocialReleaseService(SocialCapabilityBoundary({"test": NeverCalledAdapter()}), approvals), store
    )
    created = service.submit(request, authorization_scope=scope, actor_id="author")
    cancelled = service.cancel(created.schedule_id, actor_id="operator")
    assert cancelled.status == "cancelled"
    with pytest.raises(SocialApprovalConflict, match="cancelled"):
        service.approve(created.schedule_id, actor_id="reviewer")
    assert service.release_due(authorization_scope=scope, worker_id="worker-1") is None
    store.close()
    approvals.close()


def test_schedule_retries_provider_pending_after_retry_hint(tmp_path) -> None:
    class PendingThenSuccessAdapter:
        provider = "test"

        def __init__(self):
            self.calls = 0

        def execute(self, request, *, cancel_event=None):
            self.calls += 1
            if self.calls == 1:
                return {"status": "pending", "retry_after_seconds": 5, "request_id": "pending-1"}
            return {"status": "succeeded", "provider_request_id": "provider-2"}

    adapter = PendingThenSuccessAdapter()
    scope = {"user_id": "user-1", "case_id": "case-1"}
    request = SocialRequest(
        operation="schedule_post",
        provider="test",
        payload={"text": "retry me"},
        idempotency_key="schedule-retry-1",
        scheduled_for=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    approvals = SocialApprovalStore(str(tmp_path / "approvals.db"))
    store = SocialScheduleStore(str(tmp_path / "schedules.db"))
    service = SocialScheduleService(
        SocialReleaseService(SocialCapabilityBoundary({"test": adapter}), approvals), store
    )
    created = service.submit(request, authorization_scope=scope, actor_id="author")
    service.approve(created.schedule_id, actor_id="reviewer")
    pending = service.release_due(authorization_scope=scope, worker_id="worker-1")
    assert pending is not None
    assert pending.status == "provider_pending"
    assert pending.next_attempt_at is not None
    assert pending.receipt["retry_after_seconds"] == 5.0
    finished = service.release_due(
        authorization_scope=scope, worker_id="worker-1", now=pending.next_attempt_at + 1
    )
    assert finished is not None
    assert finished.status == "succeeded"
    assert adapter.calls == 2
    store.close()
    approvals.close()


def test_schedule_reclaims_expired_worker_lease_after_crash(tmp_path) -> None:
    approvals = SocialApprovalStore(str(tmp_path / "approvals.db"))
    store = SocialScheduleStore(str(tmp_path / "schedules.db"))
    scope = {"user_id": "user-1", "case_id": "case-1"}
    request = SocialRequest(
        operation="schedule_post", provider="manual", payload={"text": "recover me"},
        idempotency_key="schedule-reclaim-1",
        scheduled_for=datetime.fromtimestamp(900, tz=timezone.utc),
    )
    service = SocialScheduleService(
        SocialReleaseService(SocialCapabilityBoundary(), approvals), store
    )
    created = service.submit(request, authorization_scope=scope, actor_id="author")
    service.approve(created.schedule_id, actor_id="reviewer")

    first_claim = store.claim_due(worker_id="crashed-worker", lease_seconds=1, now=1000)
    assert first_claim is not None
    assert first_claim.status == "running"
    assert first_claim.attempts == 1
    recovered = store.claim_due(worker_id="recovery-worker", lease_seconds=30, now=1002)
    assert recovered is not None
    assert recovered.schedule_id == created.schedule_id
    assert recovered.attempts == 2
    receipt = SocialReceipt(
        receipt_id="recovered", provider="manual", operation="schedule_post",
        status="draft_only", target_ref="", manual_required=True,
    )
    finished = store.finish(
        created.schedule_id, worker_id="recovery-worker", status="draft_only", receipt=receipt,
    )
    assert finished.status == "draft_only"
    store.close()
    approvals.close()


def test_offline_social_fixture_set_emits_boundary_receipts_without_credentials() -> None:
    adapters = build_social_fixture_adapters()
    assert set(adapters) == {"manual", "mcp", "success", "retry", "timeout", "quota", "rate_limit", "authorization"}

    success = SocialCapabilityBoundary({"success": adapters["success"]}).execute(
        SocialRequest(operation="fetch_post", provider="success", target_ref="urn:post:1")
    )
    assert success.status == "succeeded"
    assert success.provider_request_id == "provider-1"
    assert adapters["success"].calls == 1

    pending = SocialCapabilityBoundary({"mcp": adapters["mcp"]}).execute(
        SocialRequest(operation="fetch_post", provider="mcp", target_ref="urn:post:1")
    )
    assert pending.status == "pending"
    assert pending.request_id == "mcp-request-1"

    rate_limited = SocialCapabilityBoundary({"retry": build_social_fixture_adapters()["retry"]}).execute(
        SocialRequest(operation="fetch_post", provider="retry", target_ref="urn:post:1")
    )
    assert rate_limited.retry_after_seconds == 30

    timeout = SocialCapabilityBoundary({"timeout": adapters["timeout"]}).execute(
        SocialRequest(operation="fetch_post", provider="timeout", target_ref="urn:post:1", timeout_seconds=0.001)
    )
    assert timeout.error_code == "SOCIAL_TIMEOUT"
    assert timeout.failure_class == "timeout"

    for name, expected in (("quota", "quota_exhausted"), ("rate_limit", "rate_limit"), ("authorization", "auth")):
        receipt = SocialCapabilityBoundary({name: adapters[name]}).execute(
            SocialRequest(operation="fetch_post", provider=name, target_ref="urn:post:1")
        )
        assert receipt.failure_class == expected
        assert receipt.status == "failed"


def test_social_boundary_preserves_retry_hint_from_provider_exception() -> None:
    class RateLimitError(RuntimeError):
        retry_after_seconds = 12

    class FailingAdapter:
        provider = "test"

        def execute(self, request, *, cancel_event=None):
            raise RateLimitError("429 rate limit")

    receipt = SocialCapabilityBoundary({"test": FailingAdapter()}).execute(
        SocialRequest(operation="fetch_thread", provider="test", target_ref="urn:thread:1")
    )
    assert receipt.status == "failed"
    assert receipt.failure_class == "rate_limit"
    assert receipt.retry_after_seconds == 12.0
