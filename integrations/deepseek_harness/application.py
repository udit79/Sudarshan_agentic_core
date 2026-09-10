"""Long-lived application boundary used by the Harness and backend adapters.

This module owns one orchestrator instance per Python service process. The
LangGraph checkpoint store makes paused runs recoverable across tool calls;
the progress sink makes the same run observable to a polling endpoint or an
SSE/WebSocket bridge owned by the backend.
"""

from __future__ import annotations

from threading import Event, Lock
import os
from datetime import datetime, timezone
import time
from uuid import uuid4
from typing import Any, Mapping

from memory import MemoryManager
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
        self.progress_sink = SQLiteProgressSink()
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
    ) -> dict[str, Any]:
        """Perform real source extraction and persist it through MemoryManager."""

        from ingestion_pipelines import ingest_file
        from pipelines.common.audit_logger import get_audit_logger
        from pipelines.common.ntro_policy import require_classification

        classification = require_classification(classification_level)
        audit = get_audit_logger()
        try:
            document = ingest_file(
                file_path,
                user_id=user_id,
                case_id=case_id,
                task_id=task_id,
                memory_manager=self.orchestrator.memory_manager,
                source_reference=source_reference,
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
            "status": "succeeded",
            "document_id": document.id,
            "source_reference": source_reference,
            "doc_type": document.doc_type,
            "user_id": user_id,
            "case_id": case_id,
            "task_id": task_id,
            "classification_level": classification,
            "content_characters": len(document.raw_text),
            "memory_persisted": True,
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
