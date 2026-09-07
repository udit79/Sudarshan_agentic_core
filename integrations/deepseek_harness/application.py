"""Long-lived application boundary used by the Harness and backend adapters.

This module owns one orchestrator instance per Python service process. The
LangGraph checkpoint store makes paused runs recoverable across tool calls;
the progress sink makes the same run observable to a polling endpoint or an
SSE/WebSocket bridge owned by the backend.
"""

from __future__ import annotations

from threading import Lock
import os
from uuid import uuid4
from typing import Any, Mapping

from memory import MemoryManager
from pipelines.common.contracts import AdvisoryRequest
from pipelines.common.audit_logger import get_audit_logger
from pipelines.orchestrator import (
    PipelineOrchestrator,
    SQLiteProgressSink,
    create_sqlite_checkpointer,
    event_dict,
    orchestration_result_to_dict,
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
        self._run_contexts: dict[str, dict[str, str]] = {}
        self._run_context_lock = Lock()

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
            result = self.orchestrator.run(request, run_id=run_id)
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

    def events(self, run_id: str) -> list[dict[str, Any]]:
        return [event_dict(event) for event in self.progress_sink.events(run_id)]

    def status(self, run_id: str) -> dict[str, Any]:
        snapshot = self.orchestrator.graph.get_state({"configurable": {"thread_id": run_id}})
        values = dict(snapshot.values or {})
        if not values:
            return {"run_id": run_id, "status": "not_found", "events": self.events(run_id)}
        status_response = {
            "run_id": run_id,
            "task_id": values.get("task_id"),
            "status": values.get("status"),
            "stage": values.get("stage"),
            "pipeline": values.get("pipeline"),
            "pipelines": values.get("requested_pipelines", []),
            "clarification_required": values.get("clarification_required", False),
            "clarification_questions": values.get("clarification_questions", []),
            "error": values.get("error"),
            "events": self.events(run_id),
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

    def health(self) -> dict[str, Any]:
        """Return system health for operational monitoring."""
        pipelines = self.list_pipelines()
        return {
            "status": "ok",
            "memory_system": "connected",
            "registered_pipelines": len(pipelines),
            "pipelines": pipelines,
            "routing_engine": "langgraph",
            "configuration": {
                "openai_api_key": bool(os.getenv("OPENAI_API_KEY", "").strip()),
                "cognee_api_key": bool(os.getenv("COGNEE_API_KEY", "").strip()),
                "cognee_base_url": bool(os.getenv("COGNEE_BASE_URL", "").strip()),
            },
        }

    def list_pipelines(self) -> list[str]:
        """Return registered pipeline names for frontend discovery."""
        return list(self.orchestrator.registry.keys())

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
