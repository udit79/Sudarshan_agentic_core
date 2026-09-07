"""Reusable automatic text-generation Flow for frontend-owned delivery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping
from uuid import uuid4

from crewai import Agent, Crew, Process, Task
from crewai.flow.flow import Flow, listen, or_, router, start
from pydantic import BaseModel

from memory import KnowledgeUnit, MemoryType, ScopeType, Source, SourceType

from pipelines.common.contracts import AdvisoryRequest, PipelineResponse
from pipelines.common.flow_persistence import flow_persistence, typed_persist
from pipelines.common.memory_tools import MemoryManagerLike, MemoryRuntime, TaskMemoryWriter, memory_tools
from pipelines.common.task_state import TaskState


AgentFactory = Callable[[list[Any]], dict[str, Agent]]
TaskFactory = Callable[[dict[str, Agent], TaskMemoryWriter], dict[str, Task]]


@dataclass(frozen=True, slots=True)
class TextCrewRun:
    output: BaseModel | None = None
    quality: BaseModel | None = None
    error: str | None = None


@typed_persist(flow_persistence())
class TextTransformationFlow(Flow[TaskState]):
    """Run, validate, retry, and case-store an automatic text transformation.

    This Flow deliberately has no human-approval step. It returns a validated
    output to the application, where the frontend owns preview, editing, and
    publishing/upload. A quality critic and schema validation still run before
    the result is returned or written to Case memory.
    """

    pipeline_name = "text_transformation"
    agent_factory: AgentFactory | None = None
    task_factory: TaskFactory | None = None
    output_model: type[BaseModel] | None = None
    quality_model: type[BaseModel] | None = None

    def __init__(
        self,
        memory_manager: MemoryManagerLike,
        *,
        max_attempts: int = 2,
        llm: Any = None,
        progress_callback: Callable[[str, str], None] | None = None,
    ) -> None:
        super().__init__()
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if (
            self.agent_factory is None
            or self.task_factory is None
            or self.output_model is None
            or self.quality_model is None
        ):
            raise TypeError("text transformation subclasses must configure factories and output models")
        self.memory_manager = memory_manager
        self.max_attempts = max_attempts
        self.llm = llm
        self.progress_callback = progress_callback
        self._result: PipelineResponse | None = None

    def run(self, request: AdvisoryRequest) -> PipelineResponse:
        self._result = None
        self.state.pipeline_name = self.pipeline_name
        self.state.pipeline_options = {
            **self.pipeline_options(request),
            "request_understanding": request.metadata.get("request_understanding", {}),
            "prompt_plan": request.metadata.get("prompt_plan", {}),
            "collaboration_plan": request.metadata.get("collaboration_plan", {}),
            "upstream_pipeline_results": request.metadata.get("upstream_pipeline_results", {}),
            "resolved_memory_context": request.metadata.get("resolved_memory_context"),
            "resolved_memory_records": request.metadata.get("resolved_memory_records", []),
        }
        self.state.query = request.query
        self.state.user_id = request.user_id
        self.state.case_id = request.case_id
        self.state.task_id = request.task_id
        self.state.classification_level = request.classification_level
        self.state.distribution = request.distribution
        self.state.top_k = request.top_k
        self.state.token_budget = request.token_budget
        self.state.operation = request.operation
        self.state.parent_run_id = request.parent_run_id
        self.state.parent_artifact_id = request.parent_artifact_id
        self.state.revision_instruction = request.revision_instruction
        self.state.revision_scope = list(request.revision_scope)
        self.state.request_understanding = dict(request.metadata.get("request_understanding", {}))
        self.state.prompt_plan = dict(request.metadata.get("prompt_plan", {}))
        self.state.max_attempts = self.max_attempts
        requested_run_id = request.metadata.get("run_id")
        if isinstance(requested_run_id, str) and requested_run_id.strip():
            self.state.run_id = requested_run_id.strip()
        try:
            self.kickoff(inputs={
                **request.as_inputs(),
                "top_k": request.top_k,
                "token_budget": request.token_budget,
                "max_attempts": self.max_attempts,
            })
        except Exception as exc:
            self.state.failure = str(exc)
            self.state.status = "incomplete"
            self.state.record("flow", "failed", summary="Flow terminated unexpectedly", error=str(exc))
            self._write_task_failure("flow", str(exc))
            self._result = self._failure_response()
        if self._result:
            return self._result
        return PipelineResponse(
            status="failed",
            pipeline=self.pipeline_name,
            task_id=request.task_id,
            run_id=self.state.run_id,
            failure="flow completed without a terminal response",
            attempts=self.state.attempt,
        )

    def _request(self) -> AdvisoryRequest:
        return AdvisoryRequest(
            query=self.state.query,
            user_id=self.state.user_id,
            case_id=self.state.case_id,
            task_id=self.state.task_id,
            classification_level=self.state.classification_level,
            distribution=self.state.distribution,
            top_k=self.state.top_k,
            token_budget=self.state.token_budget,
            operation=self.state.operation,
            parent_run_id=self.state.parent_run_id,
            parent_artifact_id=self.state.parent_artifact_id,
            revision_instruction=self.state.revision_instruction,
            revision_scope=tuple(self.state.revision_scope),
        )

    def pipeline_options(self, request: AdvisoryRequest) -> dict[str, Any]:
        """Return non-secret, pipeline-specific options for task interpolation."""

        return {}

    def enrich_output(self, output: BaseModel) -> BaseModel:
        """Allow a concrete pipeline to attach an optional delivery asset."""

        return output

    def _runtime(self) -> MemoryRuntime:
        request = self._request()
        return MemoryRuntime(
            manager=self.memory_manager,
            context=request.access_context,
            task_id=self.state.task_id,
            case_id=self.state.case_id,
            run_id=self.state.run_id,
            attempt=max(1, self.state.attempt),
            top_k=self.state.top_k,
            token_budget=self.state.token_budget,
            pipeline_name=self.pipeline_name,
        )

    @start()
    def prepare_context(self) -> str:
        self.state.status = "running"
        self.state.run_id = str(self.state.run_id or getattr(self.state, "id", "") or uuid4())
        self.state.record("memory_recall", "started", summary="Resolving user, case, and task memory")
        precomputed_context = self.state.pipeline_options.get("resolved_memory_context")
        precomputed_records = self.state.pipeline_options.get("resolved_memory_records")
        if isinstance(precomputed_context, str):
            self.state.memory_context = precomputed_context
            if isinstance(precomputed_records, list):
                self.state.memory_records = [
                    dict(item) for item in precomputed_records if isinstance(item, Mapping)
                ]
            self.state.record(
                "memory_recall",
                "succeeded",
                summary=f"Reused {len(self.state.memory_records)} centrally resolved memory records",
            )
            return self.state.memory_context
        request = self._request()
        response = self.memory_manager.recall(
            query=f"Prepare {self.pipeline_name} for the operation: {request.query}",
            context=request.access_context,
            top_k=request.top_k,
            token_budget=request.token_budget,
            session_id=self.state.run_id,
        )
        self.state.memory_context = response.context.text
        self.state.memory_records = [
            {
                "content": result.content,
                "scope_type": result.scope_type.value if result.scope_type else None,
                "scope_id": result.scope_id,
                "source_reference": result.source_reference,
                "score": result.score,
            }
            for result in response.results
        ]
        self.state.record("memory_recall", "succeeded", summary=f"Resolved {len(response.results)} memory records")
        return self.state.memory_context

    def _run_crew(self) -> TextCrewRun:
        self.state.attempt += 1
        self.state.record(self.pipeline_name, "started", summary="Starting sequential text-generation crew")
        writer = TaskMemoryWriter(self._runtime(), on_event=self.progress_callback)
        try:
            agents = self.agent_factory(memory_tools(self._runtime()), llm=self.llm)  # type: ignore[misc]
            tasks = self.task_factory(agents, writer)  # type: ignore[misc]
            crew = Crew(
                agents=list(agents.values()),
                tasks=list(tasks.values()),
                process=Process.sequential,
                verbose=False,
            )
            with writer.activate():
                crew.kickoff(inputs={
                    "query": self.state.query,
                    "memory_context": self.state.memory_context,
                    "task_id": self.state.task_id,
                    "case_id": self.state.case_id,
                    "classification_level": self.state.classification_level,
                    "distribution": self.state.distribution,
                    "run_id": self.state.run_id,
                    "pipeline_options": self.state.pipeline_options,
                    "prompt_plan": self.state.prompt_plan,
                    "request_understanding": self.state.request_understanding,
                })
            output = self.output_model.model_validate(getattr(tasks["output"].output, "pydantic", None))  # type: ignore[union-attr]
            quality = self.quality_model.model_validate(getattr(tasks["quality"].output, "pydantic", None))  # type: ignore[union-attr]
            self.state.record(self.pipeline_name, "succeeded", summary="Text-generation crew completed")
            return TextCrewRun(output=output, quality=quality)
        except Exception as exc:
            self.state.failure = str(exc)
            self.state.record(self.pipeline_name, "failed", summary="Text-generation crew failed", error=str(exc))
            self._write_task_failure(self.pipeline_name, str(exc))
            return TextCrewRun(error=str(exc))

    def _write_task_failure(self, step: str, error: str) -> None:
        try:
            TaskMemoryWriter(self._runtime()).write(step, "failed", error)
        except Exception:
            return

    @listen(prepare_context)
    def run_crew(self, _: str) -> TextCrewRun:
        return self._run_crew()

    @start("retry")
    def retry_crew(self) -> TextCrewRun:
        self.state.record(self.pipeline_name, "retrying", summary="Retrying after quality validation feedback")
        return self._run_crew()

    @listen(or_(run_crew, retry_crew))
    def validate_crew(self, result: TextCrewRun) -> bool:
        if result.error:
            self.state.status = "incomplete"
            self.state.failure = result.error
            self.state.record("quality_gate", "rejected", summary="Crew execution failed", error=result.error)
            return False
        if result.output is None or result.quality is None:
            self.state.status = "incomplete"
            self.state.failure = "Crew returned no structured output or quality review"
            self.state.record("quality_gate", "rejected", summary=self.state.failure)
            return False
        self.state.output = result.output.model_dump(mode="json")
        self.state.quality_review = result.quality.model_dump(mode="json")
        if result.quality.model_dump().get("approved") is True:
            self.state.record("quality_gate", "succeeded", summary="Output approved for frontend delivery")
            return True
        issues = result.quality.model_dump().get("issues", []) + result.quality.model_dump().get("required_revisions", [])
        self.state.failure = "; ".join(issues) or "Quality critic rejected the output"
        self.state.record("quality_gate", "rejected", summary=self.state.failure)
        return False

    @router(validate_crew)
    def route_validation(self) -> str:
        if self.state.output and self.state.quality_review and self.state.quality_review.get("approved"):
            return "complete"
        if self.state.attempt < self.state.max_attempts:
            return "retry"
        return "failed"

    @listen("complete")
    def persist_output(self) -> PipelineResponse:
        try:
            output = self.output_model.model_validate(self.state.output)  # type: ignore[union-attr]
            output = self.enrich_output(output)
            self.state.output = output.model_dump(mode="json")
            unit = KnowledgeUnit(
                unit_id=f"{self.pipeline_name}-{self.state.run_id}",
                content=output.model_dump_json(),
                source=Source(
                    source_id=self.state.run_id,
                    source_type=SourceType.TEXT,
                    source_reference=f"pipeline://{self.pipeline_name}/{self.state.run_id}",
                ),
                metadata={
                    "pipeline": self.pipeline_name,
                    "classification_level": self.state.classification_level,
                    "delivery_owner": "frontend",
                    "human_approval_required": False,
                    "operation": self.state.operation,
                    "parent_run_id": self.state.parent_run_id,
                    "parent_artifact_id": self.state.parent_artifact_id,
                    "revision_scope": self.state.revision_scope,
                    "output": output.model_dump(mode="json"),
                },
                provenance={
                    "task_id": self.state.task_id,
                    "case_id": self.state.case_id,
                    "run_id": self.state.run_id,
                    "memory_policy": "validated_output_case_write_back",
                    "operation": self.state.operation,
                    "parent_run_id": self.state.parent_run_id,
                    "parent_artifact_id": self.state.parent_artifact_id,
                },
            )
            self.memory_manager.remember(
                unit,
                self._request().access_context,
                scope_type=ScopeType.CASE,
                memory_type=MemoryType.SUMMARY,
            )
            self.state.status = "succeeded"
            self._result = PipelineResponse(
                status="succeeded",
                pipeline=self.pipeline_name,
                task_id=self.state.task_id,
                run_id=self.state.run_id,
                output=output,
                artifact=self.state.artifact,
                attempts=self.state.attempt,
                metadata={
                    "memory_records": len(self.state.memory_records),
                    "delivery_owner": "frontend",
                    "human_approval_required": False,
                },
            )
            return self._result
        except Exception as exc:
            self.state.status = "incomplete"
            self.state.failure = str(exc)
            self.state.record("case_write_back", "failed", summary="Validated output was not persisted", error=str(exc))
            self._result = self._failure_response()
            return self._result

    @listen("failed")
    def persist_failure(self) -> PipelineResponse:
        self.state.status = "failed"
        self._result = self._failure_response()
        return self._result

    def _failure_response(self) -> PipelineResponse:
        return PipelineResponse(
            status="failed",
            pipeline=self.pipeline_name,
            task_id=self.state.task_id,
            run_id=self.state.run_id,
            failure=self.state.failure or "text transformation pipeline failed",
            attempts=self.state.attempt,
            metadata={"events": len(self.state.events), "memory_records": len(self.state.memory_records)},
        )
