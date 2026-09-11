"""Stable hierarchical references for requesting bounded context layers."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from urllib.parse import quote

from memory.context_builder import ContextLevel, RetrievedMemory


@dataclass(frozen=True, slots=True)
class ContextReference:
    uri: str
    level: ContextLevel
    memory_id: str | None = None
    source_id: str | None = None
    classification_level: str | None = None
    checksum: str | None = None


def build_context_uri(
    *,
    scope_type: str,
    scope_id: str,
    source_id: str,
    level: ContextLevel,
) -> str:
    if level not in {"L0", "L1", "L2"}:
        raise ValueError("level must be L0, L1, or L2")
    parts = [quote(str(item), safe="") for item in (scope_type, scope_id, source_id)]
    return f"sudarshan://context/{'/'.join(parts)}/{level}"


def reference_for_memory(memory: RetrievedMemory, *, level: ContextLevel | None = None) -> ContextReference:
    resolved = level or memory.context_level
    source_id = str((memory.provenance or {}).get("source_id") or memory.source_reference or "unknown")
    provenance = dict(memory.provenance or {})
    checksum = str(provenance.get("checksum") or source_fingerprint(source_id))
    uri = build_context_uri(
        scope_type=memory.scope_type.value if memory.scope_type else "unknown",
        scope_id=memory.scope_id or "unknown",
        source_id=source_id,
        level=resolved,
    )
    return ContextReference(
        uri,
        resolved,
        memory.memory_id,
        source_id,
        str(provenance.get("classification_level")) if provenance.get("classification_level") else None,
        checksum,
    )


def source_fingerprint(reference: str) -> str:
    return sha256(str(reference).encode("utf-8")).hexdigest()[:16]


__all__ = ["ContextReference", "build_context_uri", "reference_for_memory", "source_fingerprint"]
