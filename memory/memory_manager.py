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
from memory.model import KnowledgeUnit, Memory, MemoryLifecycle, MemoryType, ScopeType, Source, SourceType, utc_now
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
    provenance = dict(metadata.get("provenance")) if isinstance(metadata.get("provenance"), Mapping) else {}
    # Preserve stable identity and lifecycle hints beside the bounded text.
    # These fields are safe retrieval metadata, not hidden prompts or model
    # reasoning, and let ContextPack records point back to the source memory.
    for key in ("memory_id", "unit_id", "pipeline", "step", "status", "source_id", "source_type"):
        if key in metadata:
            provenance.setdefault(key, metadata[key])
    result = raw.get("search_result", raw.get("context", raw.get("text", raw.get("answer"))))
    if isinstance(result, (dict, list, tuple)):
        nested = _retrieved_from(result)
        return [RetrievedMemory(
            item.content,
            _scope_type(metadata.get("scope_type")) or item.scope_type,
            metadata.get("scope_id") or item.scope_id,
            metadata.get("source_reference") or item.source_reference,
            item.score,
            provenance or item.provenance,
            metadata.get("memory_id") or item.memory_id,
            str(metadata.get("lifecycle", item.lifecycle)),
        ) for item in nested]
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
        metadata.get("memory_id"), str(metadata.get("lifecycle", "active")),
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


def _scope_accessible(memory: Memory, context: AccessContext) -> bool:
    """Check ownership before lifecycle mutation or backend deletion."""

    scope = memory.scope
    if scope.scope_type is ScopeType.SYSTEM:
        return False
    if scope.scope_type is ScopeType.USER:
        return context.user_id == scope.scope_id
    if scope.scope_type is ScopeType.CASE:
        return context.user_id == scope.parent_id and context.case_id == scope.scope_id
    if scope.scope_type is ScopeType.TASK:
        return (
            context.user_id is not None
            and context.case_id == scope.parent_id
            and context.task_id == scope.scope_id
        )
    return False


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
                 run_in_background: bool = True,
                 lifecycle: MemoryLifecycle = MemoryLifecycle.ACTIVE,
                 supersedes: Sequence[str] = ()) -> RememberReceipt:
        unit = coerce_knowledge_unit(unit)
        scope_type = ScopeType(scope_type)
        memory_type = MemoryType(memory_type)
        lifecycle = MemoryLifecycle(lifecycle)
        memory_scope = context.scope(scope_type)
        memory_id = _stable_memory_id(unit, scope_type, memory_scope.scope_id, memory_type)
        superseded_ids = list(dict.fromkeys(str(item).strip() for item in supersedes if str(item).strip()))
        for superseded_id in superseded_ids:
            old = self.store.get_memory(superseded_id)
            if old is None:
                raise KeyError(f"cannot supersede unknown memory {superseded_id!r}")
            if not _scope_accessible(old, context):
                raise PermissionError(f"memory {superseded_id!r} is outside the access context")
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
            "lifecycle": lifecycle.value,
            "supersedes": superseded_ids,
            "source_id": unit.source.source_id,
            "source_type": unit.source.source_type.value,
            "source_reference": unit.source.source_reference,
            "provenance": dict(unit.provenance),
        })
        memory = Memory(memory_id, unit.content, memory_scope, memory_type,
                        unit.created_at, utc_now(), unit.source, metadata, unit.provenance,
                        lifecycle=lifecycle)
        response = self.backend.remember(
            memory_id=memory.id, content=memory.content,
            node_sets=node_sets_for_scope(memory.scope), metadata=metadata,
            dataset_name=self.dataset_name, run_in_background=run_in_background,
        )
        self.store.upsert_memory(memory)
        for superseded_id in superseded_ids:
            self.store.transition(
                superseded_id,
                MemoryLifecycle.SUPERSEDED,
                superseded_by=memory.id,
            )
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
        results = tuple(
            result
            for item in raw
            for result in _retrieved_from(item)
            if result.content.strip()
            and _allowed(result, context)
            and self.store.is_recallable(result.memory_id)
            and result.lifecycle == MemoryLifecycle.ACTIVE.value
        )
        return RecallResponse(
            self.context_builder.build(results, token_budget, query=query),
            results,
        )

    def retract(self, memory_id: str, context: AccessContext) -> Memory:
        """Hide a memory from future recalls while retaining an audit record."""

        memory = self.store.get_memory(memory_id)
        if memory is None:
            raise KeyError(memory_id)
        if not _scope_accessible(memory, context):
            raise PermissionError(f"memory {memory_id!r} is outside the access context")
        return self.store.transition(memory_id, MemoryLifecycle.RETRACTED)

    def forget(self, memory_id: str, context: AccessContext, *, purge_backend: bool = False) -> Mapping[str, Any]:
        """Retract locally and optionally invoke an explicitly supported backend purge.

        Purging is opt-in because Cognee deletion is irreversible. The default
        behavior satisfies application-level forgetting by removing the item
        from recall while preserving a local lifecycle record for auditability.
        """

        if purge_backend:
            backend_forget = getattr(self.backend, "forget", None)
            if not callable(backend_forget):
                raise NotImplementedError("backend purge is not supported by this memory adapter")
        retracted = self.retract(memory_id, context)
        response: Mapping[str, Any] = {"status": "retracted", "memory_id": retracted.id}
        if purge_backend:
            backend_response = backend_forget(
                memory_id=memory_id,
                dataset_name=self.dataset_name,
                scope_type=retracted.scope.scope_type.value,
                scope_id=retracted.scope.scope_id,
            )
            response = {**response, "backend": dict(backend_response or {})}
        return response

    def recall_context_pack(
        self,
        query: str,
        context: AccessContext,
        *,
        run_id: str,
        stage_id: str,
        top_k: int | None = None,
        token_budget: int | None = None,
        session_id: str | None = None,
        source_artifact_ids: Sequence[str] = (),
    ) -> Any:
        """Return the canonical, bounded ``ContextPack`` for a stage.

        The import is intentionally lazy: the memory package remains usable
        by lightweight ingestion tests without importing the full orchestrator
        package and its optional pipeline dependencies.
        """

        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id must be non-empty")
        if not isinstance(stage_id, str) or not stage_id.strip():
            raise ValueError("stage_id must be non-empty")
        profile_top_k, profile_budget = self.context_builder.profile(stage_id)
        resolved_top_k = top_k if top_k is not None else profile_top_k
        resolved_budget = token_budget if token_budget is not None else profile_budget
        if resolved_top_k < 1:
            raise ValueError("top_k must be positive")
        if resolved_budget < 256:
            raise ValueError("ContextPack token_budget must be at least 256")

        response = self.recall(
            query,
            context,
            top_k=resolved_top_k,
            token_budget=resolved_budget,
            session_id=session_id,
        )
        trace_id = response.context.trace.trace_id if response.context.trace else None
        records = []
        for rank, item in enumerate(response.context.items, start=1):
            provenance = dict(item.provenance or {})
            records.append({
                "rank": rank,
                "memory_id": provenance.get("memory_id"),
                "content": item.content,
                "scope_type": item.scope_type.value if item.scope_type else None,
                "scope_id": item.scope_id,
                "source_reference": item.source_reference,
                "score": item.score,
                "provenance": provenance,
            })

        from pipelines.orchestrator.contracts import ContextPack

        scope = {
            key: value
            for key, value in {
                "user_id": context.user_id,
                "case_id": context.case_id,
                "task_id": context.task_id,
            }.items()
            if value
        }
        material = f"{run_id}|{stage_id}|{query}|{trace_id or ''}"
        pack_id = "pack_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
        pack_query = query.strip()[:4000]
        return ContextPack(
            pack_id=pack_id,
            run_id=run_id,
            stage_id=stage_id,
            query=pack_query,
            records=records,
            source_artifact_ids=list(dict.fromkeys(source_artifact_ids)),
            token_budget=resolved_budget,
            retrieval_trace_id=trace_id,
            scope=scope,
            context_text=response.context.text,
        )
