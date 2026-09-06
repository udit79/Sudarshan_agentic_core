"""Long-lived application boundary used by the Harness and backend adapters.

This module owns one orchestrator instance per Python service process. The
LangGraph checkpoint store makes paused runs recoverable across tool calls;
the progress sink makes the same run observable to a polling endpoint or an
SSE/WebSocket bridge owned by the backend.
"""

from __future__ import annotations

from threading import Lock
from typing import Any, Mapping

from memory import MemoryManager
from pipelines.common.contracts import AdvisoryRequest
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

    def run(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        result = self.orchestrator.run(AdvisoryRequest(**dict(payload)))
        return orchestration_result_to_dict(result)

    def resume(self, run_id: str, task_id: str, decision: Mapping[str, Any]) -> dict[str, Any]:
        result = self.orchestrator.resume(run_id, task_id, decision)
        return orchestration_result_to_dict(result)

    def cancel(self, run_id: str, task_id: str) -> dict[str, str]:
        return self.orchestrator.cancel(run_id, task_id)

    def events(self, run_id: str) -> list[dict[str, Any]]:
        return [event_dict(event) for event in self.progress_sink.events(run_id)]

    def status(self, run_id: str) -> dict[str, Any]:
        snapshot = self.orchestrator.graph.get_state({"configurable": {"thread_id": run_id}})
        values = dict(snapshot.values or {})
        if not values:
            return {"run_id": run_id, "status": "not_found", "events": self.events(run_id)}
        return {
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

    def health(self) -> dict[str, Any]:
        """Return system health for operational monitoring."""
        pipelines = self.list_pipelines()
        return {
            "status": "ok",
            "memory_system": "connected",
            "registered_pipelines": len(pipelines),
            "pipelines": pipelines,
            "routing_engine": "langgraph"
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
        self.orchestrator.memory_manager.remember(unit, mem_ctx, scope_type=ScopeType.CASE, memory_type=MemoryType.FACT)

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
