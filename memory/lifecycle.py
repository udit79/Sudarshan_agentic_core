"""Safe, content-free memory lifecycle events."""

from __future__ import annotations

from datetime import datetime
from threading import RLock
from typing import Any, Literal, Mapping
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


MemoryEventType = Literal[
    "created", "superseded", "retracted", "forgotten", "expired",
    "pending_review", "promoted", "lesson_recorded", "profile_updated",
]


class MemoryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1)
    event_type: MemoryEventType
    memory_id: str = Field(min_length=1)
    scope_type: str = Field(min_length=1)
    scope_id: str = Field(min_length=1)
    actor_id: str | None = None
    safe_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class MemoryEventLog:
    """Thread-safe local event projection; raw memory content never enters it."""

    def __init__(self) -> None:
        self._events: list[MemoryEvent] = []
        self._lock = RLock()

    def append(
        self,
        event_type: MemoryEventType,
        *,
        memory_id: str,
        scope_type: str,
        scope_id: str,
        actor_id: str | None = None,
        safe_metadata: Mapping[str, Any] | None = None,
        created_at: datetime,
    ) -> MemoryEvent:
        event = MemoryEvent(
            event_id=f"mevt_{uuid4().hex}",
            event_type=event_type,
            memory_id=memory_id,
            scope_type=scope_type,
            scope_id=scope_id,
            actor_id=actor_id,
            safe_metadata=dict(safe_metadata or {}),
            created_at=created_at,
        )
        with self._lock:
            self._events.append(event)
        return event

    def list(self, *, memory_id: str | None = None) -> list[MemoryEvent]:
        with self._lock:
            return [item for item in self._events if memory_id is None or item.memory_id == memory_id]


__all__ = ["MemoryEvent", "MemoryEventLog", "MemoryEventType"]
