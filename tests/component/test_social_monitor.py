from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from integrations.providers.social import SocialReceipt
from integrations.providers.social_monitor import (
    SocialMonitorConflict,
    SocialMonitorStore,
    SocialThreadMonitorService,
)


class FakeThreadReader:
    def __init__(self, receipts: list[SocialReceipt]) -> None:
        self.receipts = receipts
        self.calls = 0

    def fetch_thread(self, target_ref: str, **kwargs):
        self.calls += 1
        return self.receipts.pop(0)


def _receipt(*, data=None, retry_after_seconds=None, error_code=None) -> SocialReceipt:
    return SocialReceipt(
        receipt_id=f"receipt-{error_code or 'ok'}", provider="test",
        operation="fetch_thread", status="succeeded" if error_code is None else "failed",
        target_ref="urn:thread:1", error_code=error_code,
        retry_after_seconds=retry_after_seconds, data=data or {},
    )


def test_monitor_requires_opt_in_and_valid_bounded_interval(tmp_path) -> None:
    reader = FakeThreadReader([])
    store = SocialMonitorStore(str(tmp_path / "monitors.db"))
    service = SocialThreadMonitorService(reader, store)
    scope = {"user_id": "user-1", "case_id": "case-1"}
    with pytest.raises(SocialMonitorConflict, match="opt-in"):
        service.start(
            provider="test", target_ref="urn:thread:1", authorization_scope=scope,
        )
    with pytest.raises(SocialMonitorConflict, match="between 30"):
        service.start(
            provider="test", target_ref="urn:thread:1", authorization_scope=scope,
            interval_seconds=5, opt_in=True,
        )
    with pytest.raises(SocialMonitorConflict, match="timezone"):
        service.start(
            provider="test", target_ref="urn:thread:1", authorization_scope=scope,
            start_at=datetime.now(), opt_in=True,
        )
    store.close()


def test_monitor_persists_scoped_poll_and_respects_retry_after(tmp_path) -> None:
    reader = FakeThreadReader([_receipt(retry_after_seconds=60)])
    path = str(tmp_path / "monitors.db")
    scope = {"user_id": "user-1", "case_id": "case-1"}
    store = SocialMonitorStore(path)
    service = SocialThreadMonitorService(reader, store)
    created = service.start(
        provider="test", target_ref="urn:thread:1", authorization_scope=scope,
        interval_seconds=30, start_at=datetime.now(timezone.utc) - timedelta(seconds=1), opt_in=True,
    )
    poll_now = (created.next_poll_at or 0) + 1
    observed = service.poll_due(authorization_scope=scope, now=poll_now)
    assert observed is not None
    assert observed.status == "active"
    assert observed.last_poll_at == poll_now
    assert observed.next_poll_at == poll_now + 60
    assert reader.calls == 1
    store.close()

    restarted = SocialMonitorStore(path)
    persisted = restarted.get(created.monitor_id)
    assert persisted is not None
    assert persisted.last_receipt is not None
    assert persisted.next_poll_at == poll_now + 60
    restarted.close()


def test_monitor_scope_mismatch_is_fail_closed_and_deleted_thread_stops(tmp_path) -> None:
    reader = FakeThreadReader([_receipt(data={"deleted": True})])
    store = SocialMonitorStore(str(tmp_path / "monitors.db"))
    service = SocialThreadMonitorService(reader, store)
    scope = {"user_id": "user-1", "case_id": "case-1"}
    created = service.start(
        provider="test", target_ref="urn:thread:1", authorization_scope=scope,
        interval_seconds=30, opt_in=True,
    )
    mismatch = service.poll_due(
        authorization_scope={"user_id": "user-1", "case_id": "case-2"}, now=time_now(store, created.monitor_id),
    )
    assert mismatch is not None
    assert mismatch.status == "paused"
    assert mismatch.non_actionable is True
    assert reader.calls == 0

    resumed = service.store.resume(created.monitor_id, now=2000)
    assert resumed.status == "active"
    deleted = service.poll_due(authorization_scope=scope, now=2000)
    assert deleted is not None
    assert deleted.status == "paused"
    assert deleted.non_actionable is True
    assert service.poll_due(authorization_scope=scope, now=3000) is None
    store.close()


def test_monitor_pause_cancel_and_restart_state_are_safe(tmp_path) -> None:
    store = SocialMonitorStore(str(tmp_path / "monitors.db"))
    service = SocialThreadMonitorService(FakeThreadReader([]), store)
    scope = {"user_id": "user-1", "case_id": "case-1"}
    created = service.start(
        provider="test", target_ref="urn:thread:1", authorization_scope=scope,
        interval_seconds=30, opt_in=True,
    )
    paused = store.pause(created.monitor_id)
    assert paused.status == "paused"
    assert store.claim_due(now=paused.next_poll_at or 1000) is None
    resumed = store.resume(created.monitor_id, now=1000)
    assert resumed.status == "active"
    cancelled = store.cancel(created.monitor_id)
    assert cancelled.status == "cancelled"
    with pytest.raises(SocialMonitorConflict, match="cannot resume"):
        store.resume(created.monitor_id, now=2000)
    store.close()


def test_monitor_reclaims_expired_poll_lease_after_worker_crash(tmp_path) -> None:
    store = SocialMonitorStore(str(tmp_path / "monitors.db"))
    service = SocialThreadMonitorService(FakeThreadReader([]), store)
    scope = {"user_id": "user-1", "case_id": "case-1"}
    created = service.start(
        provider="test", target_ref="urn:thread:1", authorization_scope=scope,
        interval_seconds=30, opt_in=True,
    )
    first = store.claim_due(worker_id="crashed-worker", lease_seconds=1, now=1000)
    assert first is None  # the real-time start is not due at synthetic time
    due_now = created.next_poll_at or 0
    first = store.claim_due(worker_id="crashed-worker", lease_seconds=1, now=due_now)
    assert first is not None
    recovered = store.claim_due(worker_id="recovery-worker", lease_seconds=30, now=due_now + 2)
    assert recovered is not None
    assert recovered.monitor_id == created.monitor_id
    receipt = _receipt()
    finished = store.finish(
        created.monitor_id, worker_id="recovery-worker", receipt=receipt,
        now=due_now + 2, next_poll_at=due_now + 32,
    )
    assert finished.status == "active"
    store.close()


def time_now(store: SocialMonitorStore, monitor_id: str) -> float:
    record = store.get(monitor_id)
    assert record is not None
    return record.next_poll_at or 0
