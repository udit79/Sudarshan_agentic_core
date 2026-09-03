from datetime import datetime

from memory.model import Memory, MemoryType, Scope, ScopeType
from memory.memory_store import MemoryStore


def create_test_memory(memory_id: str, content: str) -> Memory:
    scope = Scope(
        ScopeType.USER,
        "user123",
    )

    now = datetime.now()

    return Memory(
        id=memory_id,
        content=content,
        scope=scope,
        memory_type=MemoryType.FACT,
        created_at=now,
        updated_at=now,
    )


def test_create_and_get_memory():
    store = MemoryStore()
    memory = create_test_memory("memory001", "Python preference")

    store.create_memory(memory)

    result = store.get_memory("memory001")

    assert result == memory


def test_get_nonexistent_memory():
    store = MemoryStore()

    result = store.get_memory("does_not_exist")

    assert result is None


def test_update_memory():
    store = MemoryStore()

    old_memory = create_test_memory(
        "memory001",
        "Old content",
    )

    new_memory = create_test_memory(
        "memory001",
        "New content",
    )

    store.create_memory(old_memory)
    store.update_memory(new_memory)

    result = store.get_memory("memory001")

    assert result is not None
    assert result == new_memory
    assert result.content == "New content"


def test_delete_memory():
    store = MemoryStore()

    memory = create_test_memory(
        "memory001",
        "Something",
    )

    store.create_memory(memory)
    store.delete_memory("memory001")

    result = store.get_memory("memory001")

    assert result is None


def test_list_memories():
    store = MemoryStore()

    memory1 = create_test_memory(
        "memory001",
        "First memory",
    )

    memory2 = create_test_memory(
        "memory002",
        "Second memory",
    )

    store.create_memory(memory1)
    store.create_memory(memory2)

    result = store.list()

    assert len(result) == 2
    assert memory1 in result
    assert memory2 in result