"""Small local store used for the Sudarshan contract and tests.

This is intentionally not the production knowledge database. The production
backend is Cognee; this store provides local idempotency and an inspectable
domain cache for callers that need it.
"""

from __future__ import annotations

from dataclasses import replace
from threading import RLock

from datetime import datetime

from memory.model import Memory, MemoryLifecycle, utc_now


class MemoryStore:
    def __init__(self) -> None:
        self._memory: dict[str, Memory] = {}
        self._lock = RLock()

    @property
    def memory(self) -> dict[str, Memory]:
        """Compatibility view; callers receive a snapshot, not live internals."""

        with self._lock:
            return dict(self._memory)

    def create_memory(self, single_memory: Memory) -> None:
        """Create a record; identical replays are treated as idempotent."""

        with self._lock:
            existing = self._memory.get(single_memory.id)
            if existing is not None and existing != single_memory:
                raise ValueError(f"memory already exists with id {single_memory.id!r}")
            self._memory[single_memory.id] = single_memory

    def get_memory(self, memory_id: str) -> Memory | None:
        with self._lock:
            return self._memory.get(memory_id)

    def update_memory(self, new_memory: Memory) -> None:
        with self._lock:
            if new_memory.id not in self._memory:
                raise KeyError(new_memory.id)
            self._memory[new_memory.id] = new_memory

    def upsert_memory(self, memory: Memory) -> None:
        with self._lock:
            self._memory[memory.id] = memory

    def delete_memory(self, memory_id: str) -> None:
        with self._lock:
            self._memory.pop(memory_id, None)

    def list(self) -> list[Memory]:
        with self._lock:
            return list(self._memory.values())

    def transition(
        self,
        memory_id: str,
        lifecycle: MemoryLifecycle,
        *,
        superseded_by: str | None = None,
    ) -> Memory:
        """Apply an auditable local lifecycle transition."""

        with self._lock:
            existing = self._memory.get(memory_id)
            if existing is None:
                raise KeyError(memory_id)
            updated = replace(
                existing,
                lifecycle=MemoryLifecycle(lifecycle),
                superseded_by=superseded_by,
                updated_at=utc_now(),
                metadata={
                    **dict(existing.metadata),
                    "lifecycle": MemoryLifecycle(lifecycle).value,
                    **({"superseded_by": superseded_by} if superseded_by else {}),
                },
            )
            self._memory[memory_id] = updated
            return updated

    def is_recallable(self, memory_id: str | None) -> bool:
        """Return false for locally known non-active memories."""

        if not memory_id:
            return True
        with self._lock:
            memory = self._memory.get(memory_id)
            return (
                memory is None
                or (
                    memory.lifecycle is MemoryLifecycle.ACTIVE
                    and (memory.expires_at is None or memory.expires_at > utc_now())
                )
            )

    def expire_due(self, *, now: datetime | None = None) -> list[Memory]:
        """Mark due records expired while retaining their audit rows."""

        cutoff = now or utc_now()
        expired: list[Memory] = []
        with self._lock:
            for memory in list(self._memory.values()):
                if memory.lifecycle is MemoryLifecycle.ACTIVE and memory.expires_at is not None and memory.expires_at <= cutoff:
                    expired.append(self.transition(memory.id, MemoryLifecycle.EXPIRED))
        return expired
