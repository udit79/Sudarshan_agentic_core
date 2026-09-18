"""Reusable automatic text-generation Flow for frontend-owned delivery."""

from __future__ import annotations

from dataclasses import dataclass
import json
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
from pipelines.common.usage_capture import aggregate_crew_usage, capture_crew_usage
from pipelines.orchestrator.spend_guard import (
    ProviderSpendGuard,
    TokenBudgetReservation,
    bound_text,
    declared_provider_reservation,
    output_tokens_per_call,
    usage_tokens,
)
from integrations.providers.router import ProviderRouter


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
    # A draft may require explicit human approval even though this generic
    # Flow has no interactive approval step of its own.
    human_approval_required = False
    # Subclasses may opt into local preview rendering for a valid structured
    # draft that failed the quality gate. The response remains ``failed`` and
    # the frontend must label the artifact as a draft; this is only a preview
    # path and never case-writes rejected content.
    render_failed_draft = False

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
        self._spend_guard: ProviderSpendGuard | None = None
        self._preflight_reservation: TokenBudgetReservation | None = None
        self._preflight_reserved_tokens = 0

    def run(self, request: AdvisoryRequest) -> PipelineResponse:
        self._result = None
        self.state.usage_records = []
        self.state.stage_usage_records = []
        self.state.pipeline_name = self.pipeline_name
        self.state.pipeline_options = {
            **self.pipeline_options(request),
            "request_understanding": request.metadata.get("request_understanding", {}),
            "prompt_plan": request.metadata.get("prompt_plan", {}),
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
        raw_provider_budget = request.metadata.get("provider_token_budget")
        if raw_provider_budget is None:
            budget_cap = request.metadata.get("budget_cap")
            if isinstance(budget_cap, Mapping):
                raw_provider_budget = budget_cap.get("max_model_tokens")
        if isinstance(raw_provider_budget, int) and raw_provider_budget >= 256:
            self.state.provider_token_budget = raw_provider_budget
            # A hard total budget cannot safely assume that a second retry will
            # fit, so explicit provider-budget mode admits one provider attempt.
            self._spend_guard = ProviderSpendGuard(max_tokens=raw_provider_budget, max_attempts=1)
        else:
            self.state.provider_token_budget = None
            self._spend_guard = None
        self.state.provider_tokens_used = 0
        self.state.provider_budget_exceeded = False
        self._preflight_reservation = None
        self._preflight_reserved_tokens = 0
        self.state.operation = request.operation
        raw_constraints = request.constraints
        if hasattr(raw_constraints, "model_dump"):
            raw_constraints = raw_constraints.model_dump(mode="json")
        self.state.constraints = dict(raw_constraints or {}) if isinstance(raw_constraints, Mapping) else {}
        self.state.parent_run_id = request.parent_run_id
        self.state.parent_artifact_id = request.parent_artifact_id
        self.state.revision_instruction = request.revision_instruction
        self.state.revision_scope = list(request.revision_scope)
        self.state.request_understanding = dict(request.metadata.get("request_understanding", {}))
        self.state.prompt_plan = dict(request.metadata.get("prompt_plan", {}))
        self.state.pipeline_options = {
            "request_understanding": request.metadata.get("request_understanding", {}),
            "prompt_plan": request.metadata.get("prompt_plan", {}),
            "resolved_memory_context": request.metadata.get("resolved_memory_context"),
            "resolved_memory_records": request.metadata.get("resolved_memory_records", []),
            **dict(request.metadata.get("pipeline_options", {})),
        }
        if "provider_output_token_budget" in request.metadata:
            self.state.pipeline_options["provider_output_token_budget"] = request.metadata.get(
                "provider_output_token_budget"
            )
        if "provider_input_token_budget" in request.metadata:
            self.state.pipeline_options["provider_input_token_budget"] = request.metadata.get(
                "provider_input_token_budget"
            )
        for key in ("provider_budget_preflight", "provider_call_count", "provider_context_compaction"):
            if key in request.metadata:
                self.state.pipeline_options[key] = request.metadata.get(key)
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
        # CrewAI can finish a routed flow without invoking the terminal
        # listener (for example after a rejected retry). Preserve the actual
        # quality-gate failure instead of replacing it with an opaque message.
        self.state.status = "failed"
        self.state.failure = self.state.failure or "flow completed without a terminal response"
        self._result = self._failure_response()
        return self._result

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
            constraints=dict(self.state.constraints),
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

    def prepare_quality_output(self, output: BaseModel) -> BaseModel:
        """Apply deterministic, side-effect-free checks before the quality gate."""

        return output

    def quality_output_issues(self, output: BaseModel) -> list[str]:
        """Return concrete non-LLM quality failures for the structured output."""

        return []

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
            query=request.query,
            prompt_plan=dict(self.state.prompt_plan),
            compact_task_context=self.state.pipeline_options.get("provider_context_compaction") is True,
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
        if not self._preflight_provider_budget():
            return TextCrewRun(error=self.state.failure)
        if self._spend_guard is not None and not self._spend_guard.admit_attempt():
            self.state.provider_budget_exceeded = True
            self.state.failure = "PROVIDER_TOKEN_BUDGET_EXCEEDED: retry admission denied"
            self.state.record(
                "provider_budget",
                "rejected",
                summary="Provider retry denied because the observed token budget is exhausted",
                error=self.state.failure,
            )
            return TextCrewRun(error=self.state.failure)
        self.state.attempt += 1
        self.state.record(self.pipeline_name, "started", summary="Starting sequential text-generation crew")
        writer = TaskMemoryWriter(
            self._runtime(),
            on_event=self.progress_callback,
            on_usage=self._record_stage_usage,
        )
        from time import perf_counter

        started = perf_counter()
        captured = False
        try:
            agents = self.agent_factory(
                memory_tools(self._runtime()),
                llm=self._budgeted_llm(),
            )  # type: ignore[misc]
            tasks = self.task_factory(agents, writer)  # type: ignore[misc]
            crew = Crew(
                agents=list(agents.values()),
                tasks=list(tasks.values()),
                process=Process.sequential,
                verbose=False,
            )
            with writer.activate():
                quality_feedback = (
                    self.state.failure[-12000:]
                    if self.state.attempt > 1 and self.state.failure
                    else "No previous quality-gate feedback; produce the first draft against the stated requirements."
                )
                crew_result = crew.kickoff(inputs=self._crew_inputs(quality_feedback))
            usage_record = capture_crew_usage(
                crew_result,
                run_id=self.state.run_id,
                pipeline=self.pipeline_name,
                attempt=self.state.attempt,
                latency_ms=round((perf_counter() - started) * 1000),
                model_ref=self.llm,
            )
            usage_record["stage_usage"] = list(self.state.stage_usage_records)
            self.state.usage_records.append(usage_record)
            if self._preflight_reservation is not None:
                self._preflight_reservation.reconcile(
                    self._preflight_reserved_tokens,
                    usage_tokens(usage_record),
                )
            if self._spend_guard is not None:
                self.state.provider_tokens_used += usage_tokens(usage_record)
                if self._spend_guard.record(usage_tokens(usage_record)):
                    self.state.provider_budget_exceeded = True
                    self.state.failure = (
                        "PROVIDER_TOKEN_BUDGET_EXCEEDED: observed provider usage exceeded the configured cap"
                    )
                    self.state.record(
                        "provider_budget",
                        "rejected",
                        summary="Provider usage exceeded the configured retry-spend cap",
                        error=self.state.failure,
                    )
                    return TextCrewRun(error=self.state.failure)
            captured = True
            output = self.output_model.model_validate(getattr(tasks["output"].output, "pydantic", None))  # type: ignore[union-attr]
            output = self.prepare_quality_output(output)
            quality = self.quality_model.model_validate(getattr(tasks["quality"].output, "pydantic", None))  # type: ignore[union-attr]
            self.state.record(self.pipeline_name, "succeeded", summary="Text-generation crew completed")
            return TextCrewRun(output=output, quality=quality)
        except Exception as exc:
            if not captured:
                usage_record = capture_crew_usage(
                    None,
                    run_id=self.state.run_id,
                    pipeline=self.pipeline_name,
                    attempt=self.state.attempt,
                    latency_ms=round((perf_counter() - started) * 1000),
                    model_ref=self.llm,
                )
                self.state.usage_records.append(usage_record)
            self.state.failure = str(exc)
            self.state.record(self.pipeline_name, "failed", summary="Text-generation crew failed", error=str(exc))
            self._write_task_failure(self.pipeline_name, str(exc))
            return TextCrewRun(error=str(exc))

    def _record_stage_usage(self, stage: str, usage: dict[str, Any]) -> None:
        """Keep per-task counters separate from aggregate pipeline totals."""

        self.state.stage_usage_records.append({
            "stage": stage,
            "attempt": max(1, self.state.attempt),
            **{
                key: value
                for key, value in usage.items()
                if key != "stage"
            },
        })

    def _preflight_provider_budget(self) -> bool:
        """Reserve a declared benchmark budget before provider execution.

        This path is opt-in through request metadata. Existing requests keep
        the historical behavior until a pipeline-specific profile is ready.
        """

        options = self.state.pipeline_options
        if options.get("provider_budget_preflight") is not True:
            return True

        total_budget = self.state.provider_token_budget
        if total_budget is None:
            return self._reject_preflight("provider token budget is missing")

        try:
            input_budget = int(options["provider_input_token_budget"])
            output_budget = int(options["provider_output_token_budget"])
            call_count = int(options["provider_call_count"])
        except (KeyError, TypeError, ValueError):
            return self._reject_preflight(
                "provider preflight requires input budget, output budget, and call count"
            )

        if input_budget < 1 or output_budget < 1 or call_count < 1:
            return self._reject_preflight("provider preflight values must be positive")

        planned = declared_provider_reservation(
            input_tokens_per_call=input_budget,
            output_tokens_per_call=output_budget,
            provider_call_count=call_count,
        )
        ledger = TokenBudgetReservation(max_tokens=total_budget)
        if not ledger.reserve(planned):
            return self._reject_preflight(
                "declared provider reservation exceeds the configured total budget"
            )

        self._preflight_reservation = ledger
        self._preflight_reserved_tokens = planned
        self.state.pipeline_options["provider_reserved_tokens"] = planned
        self.state.record(
            "provider_budget",
            "succeeded",
            summary=f"Reserved {planned} declared provider tokens before execution",
        )
        return True

    def _reject_preflight(self, reason: str) -> bool:
        self.state.provider_budget_exceeded = True
        self.state.failure = f"PROVIDER_BUDGET_PREFLIGHT_REJECTED: {reason}"
        self.state.record(
            "provider_budget",
            "rejected",
            summary="Provider execution rejected by benchmark budget preflight",
            error=self.state.failure,
        )
        return False

    def _budgeted_llm(self) -> Any:
        """Return an LLM configured with a conservative per-call output cap."""

        if self.state.provider_token_budget is None:
            return self.llm
        raw_output_budget = self.state.pipeline_options.get("provider_output_token_budget")
        if isinstance(raw_output_budget, int) and raw_output_budget >= 256:
            cap = raw_output_budget
        else:
            cap = output_tokens_per_call(self.state.provider_token_budget)
        configured = ProviderRouter.configured_model("text", self.llm)
        if isinstance(configured, str) and configured.strip():
            from crewai import LLM

            model = configured.strip()
            if TextTransformationFlow._uses_completion_token_parameter(model):
                # CrewAI's normal ``max_completion_tokens`` field is translated
                # back to ``max_tokens`` by its request builder.  Keep both
                # fields empty and inject the provider-native parameter so
                # GPT-5-family APIs receive only ``max_completion_tokens``.
                return LLM(
                    model=model,
                    max_tokens=None,
                    max_completion_tokens=None,
                    additional_params={"max_completion_tokens": cap},
                )
            return LLM(model=model, max_tokens=cap)
        if self.llm is not None and callable(getattr(self.llm, "model_copy", None)):
            if TextTransformationFlow._uses_completion_token_parameter(self.llm):
                additional_params = dict(getattr(self.llm, "additional_params", {}) or {})
                additional_params["max_completion_tokens"] = cap
                return self.llm.model_copy(
                    update={
                        "max_tokens": None,
                        "max_completion_tokens": None,
                        "additional_params": additional_params,
                    }
                )
            return self.llm.model_copy(update={"max_tokens": cap})
        raise RuntimeError(
            "PROVIDER_BUDGET_UNAPPLIED: explicit provider budget requires a cloneable or configured LLM"
        )

    @staticmethod
    def _uses_completion_token_parameter(model: object) -> bool:
        """Identify model families that reject the legacy ``max_tokens`` key."""

        model_name = str(getattr(model, "model", model) or "").strip().lower()
        model_name = model_name.rsplit("/", 1)[-1]
        return model_name.startswith(("gpt-5", "o1", "o3", "o4"))

    def _crew_inputs(self, quality_feedback: str) -> dict[str, Any]:
        """Bound dynamic prompt fields without changing the default path."""

        inputs: dict[str, Any] = {
            "query": self.state.query,
            "memory_context": self.state.memory_context,
            "task_id": self.state.task_id,
            "case_id": self.state.case_id,
            "classification_level": self.state.classification_level,
            "distribution": self.state.distribution,
            "constraints": self.state.constraints,
            "run_id": self.state.run_id,
            "pipeline_options": self.state.pipeline_options,
            "prompt_plan": self.state.prompt_plan,
            "request_understanding": self.state.request_understanding,
            "quality_feedback": quality_feedback,
        }
        budget = self.state.provider_token_budget
        if budget is None:
            return inputs
        raw_input_budget = self.state.pipeline_options.get("provider_input_token_budget", budget)
        try:
            input_budget = max(256, int(raw_input_budget))
        except (TypeError, ValueError):
            input_budget = max(256, budget)

        def bounded(value: Any, token_cap: int) -> str:
            if isinstance(value, str):
                text = value
            else:
                text = json.dumps(value, sort_keys=True, default=str)
            return bound_text(text, token_cap)

        inputs.update({
            "query": bounded(self.state.query, max(1, input_budget // 5)),
            "memory_context": bounded(self.state.memory_context, max(1, (input_budget * 2) // 5)),
            "constraints": bounded(self.state.constraints, max(1, input_budget // 10)),
            "pipeline_options": bounded(self.state.pipeline_options, max(1, input_budget // 10)),
            "prompt_plan": bounded(self.state.prompt_plan, max(1, input_budget // 10)),
            "request_understanding": bounded(self.state.request_understanding, max(1, input_budget // 10)),
            "quality_feedback": bounded(quality_feedback, max(1, input_budget // 10)),
        })
        return inputs

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
        prepared_output = self.prepare_quality_output(result.output)
        deterministic_issues = self.quality_output_issues(prepared_output)
        self.state.output = prepared_output.model_dump(mode="json")
        quality_data = result.quality.model_dump(mode="json")
        if deterministic_issues:
            quality_data["issues"] = [*quality_data.get("issues", []), *deterministic_issues]
            quality_data["approved"] = False
        self.state.quality_review = quality_data
        if quality_data.get("approved") is True and not deterministic_issues:
            self.state.record("quality_gate", "succeeded", summary="Output approved for frontend delivery")
            return True
        issues = quality_data.get("issues", []) + quality_data.get("required_revisions", [])
        self.state.failure = "; ".join(issues) or "Quality critic rejected the output"
        self.state.record("quality_gate", "rejected", summary=self.state.failure)
        return False

    @router(validate_crew)
    def route_validation(self) -> str:
        if self.state.output and self.state.quality_review and self.state.quality_review.get("approved"):
            return "complete"
        if self.state.provider_budget_exceeded:
            return "failed"
        if self.state.attempt < self.state.max_attempts:
            return "retry"
        return "failed"

    @listen("complete")
    def persist_output(self) -> PipelineResponse:
        try:
            output = self.output_model.model_validate(self.state.output)  # type: ignore[union-attr]
            output = self.enrich_output(output)
            self.state.output = output.model_dump(mode="json")
            from pipelines.common.release_gate import can_release_to_case_memory

            quality_approved = bool(self.state.quality_review and self.state.quality_review.get("approved"))
            artifact = self.state.artifact
            artifact_data = artifact if isinstance(artifact, Mapping) else {}
            request_metadata = self._request().metadata
            releasable, reason = can_release_to_case_memory(
                pipeline=self.pipeline_name,
                output=output,
                quality_approved=quality_approved,
                status="succeeded",
                artifact=artifact,
                operator_waiver_id=artifact_data.get("operator_waiver_id"),
                memory_policy_allows_degraded=bool(
                    request_metadata.get("memory_policy_allows_degraded", False)
                ),
                human_approval_required=self.human_approval_required,
                human_approved=not self.human_approval_required,
            )
            if releasable:
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
                        "human_approval_required": self.human_approval_required,
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
            else:
                self.state.record("case_write_back", "skipped", summary=f"Case memory write skipped: {reason}")
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
                    "human_approval_required": self.human_approval_required,
                    **self._usage_metadata(),
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
        output = self.state.output
        if output and self.render_failed_draft:
            try:
                draft = self.output_model.model_validate(output)  # type: ignore[union-attr]
                rendered_draft = self.enrich_output(draft)
                output = rendered_draft.model_dump(mode="json")
                self.state.output = output
            except Exception as exc:
                self.state.record(
                    "draft_render",
                    "failed",
                    summary="Rejected draft could not be rendered locally",
                    error=str(exc),
                )
        failed_state = {
            "status": self.state.status,
            "attempt": self.state.attempt,
            "max_attempts": self.state.max_attempts,
            "failure": self.state.failure,
            "quality_review": self.state.quality_review or {},
            "token_budget": self.state.token_budget,
            "provider_token_budget": self.state.provider_token_budget,
            "provider_tokens_used": self.state.provider_tokens_used,
            "provider_budget_exceeded": self.state.provider_budget_exceeded,
        }
        return PipelineResponse(
            status="failed",
            pipeline=self.pipeline_name,
            task_id=self.state.task_id,
            run_id=self.state.run_id,
            # Preserve the last structured draft even when the quality gate
            # rejects it. This lets the gateway persist the failed state and
            # lets the frontend show the draft and exact review feedback.
            output=output,
            artifact=self.state.artifact,
            failure=self.state.failure or "text transformation pipeline failed",
            attempts=self.state.attempt,
            metadata={
                "events": len(self.state.events),
                "memory_records": len(self.state.memory_records),
                "rendered_as_failed_draft": bool(output and self.render_failed_draft and self.state.artifact),
                "quality_review": self.state.quality_review or {},
                "failed_state": failed_state,
                "usage": aggregate_crew_usage(
                    self.state.usage_records,
                    run_id=self.state.run_id,
                    pipeline=self.pipeline_name,
                ),
                "usage_records": list(self.state.usage_records),
                "provider_token_budget": self.state.provider_token_budget,
                "provider_tokens_used": self.state.provider_tokens_used,
                "provider_budget_exceeded": self.state.provider_budget_exceeded,
            },
        )

    def _usage_metadata(self) -> dict[str, Any]:
        return {
            "usage": aggregate_crew_usage(
                self.state.usage_records,
                run_id=self.state.run_id,
                pipeline=self.pipeline_name,
            ),
            "usage_records": list(self.state.usage_records),
            "provider_token_budget": self.state.provider_token_budget,
            "provider_tokens_used": self.state.provider_tokens_used,
            "provider_budget_exceeded": self.state.provider_budget_exceeded,
        }
