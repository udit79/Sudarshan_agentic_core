"""Domain models for Sudarshan memory.

These models deliberately contain application semantics only. Cognee-specific
transport and response formats live in :mod:`memory.cognee_adapter`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping


class ScopeType(str, Enum):
    SYSTEM = "system"
    USER = "user"
    CASE = "case"
    TASK = "task"


class MemoryType(str, Enum):
    FACT = "fact"
    EVENT = "event"
    DECISION = "decision"
    PROCEDURE = "procedure"
    SUMMARY = "summary"
    RELATIONSHIP = "relationship"


class SourceType(str, Enum):
    PDF = "pdf"
    PPTX = "pptx"
    TEXT = "text"
    USER = "user"
    INFOGRAPHIC = "infographic"
    IMAGE = "image"
    VIDEO = "video"
    OTHER = "other"


def utc_now() -> datetime:
    """Return an aware UTC timestamp suitable for persisted records."""

    return datetime.now(timezone.utc)


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True, slots=True)
class Scope:
    scope_type: ScopeType
    scope_id: str
    parent_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope_type", ScopeType(self.scope_type))
        object.__setattr__(self, "scope_id", _required(self.scope_id, "scope_id"))
        if self.parent_id is not None:
            object.__setattr__(self, "parent_id", _required(self.parent_id, "parent_id"))


@dataclass(frozen=True, slots=True)
class Source:
    source_id: str
    source_type: SourceType
    source_reference: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_type", SourceType(self.source_type))
        object.__setattr__(self, "source_id", _required(self.source_id, "source_id"))
        object.__setattr__(self, "source_reference", _required(self.source_reference, "source_reference"))


@dataclass(frozen=True, slots=True)
class KnowledgeUnit:
    """The stable hand-off contract from ingestion to memory."""

    unit_id: str
    content: str
    source: Source
    metadata: Mapping[str, Any] = field(default_factory=dict)
    provenance: Mapping[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "unit_id", _required(self.unit_id, "unit_id"))
        object.__setattr__(self, "content", _required(self.content, "content"))
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "provenance", dict(self.provenance))


@dataclass(frozen=True, slots=True)
class Memory:
    id: str
    content: str
    scope: Scope
    memory_type: MemoryType
    created_at: datetime
    updated_at: datetime
    source: Source | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "memory_type", MemoryType(self.memory_type))
        object.__setattr__(self, "id", _required(self.id, "id"))
        object.__setattr__(self, "content", _required(self.content, "content"))
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "provenance", dict(self.provenance))
