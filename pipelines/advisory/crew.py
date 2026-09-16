"""CrewAI Crew plus deterministic Flow for NTRO advisory generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping
from uuid import uuid4

from crewai import Crew, Process
from crewai.flow.flow import Flow, listen, or_, router, start
from crewai.flow.human_feedback import HumanFeedbackResult, human_feedback

from memory import KnowledgeUnit, MemoryType, ScopeType, Source, SourceType

from pipelines.advisory.agents import build_agents
from pipelines.advisory.artifact import AdvisoryArtifactWriter
from pipelines.advisory.schemas import AdvisoryOutput, QualityReview
from pipelines.advisory.tasks import build_tasks
from pipelines.common.contracts import AdvisoryRequest, PipelineResponse
from pipelines.common.flow_persistence import flow_persistence, typed_persist
from pipelines.common.memory_tools import MemoryManagerLike, MemoryRuntime, TaskMemoryWriter, memory_tools
from pipelines.common.task_state import TaskState


@dataclass(frozen=True, slots=True)
class CrewRun:
    advisory: AdvisoryOutput | None = None
    quality: QualityReview | None = None
    error: str | None = None


class AdvisoryCrew:
    """Build one isolated CrewAI crew for one Flow attempt."""

    def __init__(
        self,
        memory_manager: MemoryManagerLike,
        state: TaskState,
        *,
        llm: Any = None,
        progress_callback: Callable[[str, str], None] | None = None,
    ) -> None:
        self.state = state
        runtime = MemoryRuntime(
            manager=memory_manager,
            context=AdvisoryRequest(
                query=state.query,
                user_id=state.user_id,
                case_id=state.case_id,
                task_id=state.task_id,
                classification_level=state.classification_level,
                distribution=state.distribution,
            ).access_context,
            task_id=state.task_id,
            case_id=state.case_id,
            run_id=state.run_id,
            attempt=state.attempt,
            top_k=state.top_k,
            token_budget=state.token_budget,
            pipeline_name="ntro_advisory",
        )
        self.writer = TaskMemoryWriter(runtime, on_event=progress_callback)
        self.agents = build_agents(memory_tools(runtime), llm=llm)
        self.tasks = build_tasks(self.agents, self.writer)

    def kickoff(self, inputs: dict[str, Any]) -> CrewRun:
        crew = Crew(
            agents=list(self.agents.values()),
            tasks=list(self.tasks.values()),
            process=Process.sequential,
            verbose=False,
        )
        with self.writer.activate():
            crew.kickoff(inputs=inputs)

        advisory_output = getattr(self.tasks["advisory"].output, "pydantic", None)
        quality_output = getattr(self.tasks["quality"].output, "pydantic", None)
        advisory = AdvisoryOutput.model_validate(advisory_output).model_copy(
            update={"advisory_id": f"advisory-{self.state.run_id}"}
        )
        quality = QualityReview.model_validate(quality_output)
        return CrewRun(advisory=advisory, quality=quality)


@typed_persist(flow_persistence())
class AdvisoryFlow(Flow[TaskState]):
    """Deterministic memory -> crew -> validation -> write-back workflow."""

    pipeline_name = "ntro_advisory"

    def __init__(self, memory_manager: MemoryManagerLike, *, max_attempts: int = 2,
                 llm: Any = None, artifact_dir: str = "artifacts/advisories",
                 progress_callback: Callable[[str, str], None] | None = None) -> None:
        super().__init__()
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self.memory_manager = memory_manager
        self.max_attempts = max_attempts
        self.llm = llm
        self.progress_callback = progress_callback
        self.artifact_writer = AdvisoryArtifactWriter(artifact_dir)

    def run(self, request: AdvisoryRequest) -> PipelineResponse:
        """Execute the Flow using a validated application request."""

        self._result: PipelineResponse | None = None
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
        self.state.pipeline_options = {
            "request_understanding": request.metadata.get("request_understanding", {}),
            "prompt_plan": request.metadata.get("prompt_plan", {}),
            "resolved_memory_context": request.metadata.get("resolved_memory_context"),
            "resolved_memory_records": request.metadata.get("resolved_memory_records", []),
        }
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
        if self.state.approval_status == "pending":
            advisory = AdvisoryOutput.model_validate(self.state.advisory) if self.state.advisory else None
            return PipelineResponse(
                status="pending", pipeline=self.pipeline_name, task_id=request.task_id,
                run_id=self.state.run_id, output=advisory,
                attempts=self.state.attempt,
                metadata={"approval_status": "pending", "resume_state_id": self.state.run_id},
            )
        return PipelineResponse(
            status="failed", pipeline=self.pipeline_name, task_id=request.task_id,
            run_id=self.state.run_id, failure="flow completed without a terminal response",
            attempts=self.state.attempt,
        )

    @start()
    def prepare_context(self) -> str:
        self.state.status = "running"
        self.state.run_id = str(self.state.run_id or getattr(self.state, "id", "") or uuid4())
        self.state.max_attempts = self.state.max_attempts or self.max_attempts
        self.state.record("memory_recall", "started", summary="Resolving user, case, and task memory")
        precomputed_context = self.state.pipeline_options.get("resolved_memory_context")
        precomputed_records = self.state.pipeline_options.get("resolved_memory_records", [])
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
        request = AdvisoryRequest(
            query=self.state.query,
            user_id=self.state.user_id,
            case_id=self.state.case_id,
            task_id=self.state.task_id,
            classification_level=self.state.classification_level,
            distribution=self.state.distribution,
            operation=self.state.operation,
            parent_run_id=self.state.parent_run_id,
            parent_artifact_id=self.state.parent_artifact_id,
            revision_instruction=self.state.revision_instruction,
            revision_scope=tuple(self.state.revision_scope),
        )
        response = self.memory_manager.recall(
            query=f"Prepare NTRO case advisory for the operation: {request.query}",
            context=request.access_context,
            top_k=self.state.top_k,
            token_budget=self.state.token_budget,
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

    def _run_crew(self) -> CrewRun:
        self.state.attempt += 1
        self.state.record("advisory_crew", "started", summary="Starting sequential specialist crew")
        try:
            runner = AdvisoryCrew(
                self.memory_manager,
                self.state,
                llm=self.llm,
                progress_callback=self.progress_callback,
            )
            result = runner.kickoff({
                "query": self.state.query,
                "memory_context": self.state.memory_context,
                "task_id": self.state.task_id,
                "case_id": self.state.case_id,
                "classification_level": self.state.classification_level,
                "distribution": self.state.distribution,
                "run_id": self.state.run_id,
                "operation": self.state.operation,
                "parent_artifact_id": self.state.parent_artifact_id,
                "revision_scope": self.state.revision_scope,
                "prompt_plan": self.state.prompt_plan,
                "request_understanding": self.state.request_understanding,
            })
            self.state.record("advisory_crew", "succeeded", summary="Specialist crew completed")
            return result
        except Exception as exc:
            self.state.failure = str(exc)
            self.state.record("advisory_crew", "failed", summary="Specialist crew failed", error=str(exc))
            self._write_task_failure("advisory_crew", str(exc))
            return CrewRun(error=str(exc))

    def _write_task_failure(self, step: str, error: str) -> None:
        """Best-effort failure visibility; preserve the original failure."""

        try:
            runtime = MemoryRuntime(
                manager=self.memory_manager,
                context=AdvisoryRequest(
                    query=self.state.query or "advisory flow",
                    user_id=self.state.user_id,
                    case_id=self.state.case_id,
                    task_id=self.state.task_id,
                    classification_level=self.state.classification_level,
                    distribution=self.state.distribution,
                    operation=self.state.operation,
                    parent_run_id=self.state.parent_run_id,
                    parent_artifact_id=self.state.parent_artifact_id,
                    revision_instruction=self.state.revision_instruction,
                    revision_scope=tuple(self.state.revision_scope),
                ).access_context,
                task_id=self.state.task_id,
                case_id=self.state.case_id,
                run_id=self.state.run_id or str(uuid4()),
                attempt=max(1, self.state.attempt),
                top_k=self.state.top_k,
                token_budget=self.state.token_budget,
            )
            TaskMemoryWriter(runtime).write(step, "failed", error)
        except Exception:
            # A memory outage must not hide the original pipeline failure.
            return

    @listen(prepare_context)
    def run_crew(self, _: str) -> CrewRun:
        return self._run_crew()

    @start("retry")
    def retry_crew(self) -> CrewRun:
        self.state.record("advisory_crew", "retrying", summary="Retrying after validation feedback")
        return self._run_crew()

    @listen(or_(run_crew, retry_crew))
    def validate_crew(self, result: CrewRun) -> bool:
        if result.error:
            self.state.failure = result.error
            self.state.status = "incomplete"
            self.state.record("quality_gate", "rejected", summary="Crew execution failed", error=result.error)
            return False
        if result.advisory is None or result.quality is None:
            self.state.failure = "Crew returned no structured advisory or quality review"
            self.state.status = "incomplete"
            self.state.record("quality_gate", "rejected", summary=self.state.failure)
            return False

        self.state.advisory = result.advisory.model_dump(mode="json")
        self.state.quality_review = result.quality.model_dump(mode="json")
        if result.quality.approved:
            self.state.record("quality_gate", "succeeded", summary="Advisory approved for case write-back")
            return True

        issue_text = "; ".join(result.quality.issues + result.quality.required_revisions)
        self.state.failure = issue_text or "Quality critic rejected the advisory"
        self.state.record("quality_gate", "rejected", summary=self.state.failure)
        return False

    @router(validate_crew)
    def route_validation(self) -> str:
        if self.state.advisory and self.state.quality_review and self.state.quality_review.get("approved"):
            return "human_review"
        if self.state.attempt < self.state.max_attempts:
            return "retry"
        return "failed"

    @listen("human_review")
    @human_feedback(
        message=(
            "Review the proposed NTRO case advisory. Approve only if the facts, evidence, "
            "recommendations, classification, and formal presentation are acceptable for release. "
            "Reply approved, rejected, or needs_revision with reviewer comments."
        ),
        emit=["approved", "rejected", "needs_revision"],
        default_outcome=None,
        metadata={"pipeline": "ntro_advisory", "approval_gate": "human_release"},
    )
    def request_human_approval(self, _: str) -> str:
        self.state.approval_status = "pending"
        self.state.record("human_approval", "started", summary="Waiting for authorized human approval")
        return AdvisoryOutput.model_validate(self.state.advisory).model_dump_json(indent=2)

    @listen("approved")
    def persist_case_output(self, result: HumanFeedbackResult) -> PipelineResponse:
        try:
            advisory = AdvisoryOutput.model_validate(self.state.advisory)
            approved_by = None
            feedback = getattr(result, "feedback", "")
            metadata = getattr(result, "metadata", {}) or {}
            if isinstance(metadata, dict):
                approved_by = metadata.get("reviewer_id") or metadata.get("approved_by")
            self.state.approval_status = "approved"
            self.state.approval_feedback = feedback
            self.state.record("human_approval", "succeeded", summary="Advisory approved for artifact handoff")
            artifact = self.artifact_writer.write(advisory, approved_by=approved_by)
            self.state.artifact = artifact.model_dump(mode="json")
            from pipelines.common.release_gate import can_release_to_case_memory

            releasable, reason = can_release_to_case_memory(
                pipeline=self.pipeline_name,
                output=advisory,
                quality_approved=bool(self.state.quality_review and self.state.quality_review.get("approved")),
                status="succeeded",
                artifact=artifact,
                human_approval_required=True,
                human_approved=(self.state.approval_status == "approved"),
            )
            if releasable:
                unit = KnowledgeUnit(
                    unit_id=advisory.advisory_id,
                    content=artifact.content,
                    source=Source(
                        source_id=self.state.run_id,
                        source_type=SourceType.TEXT,
                        source_reference=f"pipeline://advisory/{self.state.run_id}",
                    ),
                    metadata={
                        "pipeline": self.pipeline_name,
                        "classification_level": advisory.classification_level,
                        "artifact_path": artifact.path,
                        "operation": self.state.operation,
                        "parent_run_id": self.state.parent_run_id,
                        "parent_artifact_id": self.state.parent_artifact_id,
                        "revision_scope": self.state.revision_scope,
                        "advisory": advisory.model_dump(mode="json"),
                    },
                    provenance={
                        "task_id": self.state.task_id,
                        "case_id": self.state.case_id,
                        "run_id": self.state.run_id,
                        "memory_policy": "case_output_after_quality_gate",
                        "human_approval": "approved",
                        "approval_feedback": feedback,
                        "operation": self.state.operation,
                        "parent_run_id": self.state.parent_run_id,
                        "parent_artifact_id": self.state.parent_artifact_id,
                    },
                )
                self.memory_manager.remember(
                    unit,
                    AdvisoryRequest(
                        query=self.state.query,
                        user_id=self.state.user_id,
                        case_id=self.state.case_id,
                        task_id=self.state.task_id,
                        classification_level=self.state.classification_level,
                        distribution=self.state.distribution,
                        operation=self.state.operation,
                        parent_run_id=self.state.parent_run_id,
                        parent_artifact_id=self.state.parent_artifact_id,
                        revision_instruction=self.state.revision_instruction,
                        revision_scope=tuple(self.state.revision_scope),
                    ).access_context,
                    scope_type=ScopeType.CASE,
                    memory_type=MemoryType.SUMMARY,
                )
            else:
                self.state.record("case_write_back", "skipped", summary=f"Case memory write skipped: {reason}")
            self.state.status = "succeeded"
            response = PipelineResponse(
                status="succeeded",
                pipeline=self.pipeline_name,
                task_id=self.state.task_id,
                run_id=self.state.run_id,
                output=advisory,
                artifact=artifact,
                attempts=self.state.attempt,
                metadata={"memory_records": len(self.state.memory_records), "artifact_path": artifact.path},
            )
            self._result = response
            return response
        except Exception as exc:
            self.state.status = "incomplete"
            self.state.failure = str(exc)
            self.state.record("case_write_back", "failed", summary="Validated output was not persisted", error=str(exc))
            self._result = self._failure_response()
            return self._result

    @listen("rejected")
    def persist_rejection(self, result: HumanFeedbackResult) -> PipelineResponse:
        feedback = getattr(result, "feedback", "Human approval was rejected") or "Human approval was rejected"
        self.state.approval_status = "rejected"
        self.state.approval_feedback = feedback
        self.state.failure = f"Human approval rejected: {feedback}"
        self.state.status = "failed"
        self.state.record("human_approval", "rejected", summary=feedback)
        self._write_task_failure("human_approval", feedback)
        self._result = self._failure_response()
        return self._result

    @listen("needs_revision")
    def persist_revision_request(self, result: HumanFeedbackResult) -> PipelineResponse:
        feedback = getattr(result, "feedback", "Revision requested") or "Revision requested"
        self.state.approval_status = "revision_requested"
        self.state.approval_feedback = feedback
        self.state.failure = f"Human revision requested: {feedback}"
        self.state.status = "incomplete"
        self.state.record("human_approval", "retrying", summary=feedback)
        self._write_task_failure("human_approval", feedback)
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
            failure=self.state.failure or "advisory pipeline failed",
            attempts=self.state.attempt,
            metadata={"events": len(self.state.events), "memory_records": len(self.state.memory_records)},
        )
