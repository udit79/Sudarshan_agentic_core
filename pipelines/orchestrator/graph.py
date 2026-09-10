"""LangGraph router for all Sudarshan application-specific pipelines.

LangGraph owns the run lifecycle and routing. Registered pipeline adapters
continue to own CrewAI collaboration and call MemoryManager through their
existing controlled interfaces.
"""

from __future__ import annotations

import os
import inspect
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Event, Lock
from typing import Any, Callable, Mapping, TypedDict
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from memory import AccessContext
from pipelines.advisory.crew import AdvisoryFlow
from pipelines.common.contracts import AdvisoryRequest, PipelineResponse
from pipelines.common.memory_tools import MemoryManagerLike, MemoryRuntime, TaskMemoryWriter
from pipelines.executive_summary.crew import ExecutiveSummaryFlow
from pipelines.infographic.crew import InfographicFlow
from pipelines.linkedin.crew import LinkedInPostFlow
from pipelines.ppt.crew import PresentationFlow
from pipelines.orchestrator.progress import (
    InMemoryProgressSink,
    ProgressReporter,
    ProgressSink,
)
from pipelines.orchestrator.types import (
    OrchestrationResult,
    PipelineAdapter,
    PipelineRegistry,
    load_pipeline_plugins,
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
    requested_pipelines: list[str]
    understanding: dict[str, Any]
    clarification_required: bool
    clarification_questions: list[str]
    clarification_response: dict[str, Any] | None
    request_memory_context: str
    request_memory_records: list[dict[str, Any]]
    memory_context: str
    memory_records: list[dict[str, Any]]
    prompt_plan: dict[str, Any]
    prompt_plans: dict[str, Any]
    response: dict[str, Any] | None
    responses: dict[str, dict[str, Any]]
    approval_decision: dict[str, Any] | None
    error: str | None
    stage: str
    status: str


class RunCancelled(RuntimeError):
    """Raised at a safe orchestration boundary after frontend cancellation."""


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
        requested_pipelines=tuple(data.get("requested_pipelines", ())),
        operation=str(data.get("operation", "create")),
        parent_run_id=data.get("parent_run_id"),
        parent_artifact_id=data.get("parent_artifact_id"),
        revision_instruction=data.get("revision_instruction"),
        revision_scope=tuple(data.get("revision_scope", ())),
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
        "requested_pipelines": list(request.requested_pipelines),
        "operation": request.operation,
        "parent_run_id": request.parent_run_id,
        "parent_artifact_id": request.parent_artifact_id,
        "revision_instruction": request.revision_instruction,
        "revision_scope": list(request.revision_scope),
        "metadata": dict(request.metadata),
    }


def _clarification_text(response: Mapping[str, Any]) -> str:
    """Extract a bounded user answer from common frontend payload shapes."""

    for key in ("answer", "answers", "message", "query"):
        value = response.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (list, tuple)):
            items = [str(item).strip() for item in value if str(item).strip()]
            if items:
                return "\n".join(items)
    return ""


def _memory_records(recalled: Any) -> list[dict[str, Any]]:
    """Serialize recalled records without leaking backend-specific objects."""

    records: list[dict[str, Any]] = []
    for result in getattr(recalled, "results", ()):
        scope_type = getattr(result, "scope_type", None)
        records.append({
            "content": str(getattr(result, "content", "")),
            "scope_type": scope_type.value if scope_type else None,
            "scope_id": getattr(result, "scope_id", None),
            "source_reference": getattr(result, "source_reference", None),
            "score": getattr(result, "score", None),
        })
    return records


def build_default_pipeline_registry(
    memory_manager: MemoryManagerLike,
    *,
    llm: Any = None,
    image_generator: Callable[[str], str] | None = None,
    renderer: Any = None,
    artifact_dir: str = "artifacts/advisories",
    progress_sink: ProgressSink | None = None,
) -> dict[str, PipelineAdapter]:
    """Build adapters without exposing Cognee or CrewAI objects to the router."""

    from pipelines.video.pipeline import VideoPipeline
    video_backend = os.getenv("SUDARSHAN_VIDEO_BACKEND", "native").strip().lower()
    legacy_video_client = None
    if video_backend in {"moneyprinterturbo", "legacy"}:
        from integrations.providers.moneyprinterturbo import MoneyPrinterTurboClient

        legacy_video_client = MoneyPrinterTurboClient()

    def video_runner(request: AdvisoryRequest, *, cancel_event: Event | None = None) -> Any:
        return VideoPipeline(
            memory_manager,
            client=legacy_video_client,
        ).run(request, cancel_event=cancel_event)

    def progress_callback(request: AdvisoryRequest) -> Callable[[str, str], None] | None:
        if progress_sink is None:
            return None
        run_id = str(request.metadata.get("run_id", ""))
        if not run_id:
            return None
        progress_run_id = str(request.metadata.get("progress_run_id", run_id))
        reporter = ProgressReporter(progress_sink, run_id=progress_run_id, task_id=request.task_id)
        highest_agent_progress = 55

        def report(step: str, status: str) -> None:
            nonlocal highest_agent_progress
            # 55% used to be emitted for every successful CrewAI callback,
            # making a healthy run look frozen while the individual agents
            # were progressing. Keep the orchestration milestones (90/100)
            # unchanged, but expose monotonic agent-level progress.
            if status == "succeeded":
                if step.endswith("case_analyst") or step.endswith("intelligence_analyst"):
                    agent_progress = 60
                elif step.endswith("evidence_review") or step.endswith("provenance_reviewer"):
                    agent_progress = 66
                elif step.endswith("syntax_writer") or step.endswith("presentation_writer") or step.endswith("post_writer") or step.endswith("advisory_writer") or step.endswith("summary_writer"):
                    agent_progress = 74
                elif step.endswith("quality_critic"):
                    agent_progress = 82
                else:
                    agent_progress = 60
            else:
                agent_progress = 100
            highest_agent_progress = max(highest_agent_progress, agent_progress)
            reporter.emit(
                stage=f"agent.{step}",
                status="succeeded" if status == "succeeded" else "failed",
                progress=highest_agent_progress,
                message=f"Agent step {status}: {step}",
                pipeline=str(request.metadata.get("pipeline", "")) or None,
                error_code="AGENT_STEP_FAILED" if status != "succeeded" else None,
            )

        return report

    presentation_runner = lambda request: PresentationFlow(
        memory_manager,
        llm=llm,
        progress_callback=progress_callback(request),
    ).run(request)

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
        "presentation": PipelineAdapter(
            "presentation",
            presentation_runner,
        ),
        # ``ppt`` was the public route name in the first backend contract.
        # Keep it as a real adapter so older clients and natural-language
        # routing continue to reach the native presentation flow.
        "ppt": PipelineAdapter(
            "ppt",
            presentation_runner,
        ),
        "video": PipelineAdapter(
            "video",
            video_runner,
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
        memory_manager: MemoryManagerLike,
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
        if registry is None:
            discovered = PipelineRegistry()
            discovered.register_many(build_default_pipeline_registry(
                memory_manager,
                llm=llm,
                image_generator=image_generator,
                renderer=renderer,
                progress_sink=self.progress_sink,
            ))
            if os.getenv("SUDARSHAN_LOAD_PLUGINS", "false").lower() in {"1", "true", "yes"}:
                load_pipeline_plugins(discovered)
            self.registry = dict(discovered)
        else:
            # An explicit registry is an allow-list, including an intentional
            # empty registry used by constrained deployments and tests.
            self.registry = dict(registry)
        self._checkpointer = checkpointer or InMemorySaver()
        self._cancel_events: dict[str, Event] = {}
        self._active_runs: set[str] = set()
        self._run_lock = Lock()
        self.graph = self._build_graph()

    def _reporter(self, state: OrchestratorState) -> ProgressReporter:
        return ProgressReporter(
            self.progress_sink,
            run_id=state["run_id"],
            task_id=state["task_id"],
        )

    def _check_cancelled(self, run_id: str) -> None:
        with self._run_lock:
            event = self._cancel_events.get(run_id)
        if event is not None and event.is_set():
            raise RunCancelled(f"Run {run_id} was cancelled by the frontend")

    def _cancelled_result(
        self,
        state: Mapping[str, Any],
        run_id: str,
        task_id: str,
    ) -> OrchestrationResult:
        cancelled_state = {**dict(state), "status": "cancelled", "stage": "cancelled",
                           "error": "Run cancelled by the frontend"}
        self._write_orchestrator_task_memory(
            {**cancelled_state, "request": dict(state.get("request", {}))},
            "cancellation",
            "cancelled",
            "Run cancellation was observed at an orchestration safe point.",
        )
        ProgressReporter(self.progress_sink, run_id=run_id, task_id=task_id).emit(
            stage="cancellation",
            status="cancelled",
            progress=100,
            message="Run cancelled",
            pipeline=state.get("pipeline") or None,
            error_code="RUN_CANCELLED",
        )
        return OrchestrationResult(
            status="cancelled",
            run_id=run_id,
            task_id=task_id,
            pipeline=state.get("pipeline") or None,
            responses={},
            pipelines=tuple(state.get("requested_pipelines", ())),
            state=cancelled_state,
        )

    def cancel(self, run_id: str, task_id: str) -> dict[str, str]:
        """Request cooperative cancellation from a frontend/backend endpoint.

        Active runs stop at the next graph boundary. If a provider call is
        already running, its worker must return before LangGraph can observe
        cancellation. Paused runs are marked cancelled in the checkpointer.
        """

        with self._run_lock:
            active = run_id in self._active_runs
            event = self._cancel_events.setdefault(run_id, Event())
            event.set()
        if active:
            ProgressReporter(self.progress_sink, run_id=run_id, task_id=task_id).emit(
                stage="cancellation",
                status="running",
                progress=0,
                message="Cancellation requested",
            )
            return {"run_id": run_id, "task_id": task_id, "status": "requested"}

        config = {"configurable": {"thread_id": run_id}}
        try:
            snapshot = self.graph.get_state(config)
            values = dict(snapshot.values)
        except Exception:
            values = {}
        current_status = values.get("status")
        if not values:
            with self._run_lock:
                self._cancel_events.pop(run_id, None)
            return {"run_id": run_id, "task_id": task_id, "status": "not_found"}
        if current_status in {"completed", "succeeded", "failed", "cancelled"}:
            with self._run_lock:
                self._cancel_events.pop(run_id, None)
            return {"run_id": run_id, "task_id": task_id, "status": "already_terminal"}

        cancelled_state = {
            "status": "cancelled",
            "stage": "cancelled",
            "error": "Run cancelled by the frontend",
            "response": None,
        }
        self.graph.update_state(config, cancelled_state)
        self._write_orchestrator_task_memory(
            {**values, **cancelled_state, "request": dict(values.get("request", {}))},
            "cancellation",
            "cancelled",
            "Run cancelled while waiting for input or approval.",
        )
        ProgressReporter(self.progress_sink, run_id=run_id, task_id=task_id).emit(
            stage="cancellation",
            status="cancelled",
            progress=100,
            message="Run cancelled",
            pipeline=values.get("pipeline") or None,
            error_code="RUN_CANCELLED",
        )
        with self._run_lock:
            self._cancel_events.pop(run_id, None)
        return {"run_id": run_id, "task_id": task_id, "status": "cancelled"}

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
        builder.add_node("recall_request_context", self._recall_request_context)
        builder.add_node("await_clarification", self._await_clarification)
        builder.add_node("apply_clarification", self._apply_clarification)
        builder.add_node("recall_memory", self._recall_memory)
        builder.add_node("craft_prompt", self._craft_prompt)
        builder.add_node("run_pipeline", self._run_pipeline)
        builder.add_node("await_approval", self._await_approval)
        builder.add_node("resume_pipeline", self._resume_pipeline)
        builder.add_node("finish", self._finish)
        builder.add_node("fail", self._fail)
        builder.add_edge(START, "recall_request_context")
        builder.add_edge("recall_request_context", "understand_request")
        builder.add_conditional_edges(
            "understand_request",
            self._route_after_understanding,
            {"clarification": "await_clarification", "continue": "recall_memory", "fail": "fail"},
        )
        builder.add_edge("await_clarification", "apply_clarification")
        builder.add_edge("apply_clarification", "recall_request_context")
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

    def run(
        self,
        request: AdvisoryRequest,
        *,
        run_id: str | None = None,
        cancellation_event: Event | None = None,
    ) -> OrchestrationResult:
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
            "requested_pipelines": [],
            "understanding": {},
            "clarification_required": False,
            "clarification_questions": [],
            "clarification_response": None,
            "request_memory_context": "",
            "request_memory_records": [],
            "memory_context": "",
            "memory_records": [],
            "prompt_plan": {},
            "prompt_plans": {},
            "response": None,
            "responses": {},
            "approval_decision": None,
            "error": None,
            "status": "queued",
            "stage": "queued",
        }
        with self._run_lock:
            self._cancel_events[resolved_run_id] = cancellation_event or Event()
            self._active_runs.add(resolved_run_id)
        try:
            return self._invoke(initial, resolved_run_id, request.task_id)
        except RunCancelled:
            return self._cancelled_result(initial, resolved_run_id, request.task_id)
        finally:
            with self._run_lock:
                self._active_runs.discard(resolved_run_id)
                self._cancel_events.pop(resolved_run_id, None)

    def resume(
        self,
        run_id: str,
        task_id: str,
        decision: Mapping[str, Any],
    ) -> OrchestrationResult:
        """Resume a paused graph with an approval/revision decision."""

        snapshot = self.graph.get_state({"configurable": {"thread_id": run_id}})
        if snapshot.values.get("status") == "cancelled":
            return self._result_from_state(snapshot.values, run_id, task_id)
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
        response_data = result.get("responses") or {}
        responses = {
            str(name): parsed
            for name, value in response_data.items()
            if (parsed := _response_from_dict(value)) is not None
        }
        status = "cancelled" if result.get("status") == "cancelled" else (
            "pending" if interrupt_payload else (
                str(result.get("status")) if result.get("status") in {
                    "succeeded", "failed", "partial", "pending"
                } else (response.status if response else ("failed" if result.get("error") else "pending"))
            )
        )
        selected = result.get("requested_pipelines") or ([result.get("pipeline")] if result.get("pipeline") else [])
        return OrchestrationResult(
            status=status,  # type: ignore[arg-type]
            run_id=run_id,
            task_id=task_id,
            pipeline=result.get("pipeline"),
            response=response,
            responses=responses,
            pipelines=tuple(str(item) for item in selected if item),
            interrupt=interrupt_payload,
            state=dict(result),
        )

    def _understand_request(self, state: OrchestratorState) -> dict[str, Any]:
        self._check_cancelled(state["run_id"])
        reporter = self._reporter(state)
        reporter.emit(stage="request_understanding", status="running", progress=10,
                       message="Understanding the requested operation")
        try:
            request = _request_from_dict(state["request"])
            understanding = self.request_understander.run(
                request,
                memory_context=str(state.get("request_memory_context", "")),
            )
            pipelines = understanding.requested_pipelines or [understanding.requested_pipeline]
            pipeline = pipelines[0]
            request_data = dict(state["request"])
            request_data["metadata"] = {
                **dict(request.metadata),
                "request_understanding": understanding.model_dump(mode="json"),
                "request_memory_context": state.get("request_memory_context", ""),
                "request_memory_records": state.get("request_memory_records", []),
            }
            if not understanding.clarification_required:
                request_data["metadata"]["pipeline"] = pipeline
                request_data["metadata"]["pipelines"] = list(pipelines)
            if understanding.clarification_required:
                reporter.emit(
                    stage="request_understanding",
                    status="succeeded",
                    progress=15,
                    message="More information is required before selecting a pipeline",
                )
                self._write_orchestrator_task_memory(
                    {**state, "request": request_data},
                    "request_understanding",
                    "succeeded",
                    "Clarification required before pipeline routing.",
                )
                return {
                    "request": request_data,
                    "pipeline": "",
                    "requested_pipelines": [],
                    "understanding": understanding.model_dump(mode="json"),
                    "clarification_required": True,
                    "clarification_questions": understanding.clarification_questions,
                    "stage": "request_clarification",
                    "status": "waiting_for_input",
                }
            reporter.emit(stage="routing", status="succeeded", progress=20,
                          message=(f"Routed request to {pipeline}"
                                   if len(pipelines) == 1
                                   else f"Routed request to {len(pipelines)} pipelines"),
                          pipeline=pipeline)
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
                "requested_pipelines": pipelines,
                "understanding": understanding.model_dump(mode="json"),
                "stage": "routing",
                "status": "running",
            }
        except RunCancelled:
            raise
        except Exception as exc:
            self._write_orchestrator_task_memory(state, "request_understanding", "failed", str(exc))
            reporter.emit(stage="routing", status="failed", progress=100,
                          message="The request could not be routed", error_code="ROUTING_FAILED")
            return {"error": str(exc), "stage": "routing", "status": "failed"}

    @staticmethod
    def _route_after_understanding(state: OrchestratorState) -> str:
        if state.get("error"):
            return "fail"
        return "clarification" if state.get("clarification_required") else "continue"

    def _recall_request_context(self, state: OrchestratorState) -> dict[str, Any]:
        """Load bounded User/Case context before request understanding.

        The task scope is intentionally excluded here. Task memory is created
        as the run proceeds and is recalled only after a pipeline is selected.
        """

        self._check_cancelled(state["run_id"])
        reporter = self._reporter(state)
        reporter.emit(
            stage="request_memory_recall",
            status="running",
            progress=5,
            message="Loading bounded User and Case memory for request understanding",
        )
        try:
            request = _request_from_dict(state["request"])
            request_context = AccessContext(user_id=request.user_id, case_id=request.case_id)
            revision_hint = ""
            if request.operation == "revise":
                revision_hint = (
                    f" Revision target artifact={request.parent_artifact_id or 'by parent run'}, "
                    f"instruction={request.revision_instruction or ''}."
                )
            recalled = self.memory_manager.recall(
                query=(
                    "Understand the user's requested operation using relevant user preferences, "
                    f"terminology, and case summary. Request: {request.query}.{revision_hint}"
                ),
                context=request_context,
                top_k=min(request.top_k, 8),
                token_budget=min(request.token_budget, 1200),
                session_id=state["run_id"],
            )
            records = _memory_records(recalled)
            context_text = str(recalled.context.text or "")
            reporter.emit(
                stage="request_memory_recall",
                status="succeeded",
                progress=8,
                message=f"Loaded {len(records)} bounded User/Case memory records",
            )
            self._write_orchestrator_task_memory(
                state,
                "request_memory_recall",
                "succeeded",
                f"Loaded {len(records)} bounded User/Case records before request understanding.",
            )
            return {
                "request_memory_context": context_text,
                "request_memory_records": records,
                "stage": "request_memory_recall",
                "status": "running",
            }
        except RunCancelled:
            raise
        except Exception as exc:
            self._write_orchestrator_task_memory(state, "request_memory_recall", "failed", str(exc))
            reporter.emit(
                stage="request_memory_recall",
                status="failed",
                progress=100,
                message="User/Case memory could not be loaded for request understanding",
                error_code="REQUEST_MEMORY_RECALL_FAILED",
            )
            return {"error": str(exc), "stage": "request_memory_recall", "status": "failed"}

    def _await_clarification(self, state: OrchestratorState) -> dict[str, Any]:
        self._check_cancelled(state["run_id"])
        reporter = self._reporter(state)
        reporter.emit(
            stage="request_clarification",
            status="waiting_for_input",
            progress=15,
            message="Waiting for the user to clarify the requested operation",
            requires_action=True,
        )
        answer = interrupt({
            "type": "clarification.required",
            "run_id": state["run_id"],
            "task_id": state["task_id"],
            "questions": state.get("clarification_questions", []),
            "message": "Please provide the missing information before generation starts.",
        })
        return {
            "clarification_response": dict(answer)
            if isinstance(answer, Mapping)
            else {"answer": str(answer)},
        }

    def _apply_clarification(self, state: OrchestratorState) -> dict[str, Any]:
        self._check_cancelled(state["run_id"])
        response = state.get("clarification_response") or {}
        answer = _clarification_text(response)
        if not answer:
            return {
                "error": "Clarification response must include a non-empty answer",
                "stage": "request_clarification",
                "status": "failed",
            }
        request = _request_from_dict(state["request"])
        metadata = {
            **dict(request.metadata),
            "clarification_response": response,
        }
        for key in ("requires_clarification", "missing_information", "clarification_questions"):
            metadata.pop(key, None)
        selected_pipeline = response.get("pipeline")
        if isinstance(selected_pipeline, str) and selected_pipeline.strip():
            metadata["pipeline"] = selected_pipeline.strip().lower()
        request_data = _request_to_dict(
            AdvisoryRequest(
                query=f"{request.query}\nUser clarification: {answer[:4000]}",
                user_id=request.user_id,
                case_id=request.case_id,
                task_id=request.task_id,
                classification_level=request.classification_level,
                distribution=request.distribution,
                top_k=request.top_k,
                token_budget=request.token_budget,
                requested_pipelines=tuple(
                    [str(response["pipeline"]).strip().lower()]
                    if isinstance(response.get("pipeline"), str) and response.get("pipeline")
                    else request.requested_pipelines
                ),
                operation=request.operation,
                parent_run_id=request.parent_run_id,
                parent_artifact_id=request.parent_artifact_id,
                revision_instruction=request.revision_instruction,
                revision_scope=request.revision_scope,
                metadata=metadata,
            )
        )
        self._write_orchestrator_task_memory(
            {**state, "request": request_data},
            "request_clarification",
            "succeeded",
            "User clarification received; request understanding will run again.",
        )
        return {
            "request": request_data,
            "clarification_required": False,
            "clarification_questions": [],
            "clarification_response": response,
            "pipeline": "",
            "requested_pipelines": [],
            "understanding": {},
            "error": None,
            "stage": "request_clarification",
            "status": "running",
        }

    def _recall_memory(self, state: OrchestratorState) -> dict[str, Any]:
        if state.get("error"):
            return {}
        self._check_cancelled(state["run_id"])
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
            if request.operation == "revise":
                query += (
                    f" Retrieve the parent artifact {request.parent_artifact_id or request.parent_run_id} "
                    f"and apply this revision instruction: {request.revision_instruction}."
                )
            recalled = self.memory_manager.recall(
                query=query,
                context=request.access_context,
                top_k=request.top_k,
                token_budget=request.token_budget,
                session_id=state["run_id"],
            )
            records = _memory_records(recalled)
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
        except RunCancelled:
            raise
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
        self._check_cancelled(state["run_id"])
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
            pipelines = state.get("requested_pipelines") or [state.get("pipeline", "")]
            plans: dict[str, dict[str, Any]] = {}
            for selected in pipelines:
                selected_understanding = understanding.model_copy(update={
                    "requested_pipeline": selected,
                    "requested_pipelines": pipelines,
                    "image_requested": (
                        understanding.image_requested if selected == "linkedin_post" else None
                    ),
                })
                plan = self.prompt_crafter.run(
                    request,
                    selected_understanding,
                    str(state.get("memory_context", "")),
                )
                plans[selected] = plan.model_dump(mode="json")
            primary_plan = plans[pipelines[0]]
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
                f"Built validated prompt plans for {', '.join(pipelines)}.",
            )
            return {
                "prompt_plan": primary_plan,
                "prompt_plans": plans,
                "stage": "prompt_crafting",
                "status": "running",
            }
        except RunCancelled:
            raise
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
        self._check_cancelled(state["run_id"])
        pipeline = state["pipeline"]
        reporter = self._reporter(state)
        pipelines = state.get("requested_pipelines") or [pipeline]
        reporter.emit(stage="memory_and_generation", status="running", progress=55,
                      message=("Running the selected pipeline with resolved memory"
                               if len(pipelines) == 1
                               else f"Running {len(pipelines)} pipelines in parallel with resolved memory"),
                      pipeline=pipeline)
        try:
            request = _request_from_dict(state["request"])
            if len(pipelines) == 1:
                if pipeline not in self.registry:
                    raise ValueError(f"Pipeline '{pipeline}' is not registered")
                payload = self._run_one_pipeline(state, request, pipeline, state.get("prompt_plans", {}).get(pipeline, state.get("prompt_plan", {})))
                response = _response_from_dict(payload)
                if response is None:
                    raise ValueError(f"Pipeline '{pipeline}' returned an invalid response")
                if response.status == "pending":
                    response_metadata = dict(payload.get("metadata") or {})
                    response_metadata.setdefault(
                        "human_approval_required",
                        self.registry[pipeline].resume is not None,
                    )
                    payload["metadata"] = response_metadata
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
                return {"response": payload, "responses": {pipeline: payload}, "stage": "pipeline_result", "status": response.status}

            payloads: dict[str, dict[str, Any]] = {}
            with ThreadPoolExecutor(max_workers=min(len(pipelines), 8), thread_name_prefix="sudarshan-pipeline") as executor:
                futures = {
                    executor.submit(
                        self._run_one_pipeline,
                        state,
                        request,
                        selected,
                        state.get("prompt_plans", {}).get(selected, {}),
                    ): selected
                    for selected in pipelines
                }
                for future in as_completed(futures):
                    selected = futures[future]
                    try:
                        payloads[selected] = future.result()
                    except RunCancelled:
                        raise
                    except Exception as exc:
                        payloads[selected] = response_to_dict(PipelineResponse(
                            status="failed",
                            pipeline=selected,
                            task_id=f"{state['task_id']}-{selected}",
                            run_id=f"{state['run_id']}-{selected}",
                            failure=str(exc),
                            metadata={
                                "parent_orchestration_run_id": state["run_id"],
                                "parent_task_id": state["task_id"],
                            },
                        )) or {}
                    child = _response_from_dict(payloads[selected])
                    if child is not None:
                        reporter.emit(
                            stage="pipeline_result",
                            status="succeeded" if child.status == "succeeded" else "failed",
                            progress=90 if child.status == "succeeded" else 100,
                            message=f"{selected} pipeline completed with status {child.status}",
                            pipeline=selected,
                            error_code="PIPELINE_FAILED" if child.status == "failed" else None,
                        )
            self._check_cancelled(state["run_id"])
            aggregate = _aggregate_pipeline_status(payloads)
            primary_name = next((name for name in pipelines if payloads.get(name, {}).get("status") == "succeeded"), pipelines[0])
            return {
                "response": payloads.get(primary_name),
                "responses": payloads,
                "stage": "pipeline_result",
                "status": aggregate,
            }
        except RunCancelled:
            raise
        except Exception as exc:
            reporter.emit(stage="pipeline_result", status="failed", progress=100,
                          message="Pipeline execution failed", pipeline=pipeline,
                          error_code="PIPELINE_EXCEPTION")
            return {"error": str(exc), "stage": "pipeline_result", "status": "failed"}

    def _run_one_pipeline(
        self,
        state: OrchestratorState,
        request: AdvisoryRequest,
        pipeline: str,
        prompt_plan: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Run one isolated child execution inside a fan-out parent run."""

        self._check_cancelled(state["run_id"])
        child_task_id = f"{state['task_id']}-{pipeline}"
        child_run_id = state["run_id"] if len(state.get("requested_pipelines", ())) <= 1 else f"{state['run_id']}-{pipeline}"
        if pipeline not in self.registry:
            return response_to_dict(PipelineResponse(
                status="failed",
                pipeline=pipeline,
                task_id=child_task_id,
                run_id=child_run_id,
                failure=f"Pipeline '{pipeline}' is not registered",
                metadata={"parent_run_id": state["run_id"], "parent_task_id": state["task_id"]},
            )) or {}
        request_data = _request_to_dict(request)
        request_data["task_id"] = child_task_id
        request_data["metadata"] = {
            **dict(request.metadata),
            "run_id": child_run_id,
            "progress_run_id": state["run_id"],
            "parent_orchestration_run_id": state["run_id"],
            "parent_task_id": state["task_id"],
            "child_run_id": child_run_id,
            "child_task_id": child_task_id,
            "pipeline": pipeline,
            "request_understanding": state.get("understanding", {}),
            "resolved_memory_context": state.get("memory_context", ""),
            "resolved_memory_records": state.get("memory_records", []),
            "prompt_plan": dict(prompt_plan),
        }
        runner = self.registry[pipeline].run
        with self._run_lock:
            cancellation_event = self._cancel_events.get(state["run_id"])
        supports_event = False
        try:
            parameters = inspect.signature(runner).parameters
            supports_event = "cancel_event" in parameters or any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in parameters.values()
            )
        except (TypeError, ValueError):
            pass
        if supports_event and cancellation_event is not None:
            response = runner(
                _request_from_dict(request_data),
                cancel_event=cancellation_event,
            )
        else:
            response = runner(_request_from_dict(request_data))
        self._check_cancelled(state["run_id"])
        payload = response_to_dict(response) or {}
        response_metadata = dict(payload.get("metadata") or {})
        response_metadata.update({
            "operation": request.operation,
            "parent_run_id": request.parent_run_id,
            "parent_artifact_id": request.parent_artifact_id,
            "revision_scope": list(request.revision_scope),
            "parent_orchestration_run_id": state["run_id"],
            "parent_task_id": state["task_id"],
            "child_run_id": child_run_id,
            "child_task_id": child_task_id,
        })
        payload["metadata"] = response_metadata
        return payload

    @staticmethod
    def _route_after_run(state: OrchestratorState) -> str:
        if state.get("error"):
            return "fail"
        response = state.get("response") or {}
        if response.get("status") == "pending":
            metadata = response.get("metadata") or {}
            if metadata.get("human_approval_required") is True:
                return "approval"
            return "finish"
        return "finish" if response.get("status") == "succeeded" else "fail"

    def _await_approval(self, state: OrchestratorState) -> dict[str, Any]:
        self._check_cancelled(state["run_id"])
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
        self._check_cancelled(state["run_id"])
        pipeline = state["pipeline"]
        adapter = self.registry[pipeline]
        decision = state.get("approval_decision") or {}
        reporter = self._reporter(state)
        try:
            response = adapter.resume(_request_from_dict(state["request"]), decision)  # type: ignore[misc]
            payload = response_to_dict(response)
            updated_responses = dict(state.get("responses") or {})
            updated_responses[pipeline] = payload or {}
            if response.status == "succeeded":
                reporter.emit(stage="pipeline_result", status="succeeded", progress=90,
                              message="Approved pipeline result is ready", pipeline=pipeline)
            else:
                reporter.emit(stage="pipeline_result", status="failed", progress=100,
                              message="Approval decision did not release a result", pipeline=pipeline,
                              error_code="APPROVAL_NOT_RELEASED")
            return {
                "response": payload,
                "responses": updated_responses,
                "status": response.status,
            }
        except RunCancelled:
            raise
        except Exception as exc:
            reporter.emit(stage="pipeline_result", status="failed", progress=100,
                          message="Pipeline could not resume after approval", pipeline=pipeline,
                          error_code="RESUME_FAILED")
            return {"error": str(exc), "status": "failed"}

    @staticmethod
    def _route_after_resume(state: OrchestratorState) -> str:
        return "finish" if (state.get("response") or {}).get("status") == "succeeded" else "fail"

    def _finish(self, state: OrchestratorState) -> dict[str, Any]:
        self._check_cancelled(state["run_id"])
        reporter = self._reporter(state)
        response = state.get("response") or {}
        responses = state.get("responses") or {}
        status = _aggregate_pipeline_status(responses) if responses else response.get("status", "succeeded")
        reporter.emit(stage="completed", status="completed", progress=100,
                      message=("The requested pipeline completed"
                               if len(responses) <= 1
                               else f"Completed {len(responses)} requested pipelines"),
                      pipeline=state.get("pipeline"))
        return {"status": status, "stage": "completed"}

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


def _aggregate_pipeline_status(payloads: Mapping[str, Any]) -> str:
    """Return the parent status while retaining every child result."""

    statuses = [str(value.get("status")) for value in payloads.values() if isinstance(value, Mapping)]
    if not statuses:
        return "failed"
    if all(status == "succeeded" for status in statuses):
        return "succeeded"
    if all(status == "failed" for status in statuses):
        return "failed"
    if any(status == "pending" for status in statuses):
        return "pending"
    return "partial"
