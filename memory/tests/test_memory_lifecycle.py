import pytest

from memory import AccessContext, MemoryLifecycle, MemoryManager
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
