"""Application-facing memory orchestration."""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

from memory.cognee_adapter import CogneeConfig, CogneeHttpAdapter, MemoryBackend
from memory.context_builder import BuiltContext, ContextBuilder, ContextLevel, RetrievedMemory
from memory.lifecycle import MemoryEventLog
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
    context_layers = _context_layers(metadata)
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
            context_layers or item.context_layers,
            _context_level(metadata.get("context_level", item.context_level)),
            metadata.get("context_uri") or item.context_uri,
            metadata.get("expires_at") or item.expires_at,
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
        context_layers, _context_level(metadata.get("context_level", "L2")),
        metadata.get("context_uri"), metadata.get("expires_at"),
    )]


def _context_layers(metadata: Mapping[str, Any]) -> dict[str, str]:
    raw = metadata.get("context_layers")
    if not isinstance(raw, Mapping):
        raw = {key: metadata.get(key) for key in ("L0", "L1", "L2", "l0", "l1", "l2")}
    return {
        str(key).upper(): str(value)
        for key, value in raw.items()
        if str(key).upper() in {"L0", "L1", "L2"} and isinstance(value, str) and value.strip()
    }


def _context_level(value: Any) -> str:
    normalized = str(value or "L2").upper()
    return normalized if normalized in {"L0", "L1", "L2"} else "L2"


def _bounded_metric(value: Any, name: str) -> float:
    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be between 0 and 1") from exc
    if not 0.0 <= normalized <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return normalized


def _allowed(result: RetrievedMemory, context: AccessContext) -> bool:
    # A provider-side node-set filter is not an authorization proof.  Results
    # without explicit scope metadata cannot be tied to this request's
    # user/case/task and must not enter a ContextPack.
    if result.scope_type is None or result.scope_id is None:
        return False
    allowed = {(ScopeType.SYSTEM, "system")}
    if context.user_id:
        allowed.add((ScopeType.USER, context.user_id))
    if context.case_id:
        allowed.add((ScopeType.CASE, context.case_id))
    if context.task_id:
        allowed.add((ScopeType.TASK, context.task_id))
    return (result.scope_type, result.scope_id) in allowed


def _not_expired(result: RetrievedMemory) -> bool:
    """Apply expiry even when the provider has no local MemoryStore row."""

    if not result.expires_at:
        return True
    try:
        expiry = datetime.fromisoformat(str(result.expires_at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    return expiry > datetime.now(timezone.utc)


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
                 store: MemoryStore | None = None, context_builder: ContextBuilder | None = None,
                 event_log: MemoryEventLog | None = None,
                 operation_observer: Callable[[str, Mapping[str, Any]], None] | None = None) -> None:
        if not dataset_name.strip():
            raise ValueError("dataset_name must be non-empty")
        self.backend = backend
        self.dataset_name = dataset_name
        self.store = store or MemoryStore()
        self.context_builder = context_builder or ContextBuilder()
        self.event_log = event_log or MemoryEventLog()
        # Optional safe telemetry hook. It receives identifiers and counts,
        # never query text, recalled content, credentials, or backend payloads.
        self.operation_observer = operation_observer

    def _observe_operation(self, name: str, payload: Mapping[str, Any]) -> None:
        observer = self.operation_observer
        if observer is None:
            return
        try:
            observer(name, payload)
        except Exception:
            # Memory telemetry must never change the result of a memory call.
            return

    @classmethod
    def from_env(cls) -> "MemoryManager":
        config = CogneeConfig.from_env()
        event_log_path = os.getenv(
            "SUDARSHAN_MEMORY_EVENT_LOG",
            "artifacts/.state/memory_events.jsonl",
        ).strip()
        return cls(
            CogneeHttpAdapter(config),
            dataset_name=config.dataset_name,
            event_log=MemoryEventLog(event_log_path or None),
        )

    def remember(self, unit: KnowledgeUnit | Mapping[str, Any] | Any, context: AccessContext,
                 *, scope_type: ScopeType = ScopeType.CASE,
                 memory_type: MemoryType = MemoryType.FACT,
                 run_in_background: bool = True,
                 lifecycle: MemoryLifecycle = MemoryLifecycle.ACTIVE,
                 supersedes: Sequence[str] = (),
                 importance: float | None = None,
                 confidence: float | None = None,
                 expires_at: datetime | None = None) -> RememberReceipt:
        unit = coerce_knowledge_unit(unit)
        scope_type = ScopeType(scope_type)
        memory_type = MemoryType(memory_type)
        lifecycle = MemoryLifecycle(lifecycle)
        importance = _bounded_metric(unit.metadata.get("importance", 0.5) if importance is None else importance, "importance")
        confidence = _bounded_metric(unit.metadata.get("confidence", 0.5) if confidence is None else confidence, "confidence")
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
            "importance": importance,
            "confidence": confidence,
            "expires_at": expires_at.isoformat() if expires_at else None,
        })
        if "context_uri" not in metadata:
            from memory.context_refs import build_context_uri

            metadata["context_uri"] = build_context_uri(
                scope_type=scope_type.value,
                scope_id=memory_scope.scope_id,
                source_id=unit.source.source_id,
                level="L2",
            )
        memory = Memory(memory_id, unit.content, memory_scope, memory_type,
                        unit.created_at, utc_now(), unit.source, metadata, unit.provenance,
                        lifecycle=lifecycle, importance=importance,
                        confidence=confidence, expires_at=expires_at)
        run_id = str(unit.provenance.get("run_id") or metadata.get("run_id") or context.task_id or "")
        started = time.monotonic()
        operation_payload = {
            "run_id": run_id,
            "operation": "remember",
            "backend": type(self.backend).__name__,
            "owner_id": context.user_id,
            "case_id": context.case_id,
            "memory_id": memory.id,
            "memory_type": memory_type.value,
            "scope_type": scope_type.value,
            "scope_id": memory_scope.scope_id,
        }
        self._observe_operation("memory.remember.started", operation_payload)
        try:
            response = self.backend.remember(
                memory_id=memory.id, content=memory.content,
                node_sets=node_sets_for_scope(memory.scope), metadata=metadata,
                dataset_name=self.dataset_name, run_in_background=run_in_background,
            )
        except Exception as exc:
            self._observe_operation("memory.remember.failed", {
                **operation_payload,
                "duration_ms": max(0, round((time.monotonic() - started) * 1000)),
                "error_code": type(exc).__name__,
            })
            raise
        self._observe_operation("memory.remember.completed", {
            **operation_payload,
            "duration_ms": max(0, round((time.monotonic() - started) * 1000)),
            "backend_response_keys": sorted(str(key) for key in response)[:32]
            if isinstance(response, Mapping) else [],
        })
        self.store.upsert_memory(memory)
        self.event_log.append(
            "created",
            memory_id=memory.id,
            scope_type=memory.scope.scope_type.value,
            scope_id=memory.scope.scope_id,
            actor_id=context.user_id,
            safe_metadata={
                "memory_type": memory.memory_type.value,
                "lifecycle": lifecycle.value,
                "case_id": context.case_id,
                "task_id": context.task_id,
            },
            created_at=memory.updated_at,
        )
        for superseded_id in superseded_ids:
            self.store.transition(
                superseded_id,
                MemoryLifecycle.SUPERSEDED,
                superseded_by=memory.id,
            )
            old = self.store.get_memory(superseded_id)
            if old is not None:
                self.event_log.append(
                    "superseded",
                    memory_id=old.id,
                    scope_type=old.scope.scope_type.value,
                    scope_id=old.scope.scope_id,
                    actor_id=context.user_id,
                    safe_metadata={"superseded_by": memory.id, "case_id": context.case_id, "task_id": context.task_id},
                    created_at=old.updated_at,
                )
        return RememberReceipt(memory, response)

    def remember_lesson(
        self,
        content: str,
        context: AccessContext,
        *,
        source_reference: str = "sudarshan://lesson",
        metadata: Mapping[str, Any] | None = None,
    ) -> RememberReceipt:
        """Persist a bounded post-run lesson in the user scope."""

        unit = KnowledgeUnit(
            unit_id="lesson_" + hashlib.sha256(content.encode("utf-8")).hexdigest()[:24],
            content=content,
            source=Source("lesson", SourceType.USER, source_reference),
            metadata={**dict(metadata or {}), "lesson": True},
            provenance={"kind": "agent_lesson"},
        )
        receipt = self.remember(
            unit,
            context,
            scope_type=ScopeType.USER,
            memory_type=MemoryType.LESSON,
            run_in_background=True,
        )
        self.event_log.append(
            "lesson_recorded",
            memory_id=receipt.memory.id,
            scope_type=receipt.memory.scope.scope_type.value,
            scope_id=receipt.memory.scope.scope_id,
            actor_id=context.user_id,
            safe_metadata={"memory_type": MemoryType.LESSON.value},
            created_at=receipt.memory.updated_at,
        )
        return receipt

    def remember_profile(
        self,
        profile: Mapping[str, Any],
        context: AccessContext,
        *,
        source_reference: str = "sudarshan://voice-profile",
    ) -> RememberReceipt:
        """Persist an explicit user-scoped voice/profile preference."""

        if not context.user_id:
            raise PermissionError("a user context is required for profiles")
        payload = dict(profile)
        profile_id = str(payload.get("profile_id") or f"voice:{context.user_id}")
        content = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        unit = KnowledgeUnit(
            unit_id="profile_" + hashlib.sha256(profile_id.encode("utf-8")).hexdigest()[:24],
            content=content,
            source=Source(profile_id, SourceType.USER, source_reference),
            metadata={"profile_id": profile_id, "profile_version": str(payload.get("version", "1.0"))},
            provenance={"kind": "explicit_user_profile"},
        )
        receipt = self.remember(
            unit,
            context,
            scope_type=ScopeType.USER,
            memory_type=MemoryType.PROFILE,
            run_in_background=True,
        )
        self.event_log.append(
            "profile_updated",
            memory_id=receipt.memory.id,
            scope_type=receipt.memory.scope.scope_type.value,
            scope_id=receipt.memory.scope.scope_id,
            actor_id=context.user_id,
            safe_metadata={"profile_id": profile_id},
            created_at=receipt.memory.updated_at,
        )
        return receipt

    def recall(self, query: str, context: AccessContext, *, top_k: int = 10,
               token_budget: int = 2000, session_id: str | None = None,
               stage_id: str = "default",
               context_level: ContextLevel | None = None) -> RecallResponse:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        if top_k < 1:
            raise ValueError("top_k must be positive")
        query_hash = hashlib.sha256(query.strip().encode("utf-8")).hexdigest()[:16]
        run_id = str(session_id or context.task_id or "")
        operation_payload = {
            "run_id": run_id,
            "operation": "recall",
            "backend": type(self.backend).__name__,
            "owner_id": context.user_id,
            "case_id": context.case_id,
            "stage_id": stage_id,
            "query_hash": query_hash,
            "top_k": top_k,
            "token_budget": token_budget,
        }
        started = time.monotonic()
        self._observe_operation("memory.recall.started", operation_payload)
        try:
            raw = self.backend.recall(query=query.strip(), node_sets=accessible_node_sets(context),
                                      dataset_name=self.dataset_name, top_k=top_k,
                                      session_id=session_id)
        except Exception as exc:
            self._observe_operation("memory.recall.failed", {
                **operation_payload,
                "duration_ms": max(0, round((time.monotonic() - started) * 1000)),
                "error_code": type(exc).__name__,
            })
            raise
        raw_count = len(raw) if hasattr(raw, "__len__") else None
        results = tuple(
            result
            for item in raw
            for result in _retrieved_from(item)
            if result.content.strip()
            and _allowed(result, context)
            and self.store.is_recallable(result.memory_id)
            and result.lifecycle == MemoryLifecycle.ACTIVE.value
            and _not_expired(result)
        )
        response = RecallResponse(
            self.context_builder.build(
                results,
                token_budget,
                query=query,
                stage_id=stage_id,
                context_level=context_level,
            ),
            results,
        )
        self._observe_operation("memory.recall.completed", {
            **operation_payload,
            "duration_ms": max(0, round((time.monotonic() - started) * 1000)),
            "backend_result_count": raw_count,
            "accepted_result_count": len(results),
            "trace_id": response.context.trace.trace_id if response.context.trace else None,
        })
        return response

    def case_history(self, context: AccessContext) -> list[Any]:
        """Return the authenticated case's safe memory lifecycle history."""

        if not context.case_id:
            raise ValueError("case history requires a case context")
        return self.event_log.case_history(context.case_id, actor_id=context.user_id)

    def retract(self, memory_id: str, context: AccessContext) -> Memory:
        """Hide a memory from future recalls while retaining an audit record."""

        memory = self.store.get_memory(memory_id)
        if memory is None:
            raise KeyError(memory_id)
        if not _scope_accessible(memory, context):
            raise PermissionError(f"memory {memory_id!r} is outside the access context")
        updated = self.store.transition(memory_id, MemoryLifecycle.RETRACTED)
        self.event_log.append(
            "retracted",
            memory_id=updated.id,
            scope_type=updated.scope.scope_type.value,
            scope_id=updated.scope.scope_id,
            actor_id=context.user_id,
            safe_metadata={"case_id": context.case_id, "task_id": context.task_id},
            created_at=updated.updated_at,
        )
        return updated

    def expire_due(self, *, now: datetime | None = None) -> list[Memory]:
        expired = self.store.expire_due(now=now)
        for memory in expired:
            self.event_log.append(
                "expired",
                memory_id=memory.id,
                scope_type=memory.scope.scope_type.value,
                scope_id=memory.scope.scope_id,
                created_at=memory.updated_at,
            )
        return expired

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
        self.event_log.append(
            "forgotten",
            memory_id=retracted.id,
            scope_type=retracted.scope.scope_type.value,
            scope_id=retracted.scope.scope_id,
            actor_id=context.user_id,
            safe_metadata={"purge_backend": purge_backend, "case_id": context.case_id, "task_id": context.task_id},
            created_at=retracted.updated_at,
        )
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
            stage_id=stage_id,
        )
        trace_id = response.context.trace.trace_id if response.context.trace else None
        records = []
        for rank, item in enumerate(response.context.items, start=1):
            provenance = dict(item.provenance or {})
            records.append({
                "rank": rank,
                "memory_id": provenance.get("memory_id"),
                "content": item.content,
                "context_level": item.context_level,
                "scope_type": item.scope_type.value if item.scope_type else None,
                "scope_id": item.scope_id,
                "source_reference": item.source_reference,
                "context_uri": item.context_uri,
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
            context_level=response.context.context_level,
        )
