"""Long-lived application boundary used by the Harness and backend adapters.

This module owns one orchestrator instance per Python service process. The
LangGraph checkpoint store makes paused runs recoverable across tool calls;
the progress sink makes the same run observable to a polling endpoint or an
SSE/WebSocket bridge owned by the backend.
"""

from __future__ import annotations

from threading import Event, Lock
import hashlib
import json
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
    VideoIngestionPolicy,
    build_ingestion_stage_fingerprint,
)
from ingestion_pipelines.evidence_index import EvidenceIndex
from pipelines.common.contracts import AdvisoryRequest
from pipelines.common.audit_logger import get_audit_logger
from api.control_plane import RedisControlPlane
from api.storage import build_object_store_from_env
from api.lifecycle import LifecycleCleaner
from api.scheduler import LocalRunScheduler
from pipelines.orchestrator import (
    BudgetController,
    CacheStore,
    CompositeObservabilityStore,
    JsonHttpObservabilityExporter,
    PipelineAdapter,
    RunContext,
    RunEvent,
    RunSummary,
    RedisProgressSink,
    RedisObservabilityStore,
    SkillCall,
    ChildTaskSpec,
    HarnessCorrelation,
    SkillRuntime,
    SQLiteProgressSink,
    ObservableProgressSink,
    SQLiteObservabilityStore,
    TelemetrySummary,
    event_dict,
    project_progress_event,
    orchestration_result_to_dict,
)
from pipelines.orchestrator.cross_skill import execute_child_plan
from pipelines.orchestrator.progress import ProgressEvent
from skills.catalog import (
    build_skill_manifests,
    canonical_skill_id,
    skill_pipeline,
    skill_summary,
)


class SudarshanApplication:
    """Own the real application services behind Harness-facing tools."""

    def __init__(self) -> None:
        # Keep the application boundary importable for artifact-only routes.
        # The graph pulls optional generation runtimes such as CrewAI, so load
        # it only when a live application instance is actually constructed.
        from pipelines.orchestrator.graph import PipelineOrchestrator, create_sqlite_checkpointer

        control_plane = self._build_control_plane()
        self.control_plane = control_plane
        self.control_plane_mode = "redis" if control_plane is not None else "sqlite"
        # Resolve the object store mode once here and reuse it below.
        # Reading SUDARSHAN_OBJECT_STORE_MODE a second time for the evidence
        # index (line ~143) caused the two paths to diverge when the env var
        # changed between calls in tests.
        self._object_store_mode = os.getenv("SUDARSHAN_OBJECT_STORE_MODE", "local").strip().lower()
        configured_object_store = build_object_store_from_env(
            os.getenv("SUDARSHAN_ARTIFACT_ROOT", "artifacts")
        )
        self.object_store = configured_object_store
        if self.object_store is None:
            # The application keeps a catalog object even in legacy local mode
            # so ingestion IDs and the dashboard can use one stable boundary.
            from api.storage import LocalObjectStore

            self.object_store = LocalObjectStore(
                os.getenv("SUDARSHAN_OBJECT_STORE_ROOT", "artifacts/.state/object-store")
            )
        local_observability = SQLiteObservabilityStore()
        exporter = None
        exporter_endpoint = os.getenv("SUDARSHAN_OBSERVABILITY_EXPORT_URL", "").strip()
        if exporter_endpoint:
            exporter = JsonHttpObservabilityExporter(
                exporter_endpoint,
                timeout_seconds=float(os.getenv("SUDARSHAN_OBSERVABILITY_EXPORT_TIMEOUT_SECONDS", "2")),
                bearer_token=os.getenv("SUDARSHAN_OBSERVABILITY_EXPORT_TOKEN"),
            )
        self.observability = CompositeObservabilityStore(
            local_observability,
            RedisObservabilityStore(control_plane) if control_plane is not None else None,
            exporter,
        )
        try:
            retention_seconds = int(os.getenv("SUDARSHAN_OBSERVABILITY_RETENTION_SECONDS", "2592000"))
        except ValueError:
            retention_seconds = 2592000
        self.observability.purge_expired(retention_seconds=max(1, retention_seconds), dry_run=False)
        progress_store = RedisProgressSink(control_plane) if control_plane is not None else SQLiteProgressSink()
        self.progress_sink = ObservableProgressSink(progress_store, self.observability)
        memory_manager = MemoryManager.from_env()
        memory_manager.operation_observer = self._record_memory_operation
        self.orchestrator = PipelineOrchestrator(
            memory_manager,
            progress_sink=self.progress_sink,
            checkpointer=create_sqlite_checkpointer(),
        )
        self.skill_manifests = build_skill_manifests()
        self.budget_controller = BudgetController(control_plane=control_plane)
        self.cache_store = CacheStore(
            os.getenv("SUDARSHAN_CACHE_DB_PATH", "artifacts/.state/skill_cache.db"),
            control_plane=control_plane,
        )
        self.cache_store.cleanup_expired()
        self.lifecycle = LifecycleCleaner(
            os.getenv("SUDARSHAN_ARTIFACT_ROOT", "artifacts"),
            object_store=self.object_store,
            cache_store=self.cache_store,
        )
        self.evidence_index = EvidenceIndex(
            os.getenv(
                "SUDARSHAN_EVIDENCE_INDEX_DB_PATH",
                "artifacts/.state/evidence_index.db",
            ),
            object_store=(
                self.object_store
                if self._object_store_mode in {"durable", "filesystem", "s3"}
                else None
            ),
        )
        self.ingestion_budget_controller = IngestionBudgetController(control_plane=control_plane)
        self.ingestion_usage = IngestionUsageRecorder(control_plane=control_plane)
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
        self._preparations: dict[str, dict[str, Any]] = {}
        self._preparations_lock = Lock()
        self.scheduler = LocalRunScheduler(
            self.run,
            db_path=os.getenv("SUDARSHAN_QUEUE_DB_PATH", "artifacts/.state/run_queue.db"),
            max_workers=int(os.getenv("SUDARSHAN_MAX_CONCURRENT_RUNS", "2")),
            lease_ms=int(os.getenv("SUDARSHAN_RUN_LEASE_MS", "900000")),
            max_attempts=int(os.getenv("SUDARSHAN_MAX_ATTEMPTS", "1")),
            retry_backoff_ms=int(os.getenv("SUDARSHAN_RETRY_BACKOFF_MS", "250")),
            execution_timeout_ms=int(os.getenv("SUDARSHAN_EXECUTION_TIMEOUT_MS", "0")),
            cancel_grace_period_ms=int(os.getenv("SUDARSHAN_CANCEL_GRACE_PERIOD_MS", "2000")),
            control_plane=control_plane,
            queue_name="runs",
            queue_reclaim_idle_ms=int(os.getenv("SUDARSHAN_RUN_QUEUE_RECLAIM_IDLE_MS", "1800000")),
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
            control_plane=control_plane,
            queue_name="ingestion",
            queue_reclaim_idle_ms=int(
                os.getenv("SUDARSHAN_INGESTION_QUEUE_RECLAIM_IDLE_MS", "1800000")
            ),
        )
        # NP-08: Shared public DAG projection store — a pure projection of run
        # state, not a second scheduler. Lazily created on first access via
        # get_dag() so that import-only usage does not incur disk I/O.
        self._dag_db_path = os.getenv(
            "SUDARSHAN_DAG_DB_PATH", "artifacts/.state/dag.db"
        )
        self._dag: Any | None = None  # type: DependencyDAG | None
        self._dag_lock = Lock()

    def _run_memory_lifecycle_pass(self) -> None:
        """Apply local expiry at a scheduler-owned execution boundary."""

        # Provider records still carry lifecycle metadata and are filtered in
        # MemoryManager.recall.  This pass keeps the local audit/store state in
        # sync for records whose explicit expiry has elapsed.
        expire_due = getattr(self.orchestrator.memory_manager, "expire_due", None)
        if callable(expire_due):
            expire_due()

    @staticmethod
    def _build_control_plane() -> RedisControlPlane | None:
        """Build the optional shared control plane without changing local defaults."""

        mode = os.getenv("SUDARSHAN_CONTROL_PLANE", "sqlite").strip().lower()
        if mode in {"", "sqlite", "local"}:
            return None
        if mode != "redis":
            raise ValueError(f"unsupported SUDARSHAN_CONTROL_PLANE mode: {mode}")
        url = os.getenv("SUDARSHAN_REDIS_URL", "").strip()
        if not url:
            raise ValueError("SUDARSHAN_REDIS_URL is required when SUDARSHAN_CONTROL_PLANE=redis")
        return RedisControlPlane.from_url(
            url,
            prefix=os.getenv("SUDARSHAN_CONTROL_PLANE_PREFIX", "sudarshan:control"),
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
        request_data = dict(data)
        # Transport/admission fields are not part of AdvisoryRequest. Keep
        # them in the queued payload, but never pass them into the typed
        # pipeline request constructor.
        for key in (
            "idempotency_key",
            "preparation_id",
            "context_pack",
            "evidence_refs",
            "budget_cap",
            "input_references",
            "target_pipeline",
            "parent_node_id",
            "lineage",
        ):
            request_data.pop(key, None)
        request = AdvisoryRequest(**request_data)

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

    def _resolve_lineage(
        self,
        payload: Mapping[str, Any],
        *,
        run_id: str,
        operator_id: str,
        is_revision: bool = False,
    ) -> Any:
        """Derive authoritative, tamper-proof execution lineage server-side."""
        from integrations.deepseek_harness.contracts import LineageContext

        data = dict(payload)
        metadata = dict(data.get("metadata") or {})
        parent_run_id = data.get("parent_run_id") or metadata.get("parent_run_id")
        parent_node_id = data.get("parent_node_id") or metadata.get("parent_node_id")

        if parent_run_id:
            parent_run_id = str(parent_run_id).strip()
            parent_state = self.status(parent_run_id)
            if parent_state.get("status") == "not_found":
                raise ValueError(f"parent_run_id does not exist: {parent_run_id}")
            parent_owner = (
                parent_state.get("user_id")
                or self._run_contexts.get(parent_run_id, {}).get("user_id")
                or self._run_contexts.get(parent_run_id, {}).get("operator_id")
            )
            if parent_owner and str(parent_owner).strip() != str(operator_id).strip():
                raise PermissionError("operator_id does not have authorization for parent_run_id")

            parent_lineage_raw = (
                parent_state.get("lineage")
                or self._run_contexts.get(parent_run_id, {}).get("lineage")
                or (parent_state.get("metadata") or {}).get("lineage")
            )
            if isinstance(parent_lineage_raw, Mapping):
                parent_lineage = LineageContext.model_validate(parent_lineage_raw)
                root_run_id = parent_lineage.root_run_id
                depth = parent_lineage.lineage_depth + 1
                rev_seq = parent_lineage.revision_sequence + (1 if is_revision else 0)
                causal = list(parent_lineage.causal_chain) + [parent_run_id]
                trace_id = parent_lineage.trace_id or parent_run_id
            else:
                root_run_id = parent_run_id
                depth = 1
                rev_seq = 1 if is_revision else 0
                causal = [parent_run_id]
                trace_id = parent_run_id

            return LineageContext(
                root_run_id=root_run_id,
                parent_run_id=parent_run_id,
                parent_node_id=str(parent_node_id) if parent_node_id else "parent-task",
                lineage_depth=depth,
                revision_sequence=rev_seq,
                causal_chain=causal,
                trace_id=trace_id,
            )

        # Root run
        return LineageContext(
            root_run_id=run_id,
            parent_run_id=None,
            parent_node_id=None,
            lineage_depth=0,
            revision_sequence=0,
            causal_chain=[run_id],
            trace_id=str(data.get("trace_id") or metadata.get("trace_id") or run_id),
        )

    def prepare(
        self, payload: Mapping[str, Any], *, operator_id: str | None = None
    ) -> dict[str, Any]:
        """Validate, authorize, and atomically persist a request preparation."""
        import hashlib
        import json
        from datetime import datetime, timedelta, timezone
        from pipelines.orchestrator.graph import _context_pack, _validate_context_scope
        from api.control_plane import ControlPlaneConflict
        from pipelines.orchestrator.contracts import RequestConstraints

        data = dict(payload)
        user_id = str(data.get("user_id", "")).strip()
        operator = (operator_id or user_id).strip()
        if operator != user_id:
            return {
                "status": "rejected",
                "rejection_code": "UNAUTHORIZED_USER",
                "rejection_reason": "user_id must match the authenticated operator",
            }

        idempotency_key = str(data.get("idempotency_key", "")).strip()
        if not idempotency_key:
            raise ValueError("idempotency_key is required")
        if len(idempotency_key) > 256:
            raise ValueError("idempotency_key must not exceed 256 characters")

        try:
            request, run_id = self._prepare_request(data)
            constraints = RequestConstraints.model_validate(data.get("constraints") or {})
        except (TypeError, ValueError) as exc:
            return {
                "status": "rejected",
                "rejection_code": "INVALID_REQUEST",
                "rejection_reason": str(exc)[:1000],
            }

        # Request preparation must not use task working memory before a
        # pipeline is selected. Task memory is execution context and is
        # recalled later by the grounding stage; preparation uses only the
        # authenticated User/Case context.
        preparation_context = AccessContext(
            user_id=request.user_id,
            case_id=request.case_id,
        )
        pack = _context_pack(
            self.orchestrator.memory_manager,
            query=request.query,
            context=preparation_context,
            run_id=run_id,
            stage_id="understanding",
            top_k=min(request.top_k, 8),
            token_budget=min(request.token_budget, 1200),
        )
        if pack is not None:
            _validate_context_scope(pack, request, allow_missing_task=True)

        fingerprint = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
        selected_pipelines = list(request.requested_pipelines)
        if not selected_pipelines:
            metadata = dict(data.get("metadata") or {})
            selected_pipelines = [
                str(item).strip().lower()
                for item in (metadata.get("pipelines") or [])
                if str(item).strip()
            ]
            if not selected_pipelines and metadata.get("pipeline"):
                selected_pipelines = [str(metadata["pipeline"]).strip().lower()]
        status = "prepared" if selected_pipelines else "needs_clarification"
        clarification_questions = (
            []
            if status == "prepared"
            else ["Which Sudarshan pipeline or pipelines should produce the requested output?"]
        )
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        memory_snapshot_id = (
            (pack.get("retrieval_trace_id") or pack.get("pack_id")) if pack else None
        )
        record = {
            "preparation_id": f"prep-{idempotency_key}",
            "context_pack_id": pack["pack_id"] if pack else "",
            "normalized_request": request.as_inputs(),
            "authorized_user_id": request.user_id,
            "case_id": request.case_id,
            "task_id": request.task_id,
            "classification": request.classification_level,
            "selected_pipelines": selected_pipelines,
            "constraint_set": constraints.model_dump(mode="json"),
            "evidence_refs": list(data.get("evidence_refs") or []),
            "status": status,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": expires_at,
            "memory_snapshot_id": memory_snapshot_id,
            "clarification_questions": clarification_questions,
            "request_fingerprint": fingerprint,
            "context_pack": pack,
        }

        cp = getattr(self.scheduler, "control_plane", None)
        if cp is not None and hasattr(cp, "preparation_create_if_absent"):
            try:
                record = cp.preparation_create_if_absent(idempotency_key, fingerprint, record)
            except ControlPlaneConflict:
                return {
                    "status": "rejected",
                    "rejection_code": "IDEMPOTENCY_CONFLICT",
                    "rejection_reason": "preparation key was already admitted with a different request fingerprint",
                }
        else:
            preparation_store = self.scheduler if hasattr(self.scheduler, "preparation_create_if_absent") else None
            if preparation_store is not None:
                record = preparation_store.preparation_create_if_absent(
                    idempotency_key, fingerprint, record
                )
            else:
                with self._preparations_lock:
                    existing = self._preparations.get(idempotency_key)
                    if existing:
                        if existing.get("request_fingerprint") != fingerprint:
                            return {
                                "status": "rejected",
                                "rejection_code": "IDEMPOTENCY_CONFLICT",
                                "rejection_reason": "preparation key was already admitted with a different request fingerprint",
                            }
                        record = existing
                    else:
                        self._preparations[idempotency_key] = record

        return {
            "status": record["status"],
            "preparation_id": record["preparation_id"],
            "context_pack_id": record["context_pack_id"],
            "normalized_request": record["normalized_request"],
            "expires_at": record["expires_at"],
            "memory_snapshot_id": record.get("memory_snapshot_id"),
            "clarification_questions": list(record.get("clarification_questions") or []),
        }

    def run(
        self,
        payload: Mapping[str, Any],
        *,
        operator_id: str | None = None,
        cancel_event: Event | None = None,
        attempt_id: str | None = None,
        lease_token: str | None = None,
    ) -> dict[str, Any]:
        self._run_memory_lifecycle_pass()
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
                output = self._invoke_skill_request(request, run_id=run_id, cancel_event=cancel_event, attempt_id=attempt_id, lease_token=lease_token)
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
                attempt_id=attempt_id,
                lease_token=lease_token,
            )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error(
                "run %s failed with %s: %s",
                run_id, type(exc).__name__, exc,
            )
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
        payload = orchestration_result_to_dict(result)
        # Required specialist children are part of the application release
        # boundary: reconcile them before returning success to the caller.
        self._execute_orchestration_child_plans(payload, request)
        audit.log_run_complete(
            operator_id=operator,
            case_id=request.case_id,
            task_id=request.task_id,
            run_id=run_id,
            classification=request.classification_level,
            pipeline=result.pipeline or "",
            status=payload.get("status", result.status),
        )
        return payload

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
        attempt_id: str | None = None,
        lease_token: str | None = None,
    ) -> dict[str, Any]:
        """Execute one admitted ingestion job without exposing source paths."""

        self._run_memory_lifecycle_pass()
        if cancel_event is not None and cancel_event.is_set():
            return {"status": "cancelled", "error": "ingestion cancelled before extraction"}
        try:
            result = self.ingest_path(
                str(payload.get("file_path", "")),
                source_reference=str(payload["source_reference"]),
                operator_id=operator_id,
                user_id=str(payload["user_id"]),
                case_id=str(payload["case_id"]),
                task_id=str(payload["task_id"]),
                classification_level=str(payload.get("classification_level", "RESTRICTED")),
                ingestion_id=str(payload.get("ingestion_id", payload.get("run_id", ""))) or None,
                source_hash=str(payload.get("source_hash", "")) or None,
                source_object_id=str(payload.get("source_object_id", "")) or None,
                budget=payload.get("budget"),
                video_policy=payload.get("video_policy"),
                cancel_event=cancel_event,
            )
        except RuntimeError as exc:
            if cancel_event is not None and cancel_event.is_set():
                return {"status": "cancelled", "error": str(exc)}
            raise
        if cancel_event is not None and cancel_event.is_set():
            return {"status": "cancelled", "error": "ingestion cancelled after extraction"}
        worker_status = result.get("status", "succeeded") if isinstance(result, Mapping) else "succeeded"
        qr = result.get("quality_report") if isinstance(result, Mapping) else None
        quality_status = (
            qr.get("status")
            if isinstance(qr, Mapping) and qr.get("status")
            else ("passed" if worker_status == "succeeded" else "partial")
        )
        return {
            "status": worker_status,
            "quality_status": quality_status,
            "skill_result": result,
        }

    def submit_ingestion(
        self,
        payload: Mapping[str, Any],
        *,
        operator_id: str,
    ) -> dict[str, Any]:
        """Admit source extraction asynchronously with verified hashing and safety."""

        from ingestion_pipelines.source_safety import inspect_source, SourceSafetyError
        from pipelines.common.ntro_policy import require_classification

        data = dict(payload)
        user_id = str(data.get("user_id", "")).strip()
        case_id = str(data.get("case_id", "")).strip()
        task_id = str(data.get("task_id", "")).strip()
        file_path = str(data.get("file_path", "")).strip()
        source_reference = str(data.get("source_reference", "")).strip()
        caller_supplied_hash = str(data.get("source_hash", "")).strip()
        if not all((user_id, case_id, task_id, file_path, source_reference)):
            raise ValueError("ingestion requires file_path, source_reference, user_id, case_id, and task_id")
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

        # Admission-time safety inspection and hash verification
        max_bytes = int(os.getenv("SUDARSHAN_MAX_INGEST_BYTES", str(50 * 1024 * 1024)))
        inspection = inspect_source(
            file_path,
            source_reference=source_reference,
            max_bytes=max_bytes,
            classification_level=data["classification_level"],
            user_id=user_id,
            case_id=case_id,
            task_id=task_id,
        )
        if caller_supplied_hash and caller_supplied_hash != inspection.source_hash:
            raise ValueError(
                f"source_hash mismatch: expected {inspection.source_hash}, got {caller_supplied_hash}"
            )
        source_hash = inspection.source_hash
        data["source_hash"] = source_hash
        data["media_type"] = inspection.media_type
        data["modality"] = inspection.modality
        if inspection.instruction_markers:
            data["instruction_markers"] = list(inspection.instruction_markers)

        budget = self._ingestion_budget(data.get("budget"), modality=inspection.modality)
        data["budget"] = budget.model_dump(mode="json")
        if self._object_store_enabled() and Path(file_path).is_file():
            source_object = self.object_store.put_file(
                file_path,
                kind="source",
                media_type=inspection.media_type,
                classification_level=data["classification_level"],
                owner_id=user_id,
                case_id=case_id,
                task_id=task_id,
                retention_class="source",
            )
            data["source_object_id"] = source_object.object_id
            data["file_path"] = str(source_object.path)

        idempotency_key = str(data.get("idempotency_key", "")).strip()
        if not idempotency_key:
            model_policy = str(data.get("model_policy") or os.getenv("SUDARSHAN_INGESTION_MODEL_POLICY", "local-first"))
            config_hash = str(data.get("configuration_hash") or os.getenv("SUDARSHAN_INGESTION_CONFIGURATION_HASH", "local-default"))
            video_policy_str = json.dumps(data.get("video_policy") or {}, sort_keys=True)
            identity = (
                f"{user_id}|{case_id}|{task_id}|{source_hash}|{data['classification_level']}|"
                f"{model_policy}|{config_hash}|{video_policy_str}"
            )
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
            "source_object_id": data.get("source_object_id"),
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
        result = state.get("skill_result")
        receipt = result if isinstance(result, Mapping) else {}
        quality_report = receipt.get("quality_report") if isinstance(receipt.get("quality_report"), Mapping) else None
        quality_status = (
            quality_report.get("status")
            if quality_report and quality_report.get("status")
            else state.get("quality_status")
            or {
                "succeeded": "passed",
                "partial": "partial",
                "failed": "failed",
            }.get(status, "pending")
        )
        return {
            "ingestion_id": state["run_id"],
            "task_id": state["task_id"],
            "case_id": state["case_id"],
            "status": status,
            "quality_status": quality_status,
            "quality_report": quality_report or {
                "status": quality_status,
                "fallback_count": receipt.get("fallback_count", 0),
                "fallbacks": list(receipt.get("fallbacks") or []),
                "evidence_count": receipt.get("evidence_count", 0),
                "chunk_count": receipt.get("chunk_count", 0),
                "relationship_count": receipt.get("relationship_count", 0),
                "low_confidence_count": receipt.get("low_confidence_count", 0),
                "memory_projection_status": receipt.get("memory_projection_status", "pending"),
                "review_state": receipt.get("review_state", "unreviewed"),
                "source_map_complete": receipt.get("source_map_complete", False),
            },
            "source_reference": state.get("source_reference"),
            "source_hash": state.get("source_hash"),
            "media_type": state.get("media_type"),
            "modality": state.get("modality"),
            "classification_level": state.get("classification_level", "RESTRICTED"),
            "attempt": state.get("attempt", 0),
            "queue_wait_ms": state.get("queue_wait_ms"),
            "error": state.get("error"),
            "dead_letter": bool(state.get("dead_letter", False)),
            "cache_status": receipt.get("cache_status"),
            "budget": receipt.get("budget"),
            "usage": receipt.get("usage"),
            "fallback_count": receipt.get("fallback_count", 0),
            "fallbacks": list(receipt.get("fallbacks") or []),
            "memory_projection_status": receipt.get("memory_projection_status", "pending"),
            "memory_projection_error": receipt.get("memory_projection_error"),
            "evidence_count": receipt.get("evidence_count", 0),
            "chunk_count": receipt.get("chunk_count", 0),
            "relationship_count": receipt.get("relationship_count", 0),
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
        attempt_id: str | None = None,
        lease_token: str | None = None,
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

        # Lineage resolution for child skill
        lineage = self._resolve_lineage(
            data,
            run_id=f"skill-{uuid4().hex[:8]}",
            operator_id=user_id,
        )
        metadata = dict(data.get("metadata") or {})
        metadata["lineage"] = lineage.model_dump(mode="json")
        metadata["parent_node_id"] = data.get("parent_node_id", "harness-skill")
        metadata["skill_id"] = canonical

        # Budget cap derivation: min of requested budget and manifest limit
        token_budget = manifest.budget_policy.max_model_tokens
        if data.get("budget_cap") and isinstance(data["budget_cap"], Mapping):
            cap = data["budget_cap"].get("max_model_tokens")
            if cap and isinstance(cap, int):
                token_budget = min(token_budget, cap)

        return self._invoke_skill_request(
            AdvisoryRequest(
                query=str(data.get("query", "")),
                user_id=user_id,
                case_id=str(data.get("case_id", "")),
                task_id=str(data.get("task_id", "")),
                classification_level=str(data.get("classification_level", "RESTRICTED")),
                distribution=str(data.get("distribution", "Authorized NTRO personnel")),
                token_budget=token_budget,
                metadata=metadata,
                requested_pipelines=(skill_pipeline(canonical) or canonical,),
            ),
            run_id=parent_run_id,
            skill_id=canonical,
            cancel_event=cancel_event,
            attempt_id=attempt_id,
            lease_token=lease_token,
        )

    def invoke_a2a(
        self,
        payload: Mapping[str, Any],
        *,
        operator_id: str,
        cancel_event: Event | None = None,
        attempt_id: str | None = None,
        lease_token: str | None = None,
    ) -> dict[str, Any]:
        """Execute a local specialist handoff using the portable A2A envelope."""

        from integrations.deepseek_harness.a2a import invoke_local_task

        return invoke_local_task(
            self,
            payload,
            operator_id=operator_id,
            cancel_event=cancel_event,
            attempt_id=attempt_id,
            lease_token=lease_token,
        )

    def _invoke_skill_request(
        self,
        request: AdvisoryRequest,
        *,
        run_id: str,
        skill_id: str | None = None,
        cancel_event: Event | None = None,
        attempt_id: str | None = None,
        lease_token: str | None = None,
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
            attempt_id=attempt_id,
            lease_token=lease_token,
            ancestors=tuple(request.metadata.get("ancestor_skills", ())),
            allowed_capabilities=frozenset(manifest.required_capabilities),
            allowed_tools=frozenset(manifest.allowed_tools),
            allowed_trust_tiers=frozenset({"builtin", "verified"}),
            cancel_event=cancel_event or Event(),
        )
        result = self.skill_runtime.invoke(call, parent_context=context)
        if result.status == "succeeded" and result.child_plan:
            try:
                specs = tuple(ChildTaskSpec.model_validate(item) for item in result.child_plan)
                outcomes = execute_child_plan(self.skill_runtime, specs, parent_context=context)
                result = result.model_copy(update={
                    "child_outcomes": [item.model_dump(mode="json") for item in outcomes],
                    "status": "failed" if any(item.delivery_blocked for item in outcomes) else "succeeded",
                    "failure_code": "REQUIRED_CHILD_FAILED" if any(item.delivery_blocked for item in outcomes) else None,
                })
            except Exception as exc:
                result = result.model_copy(update={
                    "status": "failed",
                    "failure_code": "CHILD_PLAN_FAILED",
                    "failure_message": str(exc),
                })
        top_level_status = {
            "succeeded": "succeeded",
            "waiting": "pending",
            "blocked": "failed",
            "failed": "failed",
            "cancelled": "cancelled",
        }[result.status]
        lineage_data = request.metadata.get("lineage")
        return {
            "status": top_level_status,
            "run_id": run_id,
            "task_id": request.task_id,
            "skill_id": canonical,
            "skill_version": manifest.version,
            "lineage": lineage_data,
            "artifacts": [
                {"artifact_id": art_id}
                for art_id in getattr(result, "artifact_ids", [])
            ],
            "quality_status": "passed" if top_level_status == "succeeded" else "partial",
            "skill_result": result.model_dump(mode="json"),
            "result": result.model_dump(mode="json"),
        }

    def _execute_orchestration_child_plans(
        self,
        payload: dict[str, Any],
        request: AdvisoryRequest,
    ) -> None:
        """Execute typed child plans emitted by real parent pipelines."""

        responses = []
        if isinstance(payload.get("response"), dict):
            responses.append(payload["response"])
        if isinstance(payload.get("responses"), dict):
            responses.extend(value for value in payload["responses"].values() if isinstance(value, dict))
        for response in responses:
            artifact = response.get("artifact")
            if not isinstance(artifact, dict) or not artifact.get("child_plan"):
                continue
            specs = tuple(ChildTaskSpec.model_validate(item) for item in artifact["child_plan"])
            if not specs:
                continue
            parent_run_id = specs[0].parent_run_id
            pipeline_value = response.get("pipeline") or (
                request.requested_pipelines[0] if request.requested_pipelines else ""
            )
            pipeline = str(pipeline_value)
            skill_id = canonical_skill_id(pipeline)
            manifest = self.skill_manifests.get(skill_id)
            if manifest is None:
                continue
            declared_children = manifest.coordination.get("children", [])
            child_capabilities = set(manifest.required_capabilities)
            child_tools = set(manifest.allowed_tools)
            for child_id in declared_children:
                child_manifest = self.skill_manifests.get(canonical_skill_id(str(child_id)))
                if child_manifest is not None:
                    child_capabilities.update(child_manifest.required_capabilities)
                    child_tools.update(child_manifest.allowed_tools)
            context = RunContext(
                run_id=parent_run_id,
                task_id=request.task_id,
                user_id=request.user_id,
                case_id=request.case_id,
                classification_level=request.classification_level,
                distribution=request.distribution,
                policy=manifest.budget_policy,
                allowed_capabilities=frozenset(child_capabilities),
                allowed_tools=frozenset(child_tools),
                allowed_trust_tiers=frozenset({"builtin", "verified"}),
            )
            try:
                outcomes = execute_child_plan(self.skill_runtime, specs, parent_context=context)
                artifact["child_outcomes"] = [item.model_dump(mode="json") for item in outcomes]
                artifact["child_plan_status"] = (
                    "blocked" if any(item.delivery_blocked for item in outcomes) else "completed"
                )
                self._project_visual_child(response, outcomes, specs)
                if any(item.delivery_blocked for item in outcomes):
                    response["status"] = "failed"
                    response["failure"] = "A required child skill failed its quality gate"
            except Exception as exc:
                artifact["child_plan_status"] = "failed"
                artifact["child_plan_error"] = str(exc)
                response["status"] = "failed"
                response["failure"] = "Child skill plan execution failed"
        statuses = [str(item.get("status")) for item in responses if isinstance(item, dict)]
        if statuses and all(status == "succeeded" for status in statuses):
            payload["status"] = "succeeded"
        elif any(status == "failed" for status in statuses):
            payload["status"] = "failed" if all(status == "failed" for status in statuses) else "partial"

    @staticmethod
    def _project_visual_child(
        response: dict[str, Any],
        outcomes: Any,
        specs: Any,
    ) -> None:
        """Reconcile child runtime state into the parent LinkedIn contract."""

        output = response.get("output")
        if not isinstance(output, dict):
            return
        visual = output.get("visual_child")
        if not isinstance(visual, dict) or not outcomes:
            return
        outcome = outcomes[0]
        spec = specs[0]
        status = "succeeded" if outcome.status == "succeeded" else "failed"
        visual.update({
            "skill_id": spec.skill_id,
            "status": status,
            "artifact_ids": list(outcome.artifact_ids),
            "quality_report_id": outcome.quality_report_id,
            "failure_code": outcome.failure_code,
        })

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
            "skill.partial": ("partial", 100, False),
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
                node_id=payload.get("node_id"),
                parent_node_id=payload.get("parent_node_id"),
                attempt_id=payload.get("attempt_id"),
                lane_id=payload.get("lane_id"),
                fallback=bool(payload.get("fallback", False)),
                provider_request_id=payload.get("provider_request_id"),
                usage_id=payload.get("usage_id"),
            )
        )

    def _record_memory_operation(self, name: str, payload: Mapping[str, Any]) -> None:
        """Record safe memory-provider lifecycle telemetry.

        The memory manager deliberately sends hashes, IDs, counts, and timing
        only. Raw Cognee requests and returned case content stay inside the
        memory boundary.
        """

        observability = getattr(self, "observability", None)
        if observability is not None:
            observability.record_runtime_event(name, payload)

    def submit(
        self,
        payload: Mapping[str, Any],
        *,
        operator_id: str | None = None,
    ) -> dict[str, Any]:
        """Validate and durably enqueue a run without executing it inline."""

        data = dict(payload)
        preparation_id = data.get("preparation_id")
        if preparation_id:
            idempotency_key = preparation_id.replace("prep-", "")
            cp = getattr(self.scheduler, "control_plane", None)
            if cp is not None and hasattr(cp, "preparation_get"):
                record = cp.preparation_get(idempotency_key)
            else:
                with self._preparations_lock:
                    record = self._preparations.get(idempotency_key)
            if not record:
                raise ValueError("Preparation not found or expired")
            if record.get("status") != "prepared":
                raise ValueError(
                    "Preparation cannot start until clarification is resolved"
                )
            operator = (operator_id or record.get("authorized_user_id", "")).strip()
            if operator != record.get("authorized_user_id"):
                raise PermissionError("user_id must match the authorized user of the preparation")
            data.update(record.get("normalized_request", {}))
            data["context_pack"] = record.get("context_pack")
            data["metadata"] = {
                **dict(data.get("metadata") or {}),
                "preparation_id": preparation_id,
                "context_pack": record.get("context_pack") or {},
                "memory_snapshot_id": record.get("memory_snapshot_id"),
            }

        # An explicit idempotency key must control the logical run identity.
        # Previously it was accepted by the MCP schema but ignored here,
        # allowing timeout retries to create a fresh run.
        idempotency_key = str(data.get("idempotency_key") or preparation_id or "").strip()
        if idempotency_key:
            metadata = dict(data.get("metadata") or {})
            metadata["run_id"] = f"run-{hashlib.sha256(idempotency_key.encode()).hexdigest()[:32]}"
            data["metadata"] = metadata

        request, run_id = self._prepare_request(data)
        operator = (operator_id or request.user_id).strip()
        if operator != request.user_id:
            raise PermissionError("user_id must match the authenticated operator")

        # Server-derived authoritative lineage
        is_revision = data.get("operation") == "revise" or bool(data.get("revision_instruction"))
        lineage = self._resolve_lineage(
            data,
            run_id=run_id,
            operator_id=operator,
            is_revision=is_revision,
        )
        request.metadata["lineage"] = lineage.model_dump(mode="json")
        queued_payload = dict(data)
        queued_payload["metadata"] = dict(request.metadata)
        queued_payload["lineage"] = lineage.model_dump(mode="json")

        with self._run_context_lock:
            self._run_contexts[run_id] = {
                "operator_id": operator,
                "user_id": request.user_id,
                "case_id": request.case_id,
                "task_id": request.task_id,
                "classification_level": request.classification_level,
                "lineage": lineage.model_dump(mode="json"),
            }

        state = self.scheduler.submit(run_id, queued_payload, operator_id=operator)
        return {
            "status": state.get("status", "queued"),
            "run_id": run_id,
            "task_id": request.task_id,
            "reused": bool(state.get("idempotent_replay", False)),
            "attempt_id": state.get("attempt_id"),
            "next_actions": ["get_sudarshan_status", "wait_sudarshan"],
            "dag_revision": 0,
            "lineage": lineage.model_dump(mode="json"),
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
        return observability.summary(
            str(run_id),
            access_level=os.getenv("SUDARSHAN_TELEMETRY_ACCESS_LEVEL", "RESTRICTED"),
        ).model_dump(mode="json")

    def observability_events(
        self,
        run_id: str,
        *,
        operator_id: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Return the sanitized operator trace, including memory operations."""

        observability = getattr(self, "observability", None)
        if observability is None:
            return {"status": "ready", "run_id": str(run_id), "events": [], "event_count": 0}
        events = observability.events(
            str(run_id),
            limit=max(1, min(int(limit), 5000)),
            access_level=os.getenv("SUDARSHAN_TELEMETRY_ACCESS_LEVEL", "RESTRICTED"),
            operator_id=operator_id,
        )
        return {
            "status": "ready",
            "run_id": str(run_id),
            "events": [event.model_dump(mode="json") for event in events],
            "event_count": len(events),
        }

    def trajectory(
        self,
        run_id: str,
        *,
        operator_id: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Return a safe Harness timeline and grouped parallel-lane summary.

        This is a projection of the existing observability events. It does not
        schedule work, infer dependencies, or replace the durable DAG.
        """

        projection = self.observability_events(
            run_id,
            operator_id=operator_id,
            limit=limit,
        )
        # A reconnecting Harness may replay the same durable event page. Keep
        # the projection stable by event identity and bounded by the caller's
        # requested limit; terminal runs do not grow an active trajectory.
        unique_events = []
        seen_event_ids: set[str] = set()
        for event in projection["events"]:
            event_id = str(event.get("event_id") or "")
            if event_id and event_id in seen_event_ids:
                continue
            if event_id:
                seen_event_ids.add(event_id)
            unique_events.append(event)
        projection["events"] = unique_events[-max(1, min(int(limit), 5000)):]
        projection["event_count"] = len(projection["events"])
        lane_state: dict[str, dict[str, Any]] = {}
        for event in projection["events"]:
            lane_id = (
                event.get("lane_id")
                or event.get("node_id")
                or event.get("child_id")
                or "main"
            )
            lane = lane_state.setdefault(
                str(lane_id),
                {
                    "lane_id": str(lane_id),
                    "event_count": 0,
                    "last_status": "",
                    "last_stage": "",
                },
            )
            lane["event_count"] += 1
            lane["last_status"] = event.get("status", "")
            lane["last_stage"] = event.get("stage", "")
        return {
            "status": projection["status"],
            "run_id": projection["run_id"],
            "events": projection["events"],
            "event_count": projection["event_count"],
            "lanes": list(lane_state.values()),
        }

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
            harness_correlation=HarnessCorrelation.from_metadata(
                request.get("metadata", {})
            ),
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
                    "user_id": queue_state.get("user_id") or self._run_contexts.get(run_id, {}).get("user_id"),
                    "case_id": queue_state.get("case_id") or self._run_contexts.get(run_id, {}).get("case_id"),
                    "status": status,
                    "stage": summary.stage,
                    "pipeline": pipeline,
                    "pipelines": pipelines,
                    "classification_level": queue_state.get("classification_level", "RESTRICTED"),
                    "clarification_required": False,
                    "clarification_questions": [],
                    "error": queue_state.get("error"),
                    "dead_letter": bool(queue_state.get("dead_letter", False)),
                    "lineage": queue_state.get("lineage") or self._run_contexts.get(run_id, {}).get("lineage"),
                    "skill_result": queue_state.get("skill_result"),
                    "harness_correlation": queue_state.get("harness_correlation"),
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
            "user_id": (values.get("request") or {}).get("user_id") or self._run_contexts.get(run_id, {}).get("user_id"),
            "case_id": (values.get("request") or {}).get("case_id") or self._run_contexts.get(run_id, {}).get("case_id"),
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
            "harness_correlation": (
                summary.harness_correlation.model_dump(mode="json")
                if summary.harness_correlation is not None
                else None
            ),
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
        cognee_backend = os.getenv("COGNEE_BACKEND", "cloud").strip().lower() or "cloud"
        return {
            "status": "ok",
            "memory_system": "connected",
            "memory_backend": "cognee_cloud" if cognee_backend == "cloud" else "cognee_local_dev",
            "memory_cloud_configured": bool(
                cognee_backend == "cloud"
                and os.getenv("COGNEE_BASE_URL", "").strip()
                and os.getenv("COGNEE_API_KEY", "").strip()
                and os.getenv("COGNEE_TENANT_ID", "").strip()
            ),
            "registered_pipelines": len(pipelines),
            "pipelines": pipelines,
            "routing_engine": "langgraph",
            "control_plane": {
                "mode": self.control_plane_mode,
                "shared": self.control_plane is not None,
                "ingestion_stage_budget": "shared" if self.control_plane is not None else "process-local",
                "ingestion_stage_budget_next": None if self.control_plane is not None else "configure Redis for multi-worker sharing",
            },
            "storage": {
                "object_store_mode": os.getenv("SUDARSHAN_OBJECT_STORE_MODE", "local"),
                "observability_retention_seconds": os.getenv(
                    "SUDARSHAN_OBSERVABILITY_RETENTION_SECONDS", "2592000"
                ),
            },
            "scheduler": self.scheduler.metrics(),
            "ingestion_scheduler": self.ingestion_scheduler.metrics(),
            "configuration": {
                "openai_api_key": bool(os.getenv("OPENAI_API_KEY", "").strip()),
                "cognee_api_key": bool(os.getenv("COGNEE_API_KEY", "").strip()),
                "cognee_base_url": bool(os.getenv("COGNEE_BASE_URL", "").strip()),
            },
        }

    def cleanup_lifecycle(self, *, dry_run: bool = True, older_than_seconds: float = 86_400) -> dict[str, Any]:
        """Run the lineage-aware cleanup boundary for an operator or job."""

        return self.lifecycle.cleanup(
            dry_run=dry_run,
            older_than_seconds=older_than_seconds,
        ).to_dict()

    def list_pipelines(self) -> list[str]:
        """Return registered pipeline names for frontend discovery."""
        return list(self.orchestrator.registry.keys())

    def get_artifact(
        self,
        artifact_id: str,
        *,
        classification_level: str = "RESTRICTED",
        user_id: str | None = None,
        case_id: str | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """Return a verified, frontend-safe artifact manifest.

        The MCP boundary exposes the stable download URI and integrity metadata,
        never the controlled filesystem path or artifact bytes.
        """

        import mimetypes

        from api.artifacts import ArtifactStore
        from pipelines.common.ntro_policy import require_classification_access

        root = os.getenv("SUDARSHAN_ARTIFACT_ROOT", "artifacts")
        manifest, _source = ArtifactStore(root).get(str(artifact_id).strip())
        require_classification_access(classification_level, manifest.classification_level)
        if not all((manifest.user_id, manifest.case_id, manifest.task_id)):
            raise PermissionError("artifact ownership is unavailable")
        if not user_id or user_id != manifest.user_id:
            raise PermissionError("artifact owner is not authorized")
        if not case_id or case_id != manifest.case_id:
            raise PermissionError("artifact case is not authorized")
        if task_id != manifest.task_id:
            raise PermissionError("artifact task is not authorized")
        # ArtifactManifest intentionally stores only the portable contract; it
        # does not expose filesystem-derived MIME/provenance attributes. Infer
        # the public media type from the manifest name and keep provenance in
        # the explicit metadata field instead of reaching through stale fields.
        mime_type = mimetypes.guess_type(manifest.name, strict=False)[0] or "application/octet-stream"
        return {
            "artifact_id": manifest.artifact_id,
            "uri": manifest.uri,
            "mime_type": mime_type,
            "sha256": manifest.sha256,
            "classification_level": manifest.classification_level,
            "created_at": manifest.created_at,
            "provenance": dict(manifest.metadata.get("provenance", {})),
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
    def _object_store_enabled() -> bool:
        return os.getenv("SUDARSHAN_OBJECT_STORE_MODE", "local").strip().lower() in {
            "durable", "filesystem", "s3"
        }

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
        source_object_id: str | None = None,
        budget: IngestionBudget | Mapping[str, Any] | None = None,
        video_policy: VideoIngestionPolicy | Mapping[str, Any] | None = None,
        cancel_event: Event | None = None,
    ) -> dict[str, Any]:
        """Perform real source extraction and persist it through MemoryManager."""

        from ingestion_pipelines import ingest_file
        from pipelines.common.audit_logger import get_audit_logger
        from pipelines.common.ntro_policy import require_classification

        classification = require_classification(classification_level)
        resolved_ingestion_id = ingestion_id or f"direct-{uuid4().hex}"
        extraction_path = file_path
        if source_object_id:
            source_object = self.object_store.get(
                source_object_id,
                access_level="TOP SECRET",
                owner_id=user_id,
                case_id=case_id,
                task_id=task_id,
            )
            extraction_path = str(source_object.path)
        elif self._object_store_enabled():
            source_object = self.object_store.put_file(
                file_path,
                kind="source",
                media_type="application/octet-stream",
                classification_level=classification,
                owner_id=user_id,
                case_id=case_id,
                task_id=task_id,
                run_id=resolved_ingestion_id,
                retention_class="source",
            )
            source_object_id = source_object.object_id
            extraction_path = str(source_object.path)
        resolved_source_hash = source_hash or self._file_hash(extraction_path)
        resolved_budget = self._ingestion_budget(
            budget,
            modality=Path(extraction_path).suffix.lower().lstrip("."),
        )
        resolved_video_policy: VideoIngestionPolicy | None = None
        if Path(extraction_path).suffix.lower() in {".mp4", ".mov", ".avi", ".mkv", ".webm"}:
            from ingestion_pipelines.extract_video import default_video_ingestion_policy

            resolved_video_policy = (
                video_policy
                if isinstance(video_policy, VideoIngestionPolicy)
                else VideoIngestionPolicy.model_validate(video_policy)
                if isinstance(video_policy, Mapping)
                else default_video_ingestion_policy()
            )
        if cancel_event is not None and cancel_event.is_set():
            return {"status": "cancelled", "error": "ingestion cancelled before extraction"}
        self.ingestion_budget_controller.register(resolved_ingestion_id, resolved_budget)
        scope = {"user_id": user_id, "case_id": case_id, "task_id": task_id}
        fingerprint = build_ingestion_stage_fingerprint(
            source_hash=resolved_source_hash,
            stage="parser",
            stage_version="ingestion-pipeline@2",
            configuration_hash=(
                os.getenv("SUDARSHAN_INGESTION_CONFIGURATION_HASH", "local-default")
                + ("|video-policy=" + json.dumps(resolved_video_policy.model_dump(mode="json"), sort_keys=True)
                   if resolved_video_policy is not None else "")
            ),
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
                    extraction_path,
                    user_id=user_id,
                    case_id=case_id,
                    task_id=task_id,
                    source_reference=source_reference,
                    stage_charger=charge_stage,
                    usage_recorder=record_usage,
                    video_policy=resolved_video_policy,
                    cancel_event=cancel_event,
                )
                if cancel_event is not None and cancel_event.is_set():
                    return {"status": "cancelled", "error": "ingestion cancelled after extraction"}
                evidence_count = len(document.evidence_blocks)
                if evidence_count > 1:
                    self.ingestion_budget_controller.charge(
                        resolved_ingestion_id,
                        "parser",
                        units=0,
                        fan_out=evidence_count - 1,
                    )
                if cancel_event is not None and cancel_event.is_set():
                    return {"status": "cancelled", "error": "ingestion cancelled before cache write"}
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
            if cancel_event is not None and cancel_event.is_set():
                return {"status": "cancelled", "error": "ingestion cancelled before indexing"}
            index_receipt = self.evidence_index.index_document(
                document,
                classification_level=classification,
            )
            if cancel_event is not None and cancel_event.is_set():
                return {"status": "cancelled", "error": "ingestion cancelled before memory projection"}
            try:
                memory_receipt = self.evidence_index.project_to_memory(
                    document,
                    self.orchestrator.memory_manager,
                    classification_level=classification,
                )
                memory_projection_status = "succeeded" if memory_receipt.get("projected") else "failed"
                memory_projection_error = memory_receipt.get("error") if not memory_receipt.get("projected") else None
            except Exception as exc:
                memory_receipt = {
                    "projected": False,
                    "memory_id": None,
                    "error": str(exc),
                }
                memory_projection_status = "failed"
                memory_projection_error = str(exc)

            if cancel_event is not None and cancel_event.is_set():
                return {"status": "cancelled", "error": "ingestion cancelled after memory projection"}

            raw_fallbacks = set()
            for block in document.evidence_blocks:
                block_fallbacks: set[str] = set()
                if block.metadata.get("fallback_reason"):
                    block_fallbacks.add(str(block.metadata["fallback_reason"]))
                for fb in (block.metadata.get("fallbacks") or []):
                    if fb:
                        block_fallbacks.add(str(fb))
                if block.metadata.get("ocr_fallback") and not block_fallbacks:
                    block_fallbacks.add("ocr_fallback")
                raw_fallbacks.update(block_fallbacks)
            fallback_reasons = sorted(raw_fallbacks)
            fallback_count = len(fallback_reasons)
            low_confidence_count = sum(1 for block in document.evidence_blocks if block.confidence < 0.7)

            if (
                fallback_count > 0
                or low_confidence_count > 0
                or memory_projection_status == "failed"
            ):
                status = "partial"
                quality_status = "partial"
            else:
                status = "succeeded"
                quality_status = "passed"

            from ingestion_pipelines.contracts import IngestionQualityReport

            quality_report = IngestionQualityReport(
                quality_report_id=f"qr-{resolved_ingestion_id}",
                ingestion_id=resolved_ingestion_id,
                document_id=document.id,
                status=quality_status,
                coverage={
                    "evidence_count": len(document.evidence_blocks),
                    "chunk_count": len(document.chunks),
                    "relationship_count": len(document.relationships),
                },
                block_counts={
                    block.modality: sum(1 for b in document.evidence_blocks if b.modality == block.modality)
                    for block in document.evidence_blocks
                },
                low_confidence_count=low_confidence_count,
                fallback_count=fallback_count,
                fallbacks=fallback_reasons,
                evidence_count=len(document.evidence_blocks),
                chunk_count=len(document.chunks),
                relationship_count=len(document.relationships),
                memory_projection_status=memory_projection_status,
                review_state="unreviewed",
                source_map_complete=bool(document.evidence_blocks and document.chunks),
                cache_hits=1 if cache_status == "hit" else 0,
                usage_is_estimate=True,
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
            "status": status,
            "quality_status": quality_status,
            "quality_report": quality_report.model_dump(mode="json"),
            "document_id": document.id,
            "source_reference": source_reference,
            "source_object_id": source_object_id,
            "doc_type": document.doc_type,
            "user_id": user_id,
            "case_id": case_id,
            "task_id": task_id,
            "classification_level": classification,
            "content_characters": len(document.raw_text),
            "memory_persisted": bool(memory_receipt.get("projected", False)),
            "memory_projection_status": memory_projection_status,
            "memory_projection_error": memory_projection_error,
            "evidence_indexed": bool(index_receipt.get("indexed", False)),
            "evidence_count": int(index_receipt.get("evidence_count", 0)),
            "chunk_count": int(index_receipt.get("chunk_count", 0)),
            "relationship_count": int(index_receipt.get("relationship_count", 0)),
            "low_confidence_count": low_confidence_count,
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

    def _dag_store(self) -> "Any":  # returns DependencyDAG
        """Return the shared public DAG store, creating it lazily."""
        if self._dag is None:
            with self._dag_lock:
                if self._dag is None:
                    from pipelines.orchestrator.dag import DependencyDAG

                    self._dag = DependencyDAG(
                        db_path=self._dag_db_path,
                        control_plane=self.control_plane,
                    )
        return self._dag

    def get_dag(
        self,
        run_id: str,
        operator_id: str,
        *,
        after_revision: int = -1,
        include_failure_details: bool = False,
    ) -> dict[str, Any]:
        """Return a public DAG snapshot for *run_id*.

        This is the secure application boundary for all DAG reads (HTTP and
        MCP). Authorization is checked before the DAG is accessed.

        Parameters
        ----------
        run_id:
            The run whose DAG to read.
        operator_id:
            The caller's operator ID. Must match the operator that created the
            run, or hold elevated permissions in the durable run context.
        after_revision:
            If provided and the DAG revision has not advanced past this value,
            returns ``{"status": "not_changed"}`` immediately.
        include_failure_details:
            When ``True``, ``failure_code`` and ``safe_failure_summary`` are
            included in the response for failed / blocked nodes. Callers must
            hold elevated permissions to set this flag.

        Returns
        -------
        dict
            Serialised :class:`~pipelines.orchestrator.contracts.PublicDAGGraph`
            or ``{"status": "not_changed"}`` when the revision has not advanced.

        Raises
        ------
        PermissionError
            When *operator_id* does not match the run's stored operator.
        KeyError
            When *run_id* does not exist in the DAG store.
        """
        from pipelines.orchestrator.dag import DAGError

        # Authorization: check the durable run context.
        with self._run_context_lock:
            ctx = self._run_contexts.get(run_id)
        if ctx is not None and ctx.get("operator_id") != operator_id:
            raise PermissionError(
                f"operator '{operator_id}' is not authorised to read run '{run_id}'"
            )

        dag = self._dag_store()
        try:
            graph = dag.get_public_dag(
                run_id,
                after_revision=after_revision,
                include_failure_details=include_failure_details,
            )
        except DAGError as exc:
            raise KeyError(run_id) from exc

        if graph is None:
            return {"status": "not_changed"}
        return graph.model_dump(mode="json")

    def dag_graph(self, run_id: str, operator_id: str) -> dict[str, Any]:
        """Compatibility alias for callers asking for the run graph."""
        return self.get_dag(run_id, operator_id)


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
