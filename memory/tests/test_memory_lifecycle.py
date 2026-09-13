from datetime import datetime, timezone

import pytest

from memory import AccessContext, MemoryEventLog, MemoryLifecycle, MemoryManager
from memory.tests.test_memory_manager import FakeBackend, make_unit


def test_pending_review_memory_is_not_recalled_until_promoted() -> None:
    backend = FakeBackend()
    manager = MemoryManager(backend)
    context = AccessContext(user_id="user-1", case_id="case-1")

    receipt = manager.remember(
        make_unit(),
        context,
        lifecycle=MemoryLifecycle.PENDING_REVIEW,
    )

    response = manager.recall("latency risk", context)
    assert response.results == ()
    assert receipt.memory.lifecycle is MemoryLifecycle.PENDING_REVIEW


def test_explicit_supersession_removes_old_memory_from_recall() -> None:
    backend = FakeBackend()
    manager = MemoryManager(backend)
    context = AccessContext(user_id="user-1", case_id="case-1")

    old = manager.remember(make_unit("old", "latency is the primary risk"), context)
    new = manager.remember(
        make_unit("new", "latency is no longer the primary risk"),
        context,
        supersedes=[old.memory.id],
    )

    assert manager.store.get_memory(old.memory.id).lifecycle is MemoryLifecycle.SUPERSEDED
    response = manager.recall("latency risk", context)
    assert [item.memory_id for item in response.results] == [new.memory.id]


def test_forgetting_is_scope_checked_and_retracts_without_backend_purge() -> None:
    backend = FakeBackend()
    manager = MemoryManager(backend)
    owner = AccessContext(user_id="user-1", case_id="case-1")
    other = AccessContext(user_id="user-2", case_id="case-2")
    receipt = manager.remember(make_unit(), owner)

    with pytest.raises(PermissionError):
        manager.retract(receipt.memory.id, other)

    result = manager.forget(receipt.memory.id, owner)
    assert result["status"] == "retracted"
    assert manager.recall("latency", owner).results == ()
    assert manager.store.get_memory(receipt.memory.id).lifecycle is MemoryLifecycle.RETRACTED


def test_case_history_is_persisted_without_persisting_memory_content(tmp_path) -> None:
    path = tmp_path / "memory-events.jsonl"
    first = MemoryEventLog(path)
    context = AccessContext(user_id="user-1", case_id="case-1", task_id="task-1")
    first.append(
        "created",
        memory_id="mem-1",
        scope_type="case",
        scope_id="case-1",
        actor_id="user-1",
        safe_metadata={"case_id": "case-1", "memory_type": "fact"},
        created_at=datetime.now(timezone.utc),
    )

    reopened = MemoryEventLog(path)
    history = reopened.case_history(context.case_id, actor_id=context.user_id)

    assert [event.memory_id for event in history] == ["mem-1"]
    assert "content" not in path.read_text(encoding="utf-8")
