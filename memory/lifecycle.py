"""Safe, content-free memory lifecycle events."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
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
    """Thread-safe event projection with optional append-only persistence.

    Only safe identifiers, scopes, lifecycle states, and bounded metadata are
    persisted here. Memory content remains in the configured memory backend.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._events: list[MemoryEvent] = []
        self._lock = RLock()
        self.path = Path(path) if path is not None else None
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.is_file():
                for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
                    if not line.strip():
                        continue
                    try:
                        self._events.append(MemoryEvent.model_validate_json(line))
                    except ValueError as exc:
                        raise ValueError(f"invalid memory event at {self.path}:{line_number}") from exc

    def _persist(self, event: MemoryEvent) -> None:
        if self.path is None:
            return
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(event.model_dump_json() + "\n")
            stream.flush()

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
            self._persist(event)
            self._events.append(event)
        return event

    def list(
        self,
        *,
        memory_id: str | None = None,
        scope_type: str | None = None,
        scope_id: str | None = None,
        case_id: str | None = None,
        actor_id: str | None = None,
    ) -> list[MemoryEvent]:
        with self._lock:
            return [
                item for item in self._events
                if (memory_id is None or item.memory_id == memory_id)
                and (scope_type is None or item.scope_type == scope_type)
                and (scope_id is None or item.scope_id == scope_id)
                and (case_id is None or item.safe_metadata.get("case_id") == case_id or item.scope_id == case_id)
                and (actor_id is None or item.actor_id == actor_id)
            ]

    def case_history(self, case_id: str, *, actor_id: str | None = None) -> list[MemoryEvent]:
        """Return safe lifecycle history for a case, including its task writes."""

        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError("case_id must be a non-empty string")
        return self.list(case_id=case_id, actor_id=actor_id)


__all__ = ["MemoryEvent", "MemoryEventLog", "MemoryEventType"]
