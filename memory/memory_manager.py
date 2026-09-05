"""Application-facing memory orchestration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from memory.cognee_adapter import CogneeConfig, CogneeHttpAdapter, MemoryBackend
from memory.context_builder import BuiltContext, ContextBuilder, RetrievedMemory
from memory.memory_store import MemoryStore
from memory.model import KnowledgeUnit, Memory, MemoryType, ScopeType, Source, SourceType, utc_now
from memory.scope_policy import AccessContext, accessible_node_sets, node_sets_for_scope


@dataclass(frozen=True, slots=True)
class RememberReceipt:
    memory: Memory
    backend_response: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class RecallResponse:
    context: BuiltContext
    results: tuple[RetrievedMemory, ...]


def _source_from(value: Any, unit_id: str, provenance: Mapping[str, Any]) -> Source:
    if isinstance(value, Source):
        return value
    if isinstance(value, Mapping):
        source_id = value.get("source_id", unit_id)
        source_type = value.get("source_type", SourceType.TEXT)
        reference = value.get("source_reference") or value.get("reference") or value.get("uri") or unit_id
    else:
        source_id = getattr(value, "source_id", unit_id)
        source_type = getattr(value, "source_type", SourceType.TEXT)
        reference = (getattr(value, "source_reference", None)
                     or getattr(value, "reference", None)
                     or getattr(value, "uri", None)
                     or unit_id)
    try:
        source_type = SourceType(source_type)
    except (TypeError, ValueError):
        source_type = SourceType.OTHER
    return Source(str(source_id), source_type, str(reference or provenance.get("source_reference", unit_id)))


def coerce_knowledge_unit(value: KnowledgeUnit | Mapping[str, Any] | Any) -> KnowledgeUnit:
    """Accept the dataclass or a structurally compatible ingestion object."""

    if isinstance(value, KnowledgeUnit):
        return value
    if isinstance(value, Mapping):
        get = value.get
    else:
        get = lambda key, default=None: getattr(value, key, default)
    unit_id = get("unit_id", get("id"))
    content = get("content", get("text"))
    metadata = get("metadata", {}) or {}
    provenance = get("provenance", {}) or {}
    if not isinstance(metadata, Mapping) or not isinstance(provenance, Mapping):
        raise TypeError("KnowledgeUnit metadata and provenance must be mappings")
    if unit_id is None or content is None:
        raise TypeError("ingestion object must provide unit_id/id and content/text")
    created_at_value = get("created_at", None)
    if created_at_value is None:
        created_at = utc_now()
    elif isinstance(created_at_value, datetime):
        created_at = created_at_value
    elif isinstance(created_at_value, str):
        try:
            created_at = datetime.fromisoformat(created_at_value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise TypeError("created_at must be a datetime or ISO-8601 string") from exc
    else:
        raise TypeError("created_at must be a datetime or ISO-8601 string")

    return KnowledgeUnit(
        unit_id=str(unit_id),
        content=str(content),
        source=_source_from(get("source"), str(unit_id), provenance),
        metadata=metadata,
        provenance=provenance,
        created_at=created_at,
    )


def _stable_memory_id(unit: KnowledgeUnit, scope_type: ScopeType, scope_id: str,
                      memory_type: MemoryType) -> str:
    material = "|".join((unit.unit_id, scope_type.value, scope_id, memory_type.value))
    return "mem_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def _scope_type(value: Any) -> ScopeType | None:
    try:
        return ScopeType(value)
    except (TypeError, ValueError):
        return None


def _retrieved_from(raw: Any) -> list[RetrievedMemory]:
    if isinstance(raw, RetrievedMemory):
        return [raw]
    if isinstance(raw, (list, tuple)):
        output: list[RetrievedMemory] = []
        for item in raw:
            output.extend(_retrieved_from(item))
        return output
    if isinstance(raw, str):
        # Cognee may return the serialized memory document as context.
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            return [RetrievedMemory(raw)]
        return _retrieved_from(decoded) if isinstance(decoded, (dict, list)) else [RetrievedMemory(raw)]
    if not isinstance(raw, Mapping):
        return [RetrievedMemory(str(raw))]

    metadata: Mapping[str, Any] = raw.get("metadata") or raw.get("memify_metadata") or {}
    provenance = metadata.get("provenance") if isinstance(metadata.get("provenance"), Mapping) else {}
    result = raw.get("search_result", raw.get("context", raw.get("text", raw.get("answer"))))
    if isinstance(result, (dict, list, tuple)):
        nested = _retrieved_from(result)
        return [RetrievedMemory(item.content,
                                _scope_type(metadata.get("scope_type")) or item.scope_type,
                                metadata.get("scope_id") or item.scope_id,
                                metadata.get("source_reference") or item.source_reference,
                                item.score, provenance or item.provenance) for item in nested]
    if result is None:
        result = raw.get("content", "")
    score = raw.get("score", raw.get("relevance"))
    try:
        score = float(score) if score is not None else None
    except (TypeError, ValueError):
        score = None
    return [RetrievedMemory(
        str(result), _scope_type(metadata.get("scope_type")), metadata.get("scope_id"),
        metadata.get("source_reference") or metadata.get("source"), score, provenance,
    )]


def _allowed(result: RetrievedMemory, context: AccessContext) -> bool:
    if result.scope_type is None or result.scope_id is None:
        return True  # Cognee's node_name filter is authoritative when metadata is absent.
    allowed = {(ScopeType.SYSTEM, "system")}
    if context.user_id:
        allowed.add((ScopeType.USER, context.user_id))
    if context.case_id:
        allowed.add((ScopeType.CASE, context.case_id))
    if context.task_id:
        allowed.add((ScopeType.TASK, context.task_id))
    return (result.scope_type, result.scope_id) in allowed


class MemoryManager:
    """Own Sudarshan semantics and delegate graph/vector work to Cognee."""

    def __init__(self, backend: MemoryBackend, *, dataset_name: str = "sudarshan_memory",
                 store: MemoryStore | None = None, context_builder: ContextBuilder | None = None) -> None:
        if not dataset_name.strip():
            raise ValueError("dataset_name must be non-empty")
        self.backend = backend
        self.dataset_name = dataset_name
        self.store = store or MemoryStore()
        self.context_builder = context_builder or ContextBuilder()

    @classmethod
    def from_env(cls) -> "MemoryManager":
        config = CogneeConfig.from_env()
        return cls(CogneeHttpAdapter(config), dataset_name=config.dataset_name)

    def remember(self, unit: KnowledgeUnit | Mapping[str, Any] | Any, context: AccessContext,
                 *, scope_type: ScopeType = ScopeType.CASE,
                 memory_type: MemoryType = MemoryType.FACT,
                 run_in_background: bool = True) -> RememberReceipt:
        unit = coerce_knowledge_unit(unit)
        scope_type = ScopeType(scope_type)
        memory_type = MemoryType(memory_type)
        memory_scope = context.scope(scope_type)
        memory_id = _stable_memory_id(unit, scope_type, memory_scope.scope_id, memory_type)
        metadata = dict(unit.metadata)
        metadata.update({
            "memory_id": memory_id,
            "unit_id": unit.unit_id,
            "scope_type": scope_type.value,
            "scope_id": memory_scope.scope_id,
            "user_id": context.user_id,
            "case_id": context.case_id,
            "task_id": context.task_id,
            "memory_type": memory_type.value,
            "source_id": unit.source.source_id,
            "source_type": unit.source.source_type.value,
            "source_reference": unit.source.source_reference,
            "provenance": dict(unit.provenance),
        })
        memory = Memory(memory_id, unit.content, memory_scope, memory_type,
                        unit.created_at, utc_now(), unit.source, metadata, unit.provenance)
        response = self.backend.remember(
            memory_id=memory.id, content=memory.content,
            node_sets=node_sets_for_scope(memory.scope), metadata=metadata,
            dataset_name=self.dataset_name, run_in_background=run_in_background,
        )
        self.store.upsert_memory(memory)
        return RememberReceipt(memory, response)

    def recall(self, query: str, context: AccessContext, *, top_k: int = 10,
               token_budget: int = 2000, session_id: str | None = None) -> RecallResponse:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        if top_k < 1:
            raise ValueError("top_k must be positive")
        raw = self.backend.recall(query=query.strip(), node_sets=accessible_node_sets(context),
                                  dataset_name=self.dataset_name, top_k=top_k,
                                  session_id=session_id)
        results = tuple(result for item in raw for result in _retrieved_from(item)
                        if result.content.strip() and _allowed(result, context))
        return RecallResponse(self.context_builder.build(results, token_budget), results)
