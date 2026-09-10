"""Long-lived application boundary used by the Harness and backend adapters.

This module owns one orchestrator instance per Python service process. The
LangGraph checkpoint store makes paused runs recoverable across tool calls;
the progress sink makes the same run observable to a polling endpoint or an
SSE/WebSocket bridge owned by the backend.
"""

from __future__ import annotations

from threading import Event, Lock
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
import time
from uuid import uuid4
from typing import Any, Mapping

from memory import AccessContext, MemoryManager
from ingestion_pipelines import (
    EvidenceBlock,
    IngestedDocument,
    IngestionBudget,
    IngestionBudgetController,
    IngestionStageCache,
    IngestionUsageRecorder,
    build_ingestion_stage_fingerprint,
)
from ingestion_pipelines.evidence_index import EvidenceIndex
from pipelines.common.contracts import AdvisoryRequest
from pipelines.common.audit_logger import get_audit_logger
from api.scheduler import LocalRunScheduler
from pipelines.orchestrator import (
    BudgetController,
    CacheStore,
    PipelineAdapter,
    RunContext,
    RunEvent,
    RunSummary,
    RunPolicy,
    PipelineOrchestrator,
    SkillCall,
    SkillRuntime,
    SQLiteProgressSink,
    ObservableProgressSink,
    SQLiteObservabilityStore,
    TelemetrySummary,
    create_sqlite_checkpointer,
    event_dict,
    project_progress_event,
    orchestration_result_to_dict,
)
from pipelines.orchestrator.progress import ProgressEvent
from integrations.deepseek_harness.skill_catalog import (
    build_skill_manifests,
    canonical_skill_id,
    skill_pipeline,
    skill_summary,
)


class SudarshanApplication:
    """Own the real application services behind Harness-facing tools."""

    def __init__(self) -> None:
        self.observability = SQLiteObservabilityStore()
        self.progress_sink = ObservableProgressSink(SQLiteProgressSink(), self.observability)
        self.orchestrator = PipelineOrchestrator(
            MemoryManager.from_env(),
            progress_sink=self.progress_sink,
            checkpointer=create_sqlite_checkpointer(),
        )
        self.skill_manifests = build_skill_manifests()
        self.budget_controller = BudgetController()
        self.cache_store = CacheStore(
            os.getenv("SUDARSHAN_CACHE_DB_PATH", "artifacts/.state/skill_cache.db")
        )
        self.cache_store.cleanup_expired()
        self.evidence_index = EvidenceIndex(
            os.getenv(
                "SUDARSHAN_EVIDENCE_INDEX_DB_PATH",
                "artifacts/.state/evidence_index.db",
            )
        )
        self.ingestion_budget_controller = IngestionBudgetController()
        self.ingestion_usage = IngestionUsageRecorder()
        self.ingestion_stage_cache = IngestionStageCache(
            os.getenv(
                "SUDARSHAN_INGESTION_STAGE_CACHE_DB_PATH",
                "artifacts/.state/ingestion_stage_cache.db",
            )
        )
        runtime_adapters: dict[str, PipelineAdapter] = {}
        for skill_id, manifest in self.skill_manifests.items():
            pipeline = skill_pipeline(skill_id)
            adapter = self.orchestrator.registry.get(pipeline) if pipeline else None
            if adapter is not None:
                runtime_adapters[skill_id] = PipelineAdapter(
                    skill_id,
                    adapter.run,
                    adapter.resume,
                )
        self.skill_runtime = SkillRuntime(
            runtime_adapters,
            self.skill_manifests,
            event_sink=self._publish_skill_event,
            budget_controller=self.budget_controller,
            cache_store=self.cache_store,
        )
        self._run_contexts: dict[str, dict[str, str]] = {}
        self._run_context_lock = Lock()
        self.scheduler = LocalRunScheduler(
            self.run,
            db_path=os.getenv("SUDARSHAN_QUEUE_DB_PATH", "artifacts/.state/run_queue.db"),
            max_workers=int(os.getenv("SUDARSHAN_MAX_CONCURRENT_RUNS", "2")),
            lease_ms=int(os.getenv("SUDARSHAN_RUN_LEASE_MS", "900000")),
            max_attempts=int(os.getenv("SUDARSHAN_MAX_ATTEMPTS", "1")),
            retry_backoff_ms=int(os.getenv("SUDARSHAN_RETRY_BACKOFF_MS", "250")),
            execution_timeout_ms=int(os.getenv("SUDARSHAN_EXECUTION_TIMEOUT_MS", "0")),
        )
        self.ingestion_scheduler = LocalRunScheduler(
            self._run_ingestion_job,
            db_path=os.getenv(
                "SUDARSHAN_INGESTION_QUEUE_DB_PATH",
                "artifacts/.state/ingestion_queue.db",
            ),
            max_workers=int(os.getenv("SUDARSHAN_MAX_CONCURRENT_INGESTIONS", "2")),
            lease_ms=int(os.getenv("SUDARSHAN_INGESTION_LEASE_MS", "900000")),
            max_attempts=int(os.getenv("SUDARSHAN_INGESTION_MAX_ATTEMPTS", "2")),
            retry_backoff_ms=int(os.getenv("SUDARSHAN_INGESTION_RETRY_BACKOFF_MS", "500")),
            execution_timeout_ms=int(os.getenv("SUDARSHAN_INGESTION_TIMEOUT_MS", "0")),
        )

    def _prepare_request(
        self, payload: Mapping[str, Any]
    ) -> tuple[AdvisoryRequest, str]:
        """Validate a public request and reserve its durable run identity."""

        data = dict(payload)
        metadata = dict(data.get("metadata") or {})
        requested_run_id = metadata.get("run_id")
        run_id = (
            str(requested_run_id).strip()
            if requested_run_id is not None and str(requested_run_id).strip()
            else f"run-{uuid4()}"
        )
        metadata["run_id"] = run_id
        data["metadata"] = metadata
        request = AdvisoryRequest(**data)

        # Explicit routes are rejected at the application boundary. Natural
        # language routing remains the orchestrator's responsibility.
        explicit = list(request.requested_pipelines)
        if not explicit:
            pipeline = metadata.get("pipeline")
            pipelines = metadata.get("pipelines")
            if isinstance(pipeline, str) and pipeline.strip():
                explicit = [pipeline.strip().lower()]
            elif isinstance(pipelines, str):
                explicit = [pipelines.strip().lower()]
            elif isinstance(pipelines, (list, tuple)):
                explicit = [str(item).strip().lower() for item in pipelines if str(item).strip()]
        unknown = sorted(set(explicit) - set(self.orchestrator.registry))
        if unknown:
            raise ValueError(f"Unknown pipeline(s): {', '.join(unknown)}")
        return request, run_id

    def run(
        self,
        payload: Mapping[str, Any],
        *,
        operator_id: str | None = None,
        cancel_event: Event | None = None,
    ) -> dict[str, Any]:
        request, run_id = self._prepare_request(payload)
        operator = (operator_id or request.user_id).strip()
        if operator != request.user_id:
            raise PermissionError("user_id must match the authenticated operator")
        with self._run_context_lock:
            self._run_contexts[run_id] = {
                "operator_id": operator,
                "user_id": request.user_id,
                "case_id": request.case_id,
                "task_id": request.task_id,
                "classification_level": request.classification_level,
            }

        audit = get_audit_logger()
        audit.log_run_start(
            operator_id=operator,
            case_id=request.case_id,
            task_id=request.task_id,
            run_id=run_id,
            classification=request.classification_level,
            pipeline=next(iter(request.requested_pipelines), str(request.metadata.get("pipeline", ""))),
            query=request.query,
        )
        try:
            if request.metadata.get("skill_job") is True:
                output = self._invoke_skill_request(request, run_id=run_id, cancel_event=cancel_event)
                result_status = str(output.get("status", "failed"))
                audit.log_run_complete(
                    operator_id=operator,
                    case_id=request.case_id,
                    task_id=request.task_id,
                    run_id=run_id,
                    classification=request.classification_level,
                    pipeline=str(request.metadata.get("skill_id", "")),
                    status=result_status,
                )
                return output
            result = self.orchestrator.run(
                request,
                run_id=run_id,
                cancellation_event=cancel_event,
            )
        except Exception:
            audit.log_run_complete(
                operator_id=operator,
                case_id=request.case_id,
                task_id=request.task_id,
                run_id=run_id,
                classification=request.classification_level,
                pipeline=str(request.metadata.get("pipeline", "")),
                status="failed",
            )
            raise
        audit.log_run_complete(
            operator_id=operator,
            case_id=request.case_id,
            task_id=request.task_id,
            run_id=run_id,
            classification=request.classification_level,
            pipeline=result.pipeline or "",
            status=result.status,
        )
        return orchestration_result_to_dict(result)

    def list_skills(self) -> list[dict[str, Any]]:
        """Return safe skill summaries for Harness discovery."""

        registered = set(self.skill_runtime._adapters)
        return [
            skill_summary(manifest, available=skill_id in registered)
            for skill_id, manifest in sorted(self.skill_manifests.items())
        ]

    def get_skill(self, skill_id: str) -> dict[str, Any]:
        canonical = canonical_skill_id(skill_id)
        manifest = self.skill_manifests.get(canonical)
        if manifest is None:
            raise ValueError(f"Unknown skill: {skill_id}")
        payload = manifest.model_dump(mode="json")
        payload["available"] = canonical in self.skill_runtime._adapters
        payload["pipeline"] = skill_pipeline(canonical)
        return payload

    def usage(self, run_id: str) -> dict[str, Any]:
        """Return safe budget and usage counters for a registered skill run."""

        try:
            return self.budget_controller.usage(run_id)
        except Exception:
            return {"run_id": run_id, "status": "not_registered"}

    def submit_skill(
        self,
        payload: Mapping[str, Any],
        *,
        operator_id: str | None = None,
    ) -> dict[str, Any]:
        """Submit a canonical skill job through the same durable scheduler."""

        data = dict(payload)
        canonical = canonical_skill_id(str(data.get("skill_id", "")))
        manifest = self.skill_manifests.get(canonical)
        pipeline = skill_pipeline(canonical)
        if manifest is None or pipeline is None or canonical not in self.skill_runtime._adapters:
            raise ValueError(f"Skill is not available for execution: {canonical}")
        metadata = dict(data.get("metadata") or {})
        metadata.update({
            "skill_id": canonical,
            "skill_version": manifest.version,
            "skill_job": True,
        })
        data["metadata"] = metadata
        data["requested_pipelines"] = [pipeline]
        return self.submit(data, operator_id=operator_id or str(data.get("user_id", "")))

    def _run_ingestion_job(
        self,
        payload: Mapping[str, Any],
        *,
        operator_id: str,
        cancel_event: Event | None = None,
    ) -> dict[str, Any]:
        """Execute one admitted ingestion job without exposing source paths."""

        if cancel_event is not None and cancel_event.is_set():
            return {"status": "cancelled", "error": "ingestion cancelled before extraction"}
        result = self.ingest_path(
            str(payload["file_path"]),
            source_reference=str(payload["source_reference"]),
            operator_id=operator_id,
            user_id=str(payload["user_id"]),
            case_id=str(payload["case_id"]),
            task_id=str(payload["task_id"]),
            classification_level=str(payload.get("classification_level", "RESTRICTED")),
            ingestion_id=str(payload.get("ingestion_id", payload.get("run_id", ""))) or None,
            source_hash=str(payload.get("source_hash", "")) or None,
            budget=payload.get("budget"),
        )
        if cancel_event is not None and cancel_event.is_set():
            return {"status": "cancelled", "error": "ingestion cancelled after extraction"}
        return {"status": "succeeded", "skill_result": result}

    def submit_ingestion(
        self,
        payload: Mapping[str, Any],
        *,
        operator_id: str,
    ) -> dict[str, Any]:
        """Admit source extraction asynchronously with idempotent identity."""

        from pipelines.common.ntro_policy import require_classification

        data = dict(payload)
        user_id = str(data.get("user_id", "")).strip()
        case_id = str(data.get("case_id", "")).strip()
        task_id = str(data.get("task_id", "")).strip()
        file_path = str(data.get("file_path", "")).strip()
        source_reference = str(data.get("source_reference", "")).strip()
        source_hash = str(data.get("source_hash", "")).strip()
        if not all((user_id, case_id, task_id, file_path, source_reference, source_hash)):
            raise ValueError("ingestion requires file_path, source_reference, source_hash, user_id, case_id, and task_id")
        if operator_id.strip() != user_id:
            raise PermissionError("user_id must match the authenticated operator")
        data["job_type"] = "ingestion"
        data["classification_level"] = require_classification(
            str(data.get("classification_level", "RESTRICTED"))
        )
        data["distribution"] = str(data.get("distribution", "Authorized NTRO personnel"))
        data["user_id"] = user_id
        data["case_id"] = case_id
        data["task_id"] = task_id
        budget = self._ingestion_budget(data.get("budget"), modality=str(data.get("modality", "")))
        data["budget"] = budget.model_dump(mode="json")
        idempotency_key = str(data.get("idempotency_key", "")).strip()
        if not idempotency_key:
            identity = f"{user_id}|{case_id}|{task_id}|{source_hash}"
            idempotency_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        ingestion_id = f"ing-{idempotency_key}"
        data["ingestion_id"] = ingestion_id
        state = self.ingestion_scheduler.submit(
            ingestion_id,
            data,
            operator_id=operator_id.strip(),
        )
        return {
            "status": state.get("status", "queued"),
            "ingestion_id": ingestion_id,
            "deduplicated": bool(state.get("idempotent_replay", False)),
            "task_id": task_id,
            "source_reference": source_reference,
            "source_hash": source_hash,
            "media_type": data.get("media_type"),
            "modality": data.get("modality"),
            "classification_level": data["classification_level"],
            "budget": data["budget"],
        }

    def ingestion_status(self, ingestion_id: str) -> dict[str, Any]:
        state = self.ingestion_scheduler.status(str(ingestion_id))
        if state is None:
            return {"ingestion_id": str(ingestion_id), "status": "not_found"}
        status = str(state.get("status", "queued"))
        quality_status = {
            "succeeded": "ready",
            "partial": "partial",
            "failed": "failed",
        }.get(status, "pending")
        result = state.get("skill_result")
        return {
            "ingestion_id": state["run_id"],
            "task_id": state["task_id"],
            "case_id": state["case_id"],
            "status": status,
            "quality_status": quality_status,
            "source_reference": state.get("source_reference"),
            "source_hash": state.get("source_hash"),
            "media_type": state.get("media_type"),
            "modality": state.get("modality"),
            "classification_level": state.get("classification_level", "RESTRICTED"),
            "attempt": state.get("attempt", 0),
            "queue_wait_ms": state.get("queue_wait_ms"),
            "error": state.get("error"),
            "dead_letter": bool(state.get("dead_letter", False)),
            "result": result,
            "events": self.ingestion_scheduler.events(str(ingestion_id)),
            "created_at": state.get("created_at"),
            "updated_at": state.get("updated_at"),
        }

    def cancel_ingestion(self, ingestion_id: str, task_id: str) -> dict[str, Any]:
        current = self.ingestion_status(ingestion_id)
        if current.get("status") == "not_found":
            return current
        if current.get("task_id") != task_id:
            raise PermissionError("task_id does not match the ingestion")
        cancelled = self.ingestion_scheduler.cancel(ingestion_id)
        return self.ingestion_status(ingestion_id) if cancelled else current

    def invoke_skill(
        self,
        payload: Mapping[str, Any],
        *,
        operator_id: str | None = None,
        cancel_event: Event | None = None,
    ) -> dict[str, Any]:
        """Invoke a local child skill through SkillRuntime, without Run API recursion."""

        data = dict(payload)
        canonical = canonical_skill_id(str(data.get("skill_id", "")))
        manifest = self.skill_manifests.get(canonical)
        if manifest is None or canonical not in self.skill_runtime._adapters:
            raise ValueError(f"Skill is not available for local invocation: {canonical}")
        user_id = str(data.get("user_id", "")).strip()
        if operator_id and operator_id != user_id:
            raise PermissionError("user_id must match the authenticated operator")
        parent_run_id = str(data.get("parent_run_id", "")).strip()
        if not parent_run_id:
            raise ValueError("parent_run_id is required for a local child skill")
        return self._invoke_skill_request(
            AdvisoryRequest(
                query=str(data.get("query", "")),
                user_id=user_id,
                case_id=str(data.get("case_id", "")),
                task_id=str(data.get("task_id", "")),
                classification_level=str(data.get("classification_level", "RESTRICTED")),
                distribution=str(data.get("distribution", "Authorized NTRO personnel")),
                token_budget=manifest.budget_policy.max_model_tokens,
                metadata=dict(data.get("metadata") or {}),
                requested_pipelines=(skill_pipeline(canonical) or canonical,),
            ),
            run_id=parent_run_id,
            skill_id=canonical,
            cancel_event=cancel_event,
        )

    def _invoke_skill_request(
        self,
        request: AdvisoryRequest,
        *,
        run_id: str,
        skill_id: str | None = None,
        cancel_event: Event | None = None,
    ) -> dict[str, Any]:
        canonical = canonical_skill_id(skill_id or str(request.metadata.get("skill_id", "")))
        manifest = self.skill_manifests.get(canonical)
        if manifest is None:
            raise ValueError(f"Unknown skill: {canonical}")
        call = SkillCall(
            skill_call_id=f"call-{uuid4().hex}",
            parent_run_id=run_id,
            parent_node_id=str(request.metadata.get("parent_node_id", "harness-skill")),
            skill_id=canonical,
            skill_version=manifest.version,
            input_payload={
                "query": request.query,
                "metadata": dict(request.metadata),
            },
            policy=manifest.budget_policy,
        )
        context = RunContext(
            run_id=run_id,
            task_id=request.task_id,
            user_id=request.user_id,
            case_id=request.case_id,
            classification_level=request.classification_level,
            distribution=request.distribution,
            policy=manifest.budget_policy,
            ancestors=tuple(request.metadata.get("ancestor_skills", ())),
            allowed_capabilities=frozenset(manifest.required_capabilities),
            allowed_tools=frozenset(manifest.allowed_tools),
            allowed_trust_tiers=frozenset({"builtin", "verified"}),
            cancel_event=cancel_event or Event(),
        )
        result = self.skill_runtime.invoke(call, parent_context=context)
        top_level_status = {
            "succeeded": "succeeded",
            "waiting": "pending",
            "blocked": "failed",
            "failed": "failed",
            "cancelled": "cancelled",
        }[result.status]
        return {
            "status": top_level_status,
            "run_id": run_id,
            "task_id": request.task_id,
            "skill_id": canonical,
            "skill_version": manifest.version,
            "skill_result": result.model_dump(mode="json"),
        }

    def _publish_skill_event(self, name: str, payload: Mapping[str, Any]) -> None:
        """Project child-runtime lifecycle into the existing safe event stream."""

        observability = getattr(self, "observability", None)
        if observability is not None:
            observability.record_runtime_event(name, payload)
        run_id = str(payload.get("parent_run_id", "")).strip()
        context = self._run_contexts.get(run_id, {})
        task_id = context.get("task_id") or str(payload.get("parent_node_id", "skill"))
        status_map = {
            "skill.started": ("running", 10, False),
            "skill.waiting": ("pending", 50, True),
            "skill.completed": ("succeeded", 100, False),
            "skill.failed": ("failed", 100, False),
            "skill.blocked": ("failed", 100, True),
            "skill.cancelled": ("cancelled", 100, False),
        }
        status, progress, requires_action = status_map.get(name, ("running", 0, False))
        cache_status = None
        if name.endswith("cache_hit"):
            cache_status = "hit"
        elif name.endswith("cache_wait"):
            cache_status = "wait"
        elif name.endswith("cache_write_failed"):
            cache_status = "write"
        self.progress_sink.publish(
            ProgressEvent(
                run_id=run_id or "skill-runtime",
                task_id=task_id,
                pipeline=str(payload.get("skill_id", "")),
                stage=name,
                status=status,
                progress=progress,
                message=f"Child skill event: {name}",
                requires_action=requires_action,
                error_code=payload.get("error_code"),
                wait_reason=(
                    "Child skill is waiting for a dependency or cache owner."
                    if status == "pending" else ""
                ),
                child_id=payload.get("child_run_id"),
                skill_call_id=payload.get("skill_call_id"),
                quality_report_id=payload.get("quality_report_id"),
                artifact_id=(payload.get("artifact_ids") or [None])[0],
                provider=(payload.get("usage") or {}).get("provider") if isinstance(payload.get("usage"), Mapping) else None,
                model=(payload.get("usage") or {}).get("model") if isinstance(payload.get("usage"), Mapping) else None,
                usage=payload.get("usage"),
                cache_status=cache_status,
            )
        )

    def submit(
        self,
        payload: Mapping[str, Any],
        *,
        operator_id: str | None = None,
    ) -> dict[str, Any]:
        """Validate and durably enqueue a run without executing it inline."""

        request, run_id = self._prepare_request(payload)
        operator = (operator_id or request.user_id).strip()
        if operator != request.user_id:
            raise PermissionError("user_id must match the authenticated operator")
        queued_payload = dict(payload)
        queued_payload["metadata"] = dict(request.metadata)
        state = self.scheduler.submit(run_id, queued_payload, operator_id=operator)
        return {
            "status": state.get("status", "queued"),
            "run_id": run_id,
            "task_id": request.task_id,
            "pipeline": None,
            "pipelines": list(request.requested_pipelines),
            "classification_level": request.classification_level,
            "distribution": request.distribution,
        }

    def resume(
        self,
        run_id: str,
        task_id: str,
        decision: Mapping[str, Any],
        *,
        operator_id: str | None = None,
    ) -> dict[str, Any]:
        current = self.status(run_id)
        if current.get("status") == "not_found":
            return {"run_id": run_id, "task_id": task_id, "status": "not_found"}
        if current.get("task_id") and current["task_id"] != task_id:
            raise PermissionError("task_id does not match the run")
        reviewer_id = decision.get("reviewer_id")
        if operator_id and reviewer_id is not None and str(reviewer_id).strip() != operator_id:
            raise PermissionError("reviewer_id must match the authenticated operator")
        result = self.orchestrator.resume(run_id, task_id, decision)
        output = orchestration_result_to_dict(result)
        if operator_id and decision.get("decision"):
            context = self._run_contexts.get(run_id, {})
            get_audit_logger().log_approval(
                operator_id=operator_id,
                reviewer_id=str(decision.get("reviewer_id", operator_id)),
                run_id=run_id,
                task_id=task_id,
                case_id=context.get("case_id", ""),
                decision=str(decision.get("decision")),
                classification=context.get("classification_level", "RESTRICTED"),
            )
        return output

    def cancel(
        self,
        run_id: str,
        task_id: str,
        *,
        operator_id: str | None = None,
    ) -> dict[str, str]:
        current = self.status(run_id)
        if current.get("status") != "not_found" and current.get("task_id") != task_id:
            raise PermissionError("task_id does not match the run")
        queued = getattr(self, "scheduler", None)
        if queued is not None and current.get("status") == "queued":
            cancelled = queued.cancel(run_id)
            if cancelled and cancelled.get("status") == "cancelled":
                return {
                    "run_id": run_id,
                    "task_id": task_id,
                    "status": "cancelled",
                }
        result = self.orchestrator.cancel(run_id, task_id)
        if result.get("status") in {"requested", "cancelled"}:
            context = self._run_contexts.get(run_id, {})
            get_audit_logger().log_cancellation(
                operator_id=operator_id or context.get("operator_id", "unknown"),
                run_id=run_id,
                task_id=task_id,
                case_id=context.get("case_id", ""),
                classification=context.get("classification_level", "RESTRICTED"),
            )
        return result

    def events(self, run_id: str, *, after_sequence: int = 0) -> list[dict[str, Any]]:
        projected: list[dict[str, Any]] = []
        for index, event in enumerate(
            self.progress_sink.events(run_id, after_sequence=after_sequence),
            start=1,
        ):
            payload = event_dict(event)
            sequence = int(payload.get("sequence") or after_sequence + index)
            projected.append(
                RunEvent.model_validate(
                    project_progress_event(payload, sequence=sequence).model_dump(mode="json")
                ).model_dump(mode="json")
            )
        return projected

    def telemetry(self, run_id: str) -> dict[str, Any]:
        """Return the safe aggregate used by the operator dashboard."""

        observability = getattr(self, "observability", None)
        if observability is None:
            return {"run_id": str(run_id), "event_count": 0}
        return observability.summary(str(run_id)).model_dump(mode="json")

    @staticmethod
    def _skill_id(pipeline: Any) -> str:
        aliases = {
            "presentation": "presentation.case-brief",
            "ppt": "presentation.case-brief",
            "video": "video.storyboard",
            "infographic": "infographic",
            "linkedin_post": "linkedin.post",
            "executive_summary": "executive.summary",
            "advisory": "advisory.brief",
        }
        value = str(pipeline or "").strip().lower()
        return aliases.get(value, value or "sudarshan.request")

    def _run_summary(
        self,
        values: Mapping[str, Any],
        events: list[dict[str, Any]],
    ) -> RunSummary:
        request = values.get("request") if isinstance(values.get("request"), Mapping) else {}
        pipeline = values.get("pipeline") or next(iter(values.get("requested_pipelines", ())), None)
        response = values.get("response") if isinstance(values.get("response"), Mapping) else {}
        responses = values.get("responses") if isinstance(values.get("responses"), Mapping) else {}
        status = str(values.get("status") or "queued")
        valid_statuses = {
            "accepted", "queued", "planning", "running", "waiting_on_dependency",
            "waiting_on_child_skill", "waiting_for_input", "waiting_for_approval",
            "retrying", "validating", "rendering", "quality_check", "repairing",
            "pending", "succeeded", "partial", "failed", "cancelled", "completed",
        }
        if status not in valid_statuses:
            status = "running"
        progress = max((int(event.get("progress", 0)) for event in events), default=0)
        if status in {"succeeded", "completed"}:
            progress = max(progress, 100)
        requires_action = bool(
            values.get("clarification_required")
            or (response.get("metadata") or {}).get("human_approval_required") is True
        )
        artifact_count = sum(
            1
            for candidate in [response, *responses.values()]
            if isinstance(candidate, Mapping) and candidate.get("artifact")
        )
        timestamps = [str(event["timestamp"]) for event in events if event.get("timestamp")]
        now = datetime.now(timezone.utc).isoformat()
        return RunSummary(
            run_id=str(values.get("run_id") or request.get("metadata", {}).get("run_id") or "run-unknown"),
            task_id=str(values.get("task_id") or request.get("task_id") or "task-unknown"),
            case_id=str(request.get("case_id") or self._run_contexts.get(str(values.get("run_id")), {}).get("case_id") or "case-unknown"),
            skill_id=self._skill_id(pipeline),
            skill_version=str(request.get("metadata", {}).get("skill_version") or "legacy"),
            execution_version=os.getenv("SUDARSHAN_EXECUTION_VERSION", "2026.1"),
            status=status,
            stage=str(values.get("stage") or "queued"),
            progress=progress,
            requires_action=requires_action,
            quality_status=str(values.get("quality_status") or "pending"),
            artifact_count=artifact_count,
            child_count=len(responses),
            error_code=values.get("error_code"),
            telemetry=TelemetrySummary.model_validate({
                key: value
                for key, value in self.telemetry(
                    str(values.get("run_id") or request.get("metadata", {}).get("run_id") or "run-unknown")
                ).items()
                if key != "run_id"
            }),
            created_at=timestamps[0] if timestamps else now,
            updated_at=timestamps[-1] if timestamps else now,
        )

    def status(self, run_id: str) -> dict[str, Any]:
        snapshot = self.orchestrator.graph.get_state({"configurable": {"thread_id": run_id}})
        values = dict(snapshot.values or {})
        if not values:
            queued = getattr(self, "scheduler", None)
            queue_state = queued.status(run_id) if queued is not None else None
            if queue_state:
                pipelines = list(queue_state.get("requested_pipelines") or [])
                pipeline = pipelines[0] if pipelines else None
                status = str(queue_state.get("status") or "queued")
                if status not in {"queued", "running", "retrying", "succeeded", "partial", "failed", "cancelled", "completed", "pending"}:
                    status = "queued"
                summary = RunSummary(
                    run_id=run_id,
                    task_id=str(queue_state.get("task_id") or "task-unknown"),
                    case_id=str(queue_state.get("case_id") or "case-unknown"),
                    skill_id=str(queue_state.get("skill_id") or self._skill_id(pipeline)),
                    skill_version=str(queue_state.get("skill_version") or "legacy"),
                    execution_version=os.getenv("SUDARSHAN_EXECUTION_VERSION", "2026.1"),
                    status=status,
                    stage=(
                        "queued" if status in {"queued", "retrying"}
                        else "completed" if status in {"succeeded", "completed"}
                        else status
                    ),
                    progress=0,
                    quality_status="pending",
                    telemetry=TelemetrySummary(),
                )
                return {
                    "run_id": run_id,
                    "task_id": queue_state.get("task_id"),
                    "status": status,
                    "stage": summary.stage,
                    "pipeline": pipeline,
                    "pipelines": pipelines,
                    "classification_level": queue_state.get("classification_level", "RESTRICTED"),
                    "clarification_required": False,
                    "clarification_questions": [],
                    "error": queue_state.get("error"),
                    "dead_letter": bool(queue_state.get("dead_letter", False)),
                    "skill_result": queue_state.get("skill_result"),
                    "events": [],
                    "summary": summary.model_dump(mode="json"),
                    "telemetry": self.telemetry(run_id),
                }
            return {"run_id": run_id, "status": "not_found", "events": self.events(run_id)}
        events = self.events(run_id)
        summary = self._run_summary(values, events)
        status_response = {
            "run_id": run_id,
            "task_id": values.get("task_id"),
            "status": values.get("status"),
            "stage": values.get("stage"),
            "pipeline": values.get("pipeline"),
            "pipelines": values.get("requested_pipelines", []),
            "classification_level": str(
                (values.get("request") or {}).get("classification_level")
                or self._run_contexts.get(run_id, {}).get("classification_level", "RESTRICTED")
            ),
            "clarification_required": values.get("clarification_required", False),
            "clarification_questions": values.get("clarification_questions", []),
            "error": values.get("error"),
            "events": events,
            "summary": summary.model_dump(mode="json"),
            "telemetry": self.telemetry(run_id),
        }
        # The projection is already serialized through the NTRO response
        # sanitizer and contains no prompts, raw memory, credentials, or
        # model reasoning. Include completed results so trusted API gateways
        # can return transformed outputs without calling pipeline internals.
        from pipelines.orchestrator.graph import _response_from_dict
        from pipelines.orchestrator.types import response_to_dict

        if values.get("response") is not None:
            status_response["response"] = response_to_dict(_response_from_dict(values["response"]))
        if values.get("responses"):
            status_response["responses"] = {
                str(name): response_to_dict(_response_from_dict(value))
                for name, value in values["responses"].items()
            }
        return status_response

    def wait(
        self,
        run_id: str,
        *,
        timeout_ms: int = 30_000,
        after_sequence: int = 0,
    ) -> dict[str, Any]:
        """Wait for terminal/actionable state without holding an HTTP request."""

        if timeout_ms < 0 or timeout_ms > 60_000:
            raise ValueError("timeout_ms must be between 0 and 60000")
        deadline = time.monotonic() + timeout_ms / 1000
        terminal = {"succeeded", "partial", "failed", "cancelled", "completed"}
        actionable = {"waiting_for_input", "waiting_for_approval", "pending"}
        while True:
            current = self.status(run_id)
            current_status = str(current.get("status", "not_found"))
            if current_status == "not_found" or current_status in terminal or current_status in actionable:
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))
        current["events"] = self.events(run_id, after_sequence=after_sequence)
        current["wait_timed_out"] = (
            current.get("status") not in {"not_found", *terminal, *actionable}
        )
        return current

    def health(self) -> dict[str, Any]:
        """Return system health for operational monitoring."""
        pipelines = self.list_pipelines()
        return {
            "status": "ok",
            "memory_system": "connected",
            "registered_pipelines": len(pipelines),
            "pipelines": pipelines,
            "routing_engine": "langgraph",
            "scheduler": self.scheduler.metrics(),
            "ingestion_scheduler": self.ingestion_scheduler.metrics(),
            "configuration": {
                "openai_api_key": bool(os.getenv("OPENAI_API_KEY", "").strip()),
                "cognee_api_key": bool(os.getenv("COGNEE_API_KEY", "").strip()),
                "cognee_base_url": bool(os.getenv("COGNEE_BASE_URL", "").strip()),
            },
        }

    def list_pipelines(self) -> list[str]:
        """Return registered pipeline names for frontend discovery."""
        return list(self.orchestrator.registry.keys())

    def get_artifact(
        self,
        artifact_id: str,
        *,
        classification_level: str = "RESTRICTED",
    ) -> dict[str, Any]:
        """Return a verified, frontend-safe artifact manifest.

        The MCP boundary exposes the stable download URI and integrity metadata,
        never the controlled filesystem path or artifact bytes.
        """

        from api.artifacts import ArtifactStore
        from pipelines.common.ntro_policy import require_classification_access

        root = os.getenv("SUDARSHAN_ARTIFACT_ROOT", "artifacts")
        manifest, _source = ArtifactStore(root).get(str(artifact_id).strip())
        require_classification_access(classification_level, manifest.classification_level)
        return {
            "artifact_id": manifest.artifact_id,
            "manifest": manifest.model_dump(mode="json"),
            "download_uri": manifest.uri,
            "integrity_verified": True,
        }

    def _evidence_context(
        self,
        user_id: str,
        case_id: str,
        task_id: str | None = None,
    ) -> AccessContext:
        return AccessContext(
            user_id=str(user_id).strip(),
            case_id=str(case_id).strip(),
            task_id=str(task_id).strip() if task_id else None,
        )

    def search_text_evidence(
        self,
        query: str,
        *,
        user_id: str,
        case_id: str,
        task_id: str | None = None,
        top_k: int = 10,
        classification_level: str = "RESTRICTED",
    ) -> list[dict[str, Any]]:
        return self.evidence_index.search_text(
            query,
            self._evidence_context(user_id, case_id, task_id),
            top_k=top_k,
            classification_level=classification_level,
        )

    def search_visual_evidence(
        self,
        query: str,
        *,
        user_id: str,
        case_id: str,
        task_id: str | None = None,
        top_k: int = 10,
        classification_level: str = "RESTRICTED",
    ) -> list[dict[str, Any]]:
        return self.evidence_index.search_visual(
            query,
            self._evidence_context(user_id, case_id, task_id),
            top_k=top_k,
            classification_level=classification_level,
        )

    def search_table_evidence(
        self,
        query: str,
        *,
        user_id: str,
        case_id: str,
        task_id: str | None = None,
        top_k: int = 10,
        classification_level: str = "RESTRICTED",
    ) -> list[dict[str, Any]]:
        return self.evidence_index.search_table(
            query,
            self._evidence_context(user_id, case_id, task_id),
            top_k=top_k,
            classification_level=classification_level,
        )

    def search_video_segment_evidence(
        self,
        query: str,
        *,
        user_id: str,
        case_id: str,
        task_id: str | None = None,
        top_k: int = 10,
        classification_level: str = "RESTRICTED",
    ) -> list[dict[str, Any]]:
        return self.evidence_index.search_video_segment(
            query,
            self._evidence_context(user_id, case_id, task_id),
            top_k=top_k,
            classification_level=classification_level,
        )

    def get_evidence(
        self,
        evidence_id: str,
        *,
        user_id: str,
        case_id: str,
        task_id: str | None = None,
        classification_level: str = "RESTRICTED",
    ) -> dict[str, Any]:
        return self.evidence_index.get_evidence(
            evidence_id,
            self._evidence_context(user_id, case_id, task_id),
            classification_level=classification_level,
        )

    def remember_context(self, user_id: str, case_id: str, context: str) -> None:
        """Persist User/Case-scoped session context."""
        from memory import AccessContext, KnowledgeUnit, ScopeType, Source, SourceType, MemoryType
        from uuid import uuid4
        import json
        
        mem_ctx = AccessContext(user_id=user_id, case_id=case_id)
        unit = KnowledgeUnit(
            unit_id=f"harness-ctx-{uuid4().hex[:8]}",
            content=json.dumps({"session_context": context}),
            source=Source(source_id="harness-session", source_type=SourceType.TEXT, source_reference="harness_session"),
            metadata={"origin": "harness"},
            provenance={"user_id": user_id, "case_id": case_id}
        )
        # Keep the same bounded context available at both permitted session
        # boundaries. Task-scoped events are written by the pipeline runtime
        # once a concrete task exists.
        self.orchestrator.memory_manager.remember(
            unit, mem_ctx, scope_type=ScopeType.USER, memory_type=MemoryType.FACT
        )
        self.orchestrator.memory_manager.remember(
            unit, mem_ctx, scope_type=ScopeType.CASE, memory_type=MemoryType.FACT
        )

    def recall_session_context(self, user_id: str, case_id: str, query: str) -> str:
        """Load prior User/Case context before routing."""
        from memory import AccessContext
        
        mem_ctx = AccessContext(user_id=user_id, case_id=case_id)
        recalled = self.orchestrator.memory_manager.recall(
            query=query,
            context=mem_ctx,
            top_k=5,
            token_budget=1000,
            session_id=f"harness-recall-{user_id}"
        )
        return str(recalled.context.text or "")

    @staticmethod
    def _ingestion_budget(value: Any, *, modality: str) -> IngestionBudget:
        """Return a bounded default without making existing uploads fail."""

        if value is not None:
            return IngestionBudget.model_validate(value)
        is_video = modality.lower() == "video"
        return IngestionBudget(
            token_budget=int(os.getenv("SUDARSHAN_INGESTION_TOKEN_BUDGET", "12000")),
            parser_units=1,
            ocr_calls=int(os.getenv("SUDARSHAN_INGESTION_OCR_CALLS", "64")),
            vision_calls=int(os.getenv("SUDARSHAN_INGESTION_VISION_CALLS", "64" if is_video else "16")),
            summary_tokens=int(os.getenv("SUDARSHAN_INGESTION_SUMMARY_TOKENS", "8192")),
            embedding_tokens=int(os.getenv("SUDARSHAN_INGESTION_EMBEDDING_TOKENS", "8000")),
            max_fan_out=int(os.getenv("SUDARSHAN_INGESTION_MAX_FAN_OUT", "64")),
            wall_time_seconds=int(os.getenv("SUDARSHAN_INGESTION_WALL_TIME_SECONDS", "300")),
        )

    @staticmethod
    def _file_hash(file_path: str) -> str:
        digest = hashlib.sha256()
        with open(file_path, "rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return f"sha256:{digest.hexdigest()}"

    @staticmethod
    def _cached_document_payload(document: IngestedDocument) -> dict[str, Any]:
        return {
            "id": document.id,
            "source_path": document.source_path,
            "raw_text": document.raw_text,
            "doc_type": document.doc_type,
            "ingested_at": document.ingested_at,
            "user_id": document.user_id,
            "case_id": document.case_id,
            "task_id": document.task_id,
            "evidence_blocks": [block.model_dump(mode="json") for block in document.evidence_blocks],
            "relationships": [item.model_dump(mode="json") for item in document.relationships],
            "chunks": [item.model_dump(mode="json") for item in document.chunks],
        }

    @staticmethod
    def _document_from_cache(
        payload: Mapping[str, Any],
        *,
        source_reference: str,
        user_id: str,
        case_id: str,
        task_id: str,
    ) -> IngestedDocument:
        from ingestion_pipelines.contracts import EvidenceChunk, EvidenceRelationship

        return IngestedDocument(
            id=str(payload["id"]),
            source_path=source_reference,
            raw_text=str(payload.get("raw_text", "")),
            doc_type=str(payload["doc_type"]),
            ingested_at=str(payload["ingested_at"]),
            user_id=user_id,
            case_id=case_id,
            task_id=task_id,
            evidence_blocks=[EvidenceBlock.model_validate(item) for item in payload.get("evidence_blocks", [])],
            relationships=[EvidenceRelationship.model_validate(item) for item in payload.get("relationships", [])],
            chunks=[EvidenceChunk.model_validate(item) for item in payload.get("chunks", [])],
        )

    @staticmethod
    def _budget_receipt(snapshot: Any) -> dict[str, Any]:
        return {
            "ingestion_id": snapshot.ingestion_id,
            "stage_units": dict(snapshot.stage_units),
            "stage_tokens": dict(snapshot.stage_tokens),
            "fan_out_used": snapshot.fan_out_used,
            "total_tokens": snapshot.total_tokens,
            "usage_is_estimate": True,
            "limits": snapshot.budget.model_dump(mode="json"),
        }

    def ingest_path(
        self,
        file_path: str,
        *,
        source_reference: str,
        operator_id: str,
        user_id: str,
        case_id: str,
        task_id: str,
        classification_level: str = "RESTRICTED",
        ingestion_id: str | None = None,
        source_hash: str | None = None,
        budget: IngestionBudget | Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Perform real source extraction and persist it through MemoryManager."""

        from ingestion_pipelines import ingest_file
        from pipelines.common.audit_logger import get_audit_logger
        from pipelines.common.ntro_policy import require_classification

        classification = require_classification(classification_level)
        resolved_ingestion_id = ingestion_id or f"direct-{uuid4().hex}"
        resolved_source_hash = source_hash or self._file_hash(file_path)
        resolved_budget = self._ingestion_budget(
            budget,
            modality=Path(file_path).suffix.lower().lstrip("."),
        )
        self.ingestion_budget_controller.register(resolved_ingestion_id, resolved_budget)
        scope = {"user_id": user_id, "case_id": case_id, "task_id": task_id}
        fingerprint = build_ingestion_stage_fingerprint(
            source_hash=resolved_source_hash,
            stage="parser",
            stage_version="ingestion-pipeline@2",
            configuration_hash=os.getenv("SUDARSHAN_INGESTION_CONFIGURATION_HASH", "local-default"),
            model_policy=os.getenv("SUDARSHAN_INGESTION_MODEL_POLICY", "local-first"),
            scope={**scope, "classification_level": classification},
        )
        cached = self.ingestion_stage_cache.get(
            fingerprint,
            scope=scope,
            classification_level=classification,
        )
        cache_status = "hit" if cached is not None else "miss"
        audit = get_audit_logger()
        try:
            if cached is not None:
                document = self._document_from_cache(
                    cached.payload,
                    source_reference=source_reference,
                    user_id=user_id,
                    case_id=case_id,
                    task_id=task_id,
                )
            else:
                self.ingestion_budget_controller.charge(
                    resolved_ingestion_id,
                    "parser",
                    units=1,
                    fan_out=1,
                )

                def charge_stage(stage: str, units: int, tokens: int, fan_out: int) -> object:
                    if tokens:
                        self.ingestion_usage.record_estimate(
                            resolved_ingestion_id,
                            stage=stage,
                            tokens=tokens,
                        )
                    return self.ingestion_budget_controller.charge(
                        resolved_ingestion_id,
                        stage,  # type: ignore[arg-type]
                        units=units,
                        tokens=tokens,
                        fan_out=fan_out,
                    )

                def record_usage(
                    stage: str,
                    provider: str,
                    model: str,
                    input_tokens: int,
                    output_tokens: int,
                    is_estimate: bool,
                ) -> object:
                    return self.ingestion_usage.record(
                        resolved_ingestion_id,
                        stage=stage,
                        provider=provider,
                        model=model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        is_estimate=is_estimate,
                    )

                document = ingest_file(
                    file_path,
                    user_id=user_id,
                    case_id=case_id,
                    task_id=task_id,
                    source_reference=source_reference,
                    stage_charger=charge_stage,
                    usage_recorder=record_usage,
                )
                evidence_count = len(document.evidence_blocks)
                if evidence_count > 1:
                    self.ingestion_budget_controller.charge(
                        resolved_ingestion_id,
                        "parser",
                        units=0,
                        fan_out=evidence_count - 1,
                    )
                self.ingestion_stage_cache.put(
                    fingerprint=fingerprint,
                    source_hash=resolved_source_hash,
                    stage="parser",
                    stage_version="ingestion-pipeline@2",
                    scope=scope,
                    classification_level=classification,
                    payload=self._cached_document_payload(document),
                    ttl_seconds=float(os.getenv("SUDARSHAN_INGESTION_CACHE_TTL_SECONDS", "86400")),
                )
            index_receipt = self.evidence_index.index_document(
                document,
                classification_level=classification,
            )
            memory_receipt = self.evidence_index.project_to_memory(
                document,
                self.orchestrator.memory_manager,
                classification_level=classification,
            )
            fallback_reasons = sorted(
                {
                    str(reason)
                    for block in document.evidence_blocks
                    for reason in (
                        [block.metadata.get("fallback_reason")]
                        if block.metadata.get("fallback_reason")
                        else list(block.metadata.get("fallbacks") or [])
                    )
                    if reason
                }
            )
            fallback_count = sum(
                1
                for block in document.evidence_blocks
                if block.metadata.get("ocr_fallback")
            ) + sum(
                len(set(block.metadata.get("fallbacks") or []))
                for block in document.evidence_blocks
            )
        except Exception as exc:
            audit.log(
                operator_id=operator_id,
                action="ingestion",
                status="failed",
                case_id=case_id,
                task_id=task_id,
                classification=classification,
                detail=f"source={source_reference}; error_type={type(exc).__name__}",
            )
            raise

        audit.log_ingestion(
            operator_id=operator_id,
            case_id=case_id,
            source_type=document.doc_type,
            source_reference=source_reference,
            classification=classification,
        )
        return {
            "status": "partial" if fallback_count else "succeeded",
            "document_id": document.id,
            "source_reference": source_reference,
            "doc_type": document.doc_type,
            "user_id": user_id,
            "case_id": case_id,
            "task_id": task_id,
            "classification_level": classification,
            "content_characters": len(document.raw_text),
            "memory_persisted": bool(memory_receipt.get("projected", False)),
            "evidence_indexed": bool(index_receipt.get("indexed", False)),
            "evidence_count": int(index_receipt.get("evidence_count", 0)),
            "chunk_count": int(index_receipt.get("chunk_count", 0)),
            "relationship_count": int(index_receipt.get("relationship_count", 0)),
            "evidence_memory_id": memory_receipt.get("memory_id"),
            "cache_status": cache_status,
            "cache_fingerprint": fingerprint,
            "fallback_count": fallback_count,
            "fallbacks": fallback_reasons,
            "budget": self._budget_receipt(
                self.ingestion_budget_controller.snapshot(resolved_ingestion_id)
            ),
            "usage": self.ingestion_usage.snapshot(resolved_ingestion_id),
            "ingested_at": document.ingested_at,
        }


_application: SudarshanApplication | None = None
_application_lock = Lock()


def get_application() -> SudarshanApplication:
    """Return the process-scoped application, constructing it lazily."""

    global _application
    if _application is None:
        with _application_lock:
            if _application is None:
                _application = SudarshanApplication()
    return _application
