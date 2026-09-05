"""LangGraph router for all Sudarshan application-specific pipelines.

LangGraph owns the run lifecycle and routing. Registered pipeline adapters
continue to own CrewAI collaboration and call MemoryManager through their
existing controlled interfaces.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Callable, Mapping, TypedDict
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from memory import MemoryManager
from pipelines.advisory.crew import AdvisoryFlow
from pipelines.common.contracts import AdvisoryRequest, PipelineResponse
from pipelines.common.memory_tools import MemoryRuntime, TaskMemoryWriter
from pipelines.executive_summary.crew import ExecutiveSummaryFlow
from pipelines.infographic.crew import InfographicFlow
from pipelines.linkedin.crew import LinkedInPostFlow
from pipelines.orchestrator.progress import (
    InMemoryProgressSink,
    ProgressReporter,
    ProgressSink,
)
from pipelines.orchestrator.types import (
    OrchestrationResult,
    PipelineAdapter,
    response_to_dict,
)
from pipelines.orchestrator.understanding import (
    PromptCrafterAgent,
    RequestUnderstandingAgent,
    default_intent_resolver,
)


class OrchestratorState(TypedDict):
    request: dict[str, Any]
    run_id: str
    task_id: str
    pipeline: str
    understanding: dict[str, Any]
    memory_context: str
    memory_records: list[dict[str, Any]]
    prompt_plan: dict[str, Any]
    response: dict[str, Any] | None
    approval_decision: dict[str, Any] | None
    error: str | None
    stage: str
    status: str


IntentResolver = Callable[[AdvisoryRequest], str]


def _request_from_dict(data: Mapping[str, Any]) -> AdvisoryRequest:
    return AdvisoryRequest(
        query=str(data["query"]),
        user_id=str(data["user_id"]),
        case_id=str(data["case_id"]),
        task_id=str(data["task_id"]),
        classification_level=str(data.get("classification_level", "RESTRICTED")),
        distribution=str(data.get("distribution", "Authorized NTRO personnel")),
        top_k=int(data.get("top_k", 12)),
        token_budget=int(data.get("token_budget", 6000)),
        metadata=data.get("metadata", {}),
    )


def _request_to_dict(request: AdvisoryRequest) -> dict[str, Any]:
    return {
        "query": request.query,
        "user_id": request.user_id,
        "case_id": request.case_id,
        "task_id": request.task_id,
        "classification_level": request.classification_level,
        "distribution": request.distribution,
        "top_k": request.top_k,
        "token_budget": request.token_budget,
        "metadata": dict(request.metadata),
    }


def build_default_pipeline_registry(
    memory_manager: MemoryManager,
    *,
    llm: Any = None,
    image_generator: Callable[[str], str] | None = None,
    renderer: Any = None,
    artifact_dir: str = "artifacts/advisories",
    progress_sink: ProgressSink | None = None,
) -> dict[str, PipelineAdapter]:
    """Build adapters without exposing Cognee or CrewAI objects to the router."""

    def progress_callback(request: AdvisoryRequest) -> Callable[[str, str], None] | None:
        if progress_sink is None:
            return None
        run_id = str(request.metadata.get("run_id", ""))
        if not run_id:
            return None
        reporter = ProgressReporter(progress_sink, run_id=run_id, task_id=request.task_id)

        def report(step: str, status: str) -> None:
            reporter.emit(
                stage=f"agent.{step}",
                status="succeeded" if status == "succeeded" else "failed",
                progress=55 if status == "succeeded" else 100,
                message=f"Agent step {status}: {step}",
                pipeline=str(request.metadata.get("pipeline", "")) or None,
                error_code="AGENT_STEP_FAILED" if status != "succeeded" else None,
            )

        return report

    return {
        "advisory": PipelineAdapter(
            "advisory",
            lambda request: AdvisoryFlow(
                memory_manager,
                llm=llm,
                artifact_dir=artifact_dir,
                progress_callback=progress_callback(request),
            ).run(request),
        ),
        "linkedin_post": PipelineAdapter(
            "linkedin_post",
            lambda request: LinkedInPostFlow(
                memory_manager,
                llm=llm,
                image_generator=image_generator,
                progress_callback=progress_callback(request),
            ).run(request),
        ),
        "executive_summary": PipelineAdapter(
            "executive_summary",
            lambda request: ExecutiveSummaryFlow(
                memory_manager,
                llm=llm,
                progress_callback=progress_callback(request),
            ).run(request),
        ),
        "infographic": PipelineAdapter(
            "infographic",
            lambda request: InfographicFlow(
                memory_manager,
                llm=llm,
                renderer=renderer,
                progress_callback=progress_callback(request),
            ).run(request),
        ),
    }


def create_sqlite_checkpointer(path: str | None = None) -> Any:
    """Create a local durable checkpointer for development or single-instance use."""

    configured = path or os.getenv(
        "LANGGRAPH_CHECKPOINT_DB_PATH", "artifacts/.state/langgraph_checkpoints.db"
    )
    db_path = Path(configured).expanduser()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    from langgraph.checkpoint.sqlite import SqliteSaver

    connection = sqlite3.connect(str(db_path), check_same_thread=False)
    saver = SqliteSaver(connection)
    saver.setup()
    return saver


class PipelineOrchestrator:
    """Central graph with a stable invocation and progress-event interface."""

    def __init__(
        self,
        memory_manager: MemoryManager,
        *,
        registry: Mapping[str, PipelineAdapter] | None = None,
        progress_sink: ProgressSink | None = None,
        checkpointer: Any | None = None,
        intent_resolver: IntentResolver = default_intent_resolver,
        request_understander: RequestUnderstandingAgent | None = None,
        prompt_crafter: PromptCrafterAgent | None = None,
        llm: Any = None,
        image_generator: Callable[[str], str] | None = None,
        renderer: Any = None,
    ) -> None:
        self.memory_manager = memory_manager
        self.progress_sink = progress_sink or InMemoryProgressSink()
        self.intent_resolver = intent_resolver
        self.request_understander = request_understander or RequestUnderstandingAgent(intent_resolver)
        self.prompt_crafter = prompt_crafter or PromptCrafterAgent()
        self.registry = dict(registry or build_default_pipeline_registry(
            memory_manager,
            llm=llm,
            image_generator=image_generator,
            renderer=renderer,
            progress_sink=self.progress_sink,
        ))
        self._checkpointer = checkpointer or InMemorySaver()
        self.graph = self._build_graph()

    def _reporter(self, state: OrchestratorState) -> ProgressReporter:
        return ProgressReporter(
            self.progress_sink,
            run_id=state["run_id"],
            task_id=state["task_id"],
        )

    def _write_orchestrator_task_memory(
        self,
        state: OrchestratorState,
        step: str,
        status: str,
        content: str,
    ) -> None:
        """Best-effort task audit for the pre-pipeline stages."""

        try:
            request = _request_from_dict(state["request"])
            runtime = MemoryRuntime(
                manager=self.memory_manager,
                context=request.access_context,
                task_id=state["task_id"],
                case_id=request.case_id,
                run_id=state["run_id"],
                attempt=1,
                top_k=request.top_k,
                token_budget=request.token_budget,
                pipeline_name=state.get("pipeline", "orchestrator"),
            )
            TaskMemoryWriter(runtime).write(step, status, content[:2000])
        except Exception:
            # Audit persistence must not hide a routing or generation failure.
            return

    def _build_graph(self) -> Any:
        builder = StateGraph(OrchestratorState)
        builder.add_node("understand_request", self._understand_request)
        builder.add_node("recall_memory", self._recall_memory)
        builder.add_node("craft_prompt", self._craft_prompt)
        builder.add_node("run_pipeline", self._run_pipeline)
        builder.add_node("await_approval", self._await_approval)
        builder.add_node("resume_pipeline", self._resume_pipeline)
        builder.add_node("finish", self._finish)
        builder.add_node("fail", self._fail)
        builder.add_edge(START, "understand_request")
        builder.add_edge("understand_request", "recall_memory")
        builder.add_edge("recall_memory", "craft_prompt")
        builder.add_edge("craft_prompt", "run_pipeline")
        builder.add_conditional_edges(
            "run_pipeline",
            self._route_after_run,
            {"approval": "await_approval", "finish": "finish", "fail": "fail"},
        )
        builder.add_edge("await_approval", "resume_pipeline")
        builder.add_conditional_edges(
            "resume_pipeline",
            self._route_after_resume,
            {"finish": "finish", "fail": "fail"},
        )
        builder.add_edge("finish", END)
        builder.add_edge("fail", END)
        return builder.compile(checkpointer=self._checkpointer)

    def run(self, request: AdvisoryRequest, *, run_id: str | None = None) -> OrchestrationResult:
        resolved_run_id = run_id or f"run-{uuid4()}"
        ProgressReporter(self.progress_sink, run_id=resolved_run_id, task_id=request.task_id).emit(
            stage="queued",
            status="queued",
            progress=0,
            message="Run accepted and queued",
        )
        request_data = _request_to_dict(request)
        request_data["metadata"] = {**dict(request.metadata), "run_id": resolved_run_id}
        initial: OrchestratorState = {
            "request": request_data,
            "run_id": resolved_run_id,
            "task_id": request.task_id,
            "pipeline": "",
            "understanding": {},
            "memory_context": "",
            "memory_records": [],
            "prompt_plan": {},
            "response": None,
            "approval_decision": None,
            "error": None,
            "status": "queued",
            "stage": "queued",
        }
        return self._invoke(initial, resolved_run_id, request.task_id)

    def resume(
        self,
        run_id: str,
        task_id: str,
        decision: Mapping[str, Any],
    ) -> OrchestrationResult:
        """Resume a paused graph with an approval/revision decision."""

        result = self.graph.invoke(
            Command(resume=dict(decision)),
            config={"configurable": {"thread_id": run_id}},
        )
        return self._result_from_state(result, run_id, task_id)

    def _invoke(self, initial: OrchestratorState, run_id: str, task_id: str) -> OrchestrationResult:
        result = self.graph.invoke(
            initial,
            config={"configurable": {"thread_id": run_id}},
        )
        return self._result_from_state(result, run_id, task_id)

    def _result_from_state(
        self, result: Mapping[str, Any], run_id: str, task_id: str
    ) -> OrchestrationResult:
        raw_interrupts = result.get("__interrupt__")
        interrupt_payload: Mapping[str, Any] | None = None
        if raw_interrupts:
            first = raw_interrupts[0]
            value = getattr(first, "value", first)
            if isinstance(value, Mapping):
                interrupt_payload = dict(value)
        response = _response_from_dict(result.get("response"))
        status = "pending" if interrupt_payload else (
            response.status if response else ("failed" if result.get("error") else "pending")
        )
        return OrchestrationResult(
            status=status,  # type: ignore[arg-type]
            run_id=run_id,
            task_id=task_id,
            pipeline=result.get("pipeline"),
            response=response,
            interrupt=interrupt_payload,
            state=dict(result),
        )

    def _understand_request(self, state: OrchestratorState) -> dict[str, Any]:
        reporter = self._reporter(state)
        reporter.emit(stage="request_understanding", status="running", progress=10,
                       message="Understanding the requested operation")
        try:
            request = _request_from_dict(state["request"])
            understanding = self.request_understander.run(request)
            pipeline = understanding.requested_pipeline
            if pipeline not in self.registry:
                raise ValueError(f"Pipeline '{pipeline}' is not registered")
            request_data = dict(state["request"])
            request_data["metadata"] = {
                **dict(request.metadata),
                "pipeline": pipeline,
                "request_understanding": understanding.model_dump(mode="json"),
            }
            reporter.emit(stage="routing", status="succeeded", progress=20,
                          message=f"Routed request to {pipeline}", pipeline=pipeline)
            self._write_orchestrator_task_memory(
                {**state, "request": request_data, "pipeline": pipeline},
                "request_understanding",
                "succeeded",
                f"Selected pipeline={pipeline}; audience={understanding.audience}; "
                f"confidence={understanding.confidence:.2f}",
            )
            return {
                "request": request_data,
                "pipeline": pipeline,
                "understanding": understanding.model_dump(mode="json"),
                "stage": "routing",
                "status": "running",
            }
        except Exception as exc:
            self._write_orchestrator_task_memory(state, "request_understanding", "failed", str(exc))
            reporter.emit(stage="routing", status="failed", progress=100,
                          message="The request could not be routed", error_code="ROUTING_FAILED")
            return {"error": str(exc), "stage": "routing", "status": "failed"}

    def _recall_memory(self, state: OrchestratorState) -> dict[str, Any]:
        if state.get("error"):
            return {}
        reporter = self._reporter(state)
        reporter.emit(
            stage="memory_recall",
            status="running",
            progress=30,
            message="Recalling task-oriented permitted memory",
            pipeline=state.get("pipeline"),
        )
        try:
            request = _request_from_dict(state["request"])
            understanding = state.get("understanding", {})
            query = (
                f"Prepare {state['pipeline']} for the operation: {request.query}. "
                f"Intent: {understanding.get('intent', 'case-grounded generation')}"
            )
            recalled = self.memory_manager.recall(
                query=query,
                context=request.access_context,
                top_k=request.top_k,
                token_budget=request.token_budget,
                session_id=state["run_id"],
            )
            records = [
                {
                    "content": result.content,
                    "scope_type": result.scope_type.value if result.scope_type else None,
                    "scope_id": result.scope_id,
                    "source_reference": result.source_reference,
                    "score": result.score,
                }
                for result in recalled.results
            ]
            reporter.emit(
                stage="memory_recall",
                status="succeeded",
                progress=40,
                message=f"Recalled {len(records)} permitted memory records",
                pipeline=state.get("pipeline"),
            )
            self._write_orchestrator_task_memory(
                state,
                "memory_recall",
                "succeeded",
                f"Recalled {len(records)} permitted records for task-scoped generation.",
            )
            return {
                "memory_context": recalled.context.text,
                "memory_records": records,
                "stage": "memory_recall",
                "status": "running",
            }
        except Exception as exc:
            self._write_orchestrator_task_memory(state, "memory_recall", "failed", str(exc))
            reporter.emit(
                stage="memory_recall",
                status="failed",
                progress=100,
                message="Permitted memory could not be recalled",
                pipeline=state.get("pipeline"),
                error_code="MEMORY_RECALL_FAILED",
            )
            return {"error": str(exc), "stage": "memory_recall", "status": "failed"}

    def _craft_prompt(self, state: OrchestratorState) -> dict[str, Any]:
        if state.get("error"):
            return {}
        reporter = self._reporter(state)
        reporter.emit(
            stage="prompt_crafting",
            status="running",
            progress=45,
            message="Building the validated pipeline prompt plan",
            pipeline=state.get("pipeline"),
        )
        try:
            request = _request_from_dict(state["request"])
            from pipelines.orchestrator.understanding import RequestUnderstanding

            understanding = RequestUnderstanding.model_validate(state["understanding"])
            plan = self.prompt_crafter.run(
                request,
                understanding,
                str(state.get("memory_context", "")),
            )
            reporter.emit(
                stage="prompt_crafting",
                status="succeeded",
                progress=50,
                message="Prompt plan is ready for the generation pipeline",
                pipeline=state.get("pipeline"),
            )
            self._write_orchestrator_task_memory(
                state,
                "prompt_crafting",
                "succeeded",
                f"Built a validated prompt plan for {plan.pipeline}.",
            )
            return {
                "prompt_plan": plan.model_dump(mode="json"),
                "stage": "prompt_crafting",
                "status": "running",
            }
        except Exception as exc:
            self._write_orchestrator_task_memory(state, "prompt_crafting", "failed", str(exc))
            reporter.emit(
                stage="prompt_crafting",
                status="failed",
                progress=100,
                message="The pipeline prompt plan could not be built",
                pipeline=state.get("pipeline"),
                error_code="PROMPT_PLAN_FAILED",
            )
            return {"error": str(exc), "stage": "prompt_crafting", "status": "failed"}

    def _run_pipeline(self, state: OrchestratorState) -> dict[str, Any]:
        if state.get("error"):
            return {}
        pipeline = state["pipeline"]
        reporter = self._reporter(state)
        reporter.emit(stage="memory_and_generation", status="running", progress=55,
                      message="Running the selected pipeline with resolved memory", pipeline=pipeline)
        try:
            request = _request_from_dict(state["request"])
            request_data = _request_to_dict(request)
            request_data["metadata"] = {
                **dict(request.metadata),
                "run_id": state["run_id"],
                "pipeline": pipeline,
                "request_understanding": state.get("understanding", {}),
                "resolved_memory_context": state.get("memory_context", ""),
                "resolved_memory_records": state.get("memory_records", []),
                "prompt_plan": state.get("prompt_plan", {}),
            }
            response = self.registry[pipeline].run(_request_from_dict(request_data))
            payload = response_to_dict(response)
            if response.status == "pending":
                reporter.emit(stage="human_approval", status="waiting_for_approval", progress=75,
                              message="Waiting for an authorized approval decision", pipeline=pipeline,
                              requires_action=True)
            elif response.status == "succeeded":
                reporter.emit(stage="pipeline_result", status="succeeded", progress=90,
                              message="Pipeline produced a validated result", pipeline=pipeline)
            else:
                reporter.emit(stage="pipeline_result", status="failed", progress=100,
                              message="Pipeline failed", pipeline=pipeline, error_code="PIPELINE_FAILED")
            return {"response": payload, "stage": "pipeline_result", "status": response.status}
        except Exception as exc:
            reporter.emit(stage="pipeline_result", status="failed", progress=100,
                          message="Pipeline execution failed", pipeline=pipeline,
                          error_code="PIPELINE_EXCEPTION")
            return {"error": str(exc), "stage": "pipeline_result", "status": "failed"}

    @staticmethod
    def _route_after_run(state: OrchestratorState) -> str:
        if state.get("error"):
            return "fail"
        response = state.get("response") or {}
        if response.get("status") == "pending":
            return "approval"
        return "finish" if response.get("status") == "succeeded" else "fail"

    def _await_approval(self, state: OrchestratorState) -> dict[str, Any]:
        pipeline = state["pipeline"]
        adapter = self.registry[pipeline]
        if adapter.resume is None:
            return {"error": f"Pipeline '{pipeline}' returned pending without a resume adapter"}
        decision = interrupt({
            "type": "approval.required",
            "run_id": state["run_id"],
            "task_id": state["task_id"],
            "pipeline": pipeline,
            "message": "An authorized reviewer must approve, reject, or request revision.",
            "response": state.get("response"),
            "allowed_decisions": ["approved", "rejected", "needs_revision"],
        })
        return {"approval_decision": dict(decision) if isinstance(decision, Mapping) else {"decision": decision}}

    def _resume_pipeline(self, state: OrchestratorState) -> dict[str, Any]:
        pipeline = state["pipeline"]
        adapter = self.registry[pipeline]
        decision = state.get("approval_decision") or {}
        reporter = self._reporter(state)
        try:
            response = adapter.resume(_request_from_dict(state["request"]), decision)  # type: ignore[misc]
            if response.status == "succeeded":
                reporter.emit(stage="pipeline_result", status="succeeded", progress=90,
                              message="Approved pipeline result is ready", pipeline=pipeline)
            else:
                reporter.emit(stage="pipeline_result", status="failed", progress=100,
                              message="Approval decision did not release a result", pipeline=pipeline,
                              error_code="APPROVAL_NOT_RELEASED")
            return {"response": response_to_dict(response), "status": response.status}
        except Exception as exc:
            reporter.emit(stage="pipeline_result", status="failed", progress=100,
                          message="Pipeline could not resume after approval", pipeline=pipeline,
                          error_code="RESUME_FAILED")
            return {"error": str(exc), "status": "failed"}

    @staticmethod
    def _route_after_resume(state: OrchestratorState) -> str:
        return "finish" if (state.get("response") or {}).get("status") == "succeeded" else "fail"

    def _finish(self, state: OrchestratorState) -> dict[str, Any]:
        reporter = self._reporter(state)
        response = state.get("response") or {}
        reporter.emit(stage="completed", status="completed", progress=100,
                      message="The requested pipeline completed", pipeline=state.get("pipeline"))
        return {"status": response.get("status", "succeeded"), "stage": "completed"}

    def _fail(self, state: OrchestratorState) -> dict[str, Any]:
        reporter = self._reporter(state)
        reporter.emit(stage="failed", status="failed", progress=100,
                      message="The orchestration run failed", pipeline=state.get("pipeline"),
                      error_code="ORCHESTRATION_FAILED")
        return {"status": "failed", "stage": "failed"}


def _response_from_dict(data: Any) -> PipelineResponse | None:
    if not isinstance(data, Mapping):
        return None
    return PipelineResponse(
        status=data["status"],
        pipeline=str(data["pipeline"]),
        task_id=str(data["task_id"]),
        run_id=str(data["run_id"]),
        output=data.get("output"),
        artifact=data.get("artifact"),
        failure=data.get("failure"),
        attempts=int(data.get("attempts", 0)),
        metadata=data.get("metadata", {}),
    )
