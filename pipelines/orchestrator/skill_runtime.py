"""Typed, bounded child-skill execution for the native orchestrator.

The runtime is intentionally smaller than the top-level graph. It is the
composition boundary used by a parent skill when it needs a specialist such
as a flowchart, infographic, or video renderer. A child is invoked in-process
through a registered adapter; production deployments may replace the adapter
call with a durable child job without changing ``SkillCall``/``SkillResult``.

This module never calls the public Run API recursively. It validates the child
call, derives a scoped request, runs the existing adapter, and returns only a
typed result and references to child outputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from queue import Empty, Queue
from threading import Event, Lock, Thread
from time import monotonic
from typing import Any, Callable, Mapping
from uuid import uuid4

from pipelines.common.contracts import AdvisoryRequest, PipelineResponse
from pipelines.orchestrator.contracts import (
    RunPolicy,
    SkillCall,
    SkillManifest,
    SkillResult,
    UsageRecord,
)
from pipelines.orchestrator.budget import BudgetController, BudgetExceededError
from pipelines.orchestrator.cache import CacheStore, build_cache_fingerprint, stable_hash
from pipelines.orchestrator.types import PipelineAdapter


class SkillRuntimeError(RuntimeError):
    """A policy or lifecycle rejection with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class RunContext:
    """Safe parent context inherited by one child invocation."""

    run_id: str
    task_id: str
    user_id: str
    case_id: str
    classification_level: str = "RESTRICTED"
    distribution: str = "Authorized NTRO personnel"
    policy: RunPolicy = field(default_factory=RunPolicy)
    ancestors: tuple[str, ...] = ()
    allowed_capabilities: frozenset[str] | None = None
    allowed_tools: frozenset[str] | None = None
    allowed_trust_tiers: frozenset[str] | None = None
    approved_side_effects: frozenset[str] = frozenset()
    cancel_event: Event = field(default_factory=Event, compare=False, repr=False)


EventSink = Callable[[str, Mapping[str, Any]], None]


class SkillRuntime:
    """Execute registered child skills under typed policy and lifecycle rules."""

    def __init__(
        self,
        adapters: Mapping[str, PipelineAdapter],
        manifests: Mapping[str, SkillManifest],
        *,
        event_sink: EventSink | None = None,
        budget_controller: BudgetController | None = None,
        cache_store: CacheStore | None = None,
    ) -> None:
        self._adapters = dict(adapters)
        self._manifests = dict(manifests)
        self._event_sink = event_sink
        self._budget_controller = budget_controller
        self._cache_store = cache_store
        self._active_lock = Lock()
        self._active_by_parent: dict[str, int] = {}

    def invoke(self, call: SkillCall, *, parent_context: RunContext) -> SkillResult:
        """Invoke one child adapter without entering the public Run API."""

        try:
            manifest, adapter = self._validate_call(call, parent_context)
        except SkillRuntimeError as error:
            self._emit("skill.blocked", call, error_code=error.code, message=str(error))
            return SkillResult(
                skill_call_id=call.skill_call_id,
                child_run_id=self._child_id(call),
                status="blocked",
                failure_code=error.code,
                failure_message=str(error),
            )

        child_run_id = self._child_id(call)
        child_task_id = f"skill-task-{uuid4().hex}"
        cache_fingerprint: str | None = None
        cache_claim_owner: str | None = None
        if self._cache_store is not None:
            cache_fingerprint = self._cache_fingerprint(call, parent_context, manifest)
            cached = self._cache_store.get(cache_fingerprint)
            if cached is not None:
                self._emit(
                    "skill.cache_hit",
                    call,
                    child_run_id=child_run_id,
                    fingerprint=cache_fingerprint,
                    quality_report_id=cached.quality_report_id,
                )
                return SkillResult(
                    skill_call_id=call.skill_call_id,
                    child_run_id=child_run_id,
                    status="succeeded",
                    artifact_ids=list(cached.artifact_ids),
                    quality_report_id=cached.quality_report_id,
                )
            cache_claim_owner = self._cache_store.try_claim(cache_fingerprint)
            if cache_claim_owner is None:
                self._emit("skill.cache_wait", call, fingerprint=cache_fingerprint)
                return SkillResult(
                    skill_call_id=call.skill_call_id,
                    child_run_id=child_run_id,
                    status="waiting",
                    failure_code="CACHE_IN_FLIGHT",
                    failure_message="An equivalent skill execution is already producing a cacheable artifact.",
                )
        try:
            self._reserve_slot(call, parent_context)
        except SkillRuntimeError as error:
            if cache_fingerprint is not None and cache_claim_owner is not None:
                self._cache_store.release_claim(cache_fingerprint, cache_claim_owner)
            self._emit("skill.blocked", call, error_code=error.code, message=str(error))
            return SkillResult(
                skill_call_id=call.skill_call_id,
                child_run_id=child_run_id,
                status="blocked",
                failure_code=error.code,
                failure_message=str(error),
            )

        budget_reservation_id: str | None = None
        budget_settled = False
        if self._budget_controller is not None:
            try:
                self._budget_controller.register_run(call.parent_run_id, parent_context.policy)
                reservation = self._budget_controller.reserve(
                    call.parent_run_id,
                    node_id=call.parent_node_id,
                    model_tokens=call.policy.max_model_tokens,
                    tool_calls=call.policy.max_tool_calls,
                    wall_time_ms=call.policy.max_wall_time_ms,
                    cost=call.policy.max_cost or 0.0,
                )
                budget_reservation_id = reservation.reservation_id
            except BudgetExceededError as error:
                self._release_slot(call, parent_context)
                self._emit("skill.blocked", call, error_code=error.code, message=str(error))
                return SkillResult(
                    skill_call_id=call.skill_call_id,
                    child_run_id=child_run_id,
                    status="blocked",
                    failure_code=error.code,
                    failure_message=str(error),
                )

        self._emit("skill.started", call, child_run_id=child_run_id, manifest_version=manifest.version)
        try:
            child_cancel_event = Event()
            request = self._build_request(call, parent_context, child_task_id, child_cancel_event)
            if parent_context.cancel_event.is_set():
                child_cancel_event.set()
                return self._cancelled(call, child_run_id, "PARENT_CANCELLED")

            response, timed_out = self._run_with_timeout(
                adapter,
                request,
                timeout_ms=min(call.policy.max_wall_time_ms, parent_context.policy.max_wall_time_ms),
                parent_cancel_event=parent_context.cancel_event,
                child_cancel_event=child_cancel_event,
            )
            if timed_out:
                if budget_reservation_id is not None:
                    self._budget_controller.release(budget_reservation_id)
                    budget_settled = True
                result = SkillResult(
                    skill_call_id=call.skill_call_id,
                    child_run_id=child_run_id,
                    status="failed",
                    failure_code="CHILD_TIMEOUT",
                    failure_message="Child skill exceeded its wall-time budget.",
                )
                self._emit("skill.failed", call, child_run_id=child_run_id, error_code=result.failure_code)
                return result
            if parent_context.cancel_event.is_set():
                if budget_reservation_id is not None and not budget_settled:
                    self._budget_controller.release(budget_reservation_id)
                    budget_settled = True
                return self._cancelled(call, child_run_id, "PARENT_CANCELLED")

            usage_record = self._usage_from_response(call, response)
            if budget_reservation_id is not None:
                try:
                    self._budget_controller.commit(
                        budget_reservation_id,
                        usage_record,
                    )
                    budget_settled = True
                except BudgetExceededError as error:
                    self._budget_controller.release(budget_reservation_id)
                    budget_settled = True
                    result = SkillResult(
                        skill_call_id=call.skill_call_id,
                        child_run_id=child_run_id,
                        status="failed",
                        failure_code=error.code,
                        failure_message=str(error),
                    )
                    self._emit("skill.failed", call, child_run_id=child_run_id, error_code=error.code)
                    return result

            result = self._result_from_response(call, child_run_id, response)
            self._cache_success(
                cache_fingerprint,
                call,
                manifest,
                response,
                result,
            )
            event_name = {
                "succeeded": "skill.completed",
                "waiting": "skill.waiting",
                "cancelled": "skill.cancelled",
            }.get(result.status, "skill.failed")
            self._emit(
                event_name,
                call,
                child_run_id=child_run_id,
                error_code=result.failure_code,
                artifact_ids=result.artifact_ids,
                quality_report_id=result.quality_report_id,
                usage=usage_record.model_dump(mode="json"),
            )
            return result
        except Exception as error:  # adapters are untrusted plugin boundaries
            result = SkillResult(
                skill_call_id=call.skill_call_id,
                child_run_id=child_run_id,
                status="failed",
                failure_code="CHILD_EXCEPTION",
                failure_message=str(error)[:1000],
            )
            self._emit("skill.failed", call, child_run_id=child_run_id, error_code=result.failure_code)
            return result
        finally:
            if budget_reservation_id is not None and not budget_settled:
                try:
                    self._budget_controller.release(budget_reservation_id)
                except BudgetExceededError:
                    pass
            if cache_fingerprint is not None and cache_claim_owner is not None:
                self._cache_store.release_claim(cache_fingerprint, cache_claim_owner)
            self._release_slot(call, parent_context)

    @staticmethod
    def _cache_fingerprint(call: SkillCall, context: RunContext, manifest: SkillManifest) -> str:
        metadata = call.input_payload.get("metadata", {})
        metadata = metadata if isinstance(metadata, Mapping) else {}
        return build_cache_fingerprint(
            skill_id=call.skill_id,
            skill_version=call.skill_version,
            stage_contract={
                "input_schema": manifest.input_schema,
                "output_artifact_types": manifest.output_artifact_types,
                "quality_gates": manifest.quality_gates,
                "coordination": manifest.coordination,
            },
            input_artifact_hashes=call.input_artifact_ids,
            input_payload_hash=stable_hash(call.input_payload),
            tool_provider_versions=metadata.get("tool_provider_versions", {}),
            model_policy={
                "manifest": manifest.model_policy,
                "call": call.policy.model_dump(mode="json"),
            },
            authorization_scope={
                "user_id": context.user_id,
                "case_id": context.case_id,
                "classification_level": context.classification_level,
                "distribution": context.distribution,
                "allowed_capabilities": sorted(context.allowed_capabilities or ()),
                "allowed_tools": sorted(context.allowed_tools or ()),
                "side_effects": manifest.side_effects,
            },
        )

    def _cache_success(
        self,
        fingerprint: str | None,
        call: SkillCall,
        manifest: SkillManifest,
        response: PipelineResponse,
        result: SkillResult,
    ) -> None:
        if self._cache_store is None or fingerprint is None or result.status != "succeeded":
            return
        metadata = dict(response.metadata or {})
        if metadata.get("quality_status") != "passed" or not result.artifact_ids:
            return
        try:
            self._cache_store.put(
                fingerprint=fingerprint,
                skill_id=manifest.skill_id,
                skill_version=manifest.version,
                artifact_ids=result.artifact_ids,
                quality_report_id=result.quality_report_id,
                quality_status="passed",
                ttl_seconds=(
                    float(metadata["cache_ttl_seconds"])
                    if metadata.get("cache_ttl_seconds") is not None
                    else None
                ),
                metadata={
                    "renderer_version": metadata.get("renderer_version"),
                    "schema_version": metadata.get("schema_version"),
                    "skill_call_id": call.skill_call_id,
                },
            )
        except (TypeError, ValueError, OverflowError):
            # Cache failure must not turn a quality-passed artifact into a
            # failed skill result. The cache is an optimization, not truth.
            self._emit("skill.cache_write_failed", call, fingerprint=fingerprint)

    def _validate_call(
        self,
        call: SkillCall,
        parent_context: RunContext,
    ) -> tuple[SkillManifest, PipelineAdapter]:
        manifest = self._manifests.get(call.skill_id)
        if manifest is None:
            raise SkillRuntimeError("SKILL_NOT_FOUND", f"Skill '{call.skill_id}' is not registered")
        if manifest.version != call.skill_version:
            raise SkillRuntimeError(
                "SKILL_VERSION_MISMATCH",
                f"Skill '{call.skill_id}' requires version {manifest.version}, got {call.skill_version}",
            )
        if call.parent_run_id != parent_context.run_id:
            raise SkillRuntimeError("PARENT_RUN_MISMATCH", "Skill call parent_run_id does not match the active run")
        if call.depth < len(parent_context.ancestors) or call.skill_id in parent_context.ancestors:
            raise SkillRuntimeError("SKILL_CYCLE", "Skill call would create a recursive child cycle")
        if call.depth > call.max_depth:
            raise SkillRuntimeError("DEPTH_EXCEEDED", "Skill call depth exceeds the configured maximum")
        if parent_context.allowed_trust_tiers is not None and manifest.trust_tier not in parent_context.allowed_trust_tiers:
            raise SkillRuntimeError(
                "TRUST_TIER_DENIED",
                f"Skill '{call.skill_id}' trust tier '{manifest.trust_tier}' is not allowed by the parent",
            )
        self._check_policy(call.policy, parent_context.policy)
        if parent_context.allowed_capabilities is not None:
            missing = set(manifest.required_capabilities) - set(parent_context.allowed_capabilities)
            if missing:
                raise SkillRuntimeError("CAPABILITY_DENIED", f"Missing capabilities: {', '.join(sorted(missing))}")
        if parent_context.allowed_tools is not None:
            denied = set(manifest.allowed_tools) - set(parent_context.allowed_tools)
            if denied:
                raise SkillRuntimeError("TOOL_DENIED", f"Disallowed tools: {', '.join(sorted(denied))}")
        for side_effect in manifest.side_effects:
            if side_effect in {"external_write", "publish"} and side_effect not in parent_context.approved_side_effects:
                raise SkillRuntimeError("APPROVAL_REQUIRED", "Child side effect requires an approval boundary")
        adapter = self._adapters.get(call.skill_id)
        if adapter is None:
            # Compatibility aliases can point a manifest at a legacy pipeline.
            adapter = self._adapters.get(call.skill_id.split(".", 1)[-1])
        if adapter is None:
            raise SkillRuntimeError("ADAPTER_NOT_FOUND", f"No adapter is registered for '{call.skill_id}'")
        return manifest, adapter

    @staticmethod
    def _check_policy(child: RunPolicy, parent: RunPolicy) -> None:
        checks = (
            (child.max_wall_time_ms, parent.max_wall_time_ms, "WALL_TIME_BUDGET"),
            (child.max_model_tokens, parent.max_model_tokens, "TOKEN_BUDGET"),
            (child.max_tool_calls, parent.max_tool_calls, "TOOL_BUDGET"),
        )
        for requested, available, code in checks:
            if requested > available:
                raise SkillRuntimeError(code, f"Child policy exceeds parent {code.lower()}")
        if parent.max_cost is not None and (child.max_cost is None or child.max_cost > parent.max_cost):
            raise SkillRuntimeError("COST_BUDGET", "Child policy exceeds parent cost budget")

    def _reserve_slot(self, call: SkillCall, context: RunContext) -> None:
        with self._active_lock:
            active = self._active_by_parent.get(context.run_id, 0)
            if active >= context.policy.max_parallel_children:
                raise SkillRuntimeError("CHILD_CONCURRENCY_LIMIT", "Parent child concurrency budget is exhausted")
            self._active_by_parent[context.run_id] = active + 1

    def _release_slot(self, call: SkillCall, context: RunContext) -> None:
        with self._active_lock:
            active = self._active_by_parent.get(context.run_id, 1) - 1
            if active <= 0:
                self._active_by_parent.pop(context.run_id, None)
            else:
                self._active_by_parent[context.run_id] = active

    @staticmethod
    def _child_id(call: SkillCall) -> str:
        return f"child-{call.skill_id.replace('.', '-')}-{uuid4().hex}"

    @staticmethod
    def _build_request(
        call: SkillCall,
        context: RunContext,
        child_task_id: str,
        child_cancel_event: Event,
    ) -> AdvisoryRequest:
        payload = dict(call.input_payload)
        query = str(payload.pop("query", payload.pop("prompt", f"Execute skill {call.skill_id}")))[:4000]
        metadata = dict(payload.pop("metadata", {}))
        # Identity, scope, and cancellation metadata come only from the
        # trusted parent context; child payloads are untrusted plugin input.
        for protected in {
            "user_id", "case_id", "task_id", "parent_run_id", "classification_level",
            "distribution", "requested_pipelines", "_cancel_event",
        }:
            metadata.pop(protected, None)
        metadata.update({
            "skill_call_id": call.skill_call_id,
            "parent_run_id": context.run_id,
            "user_id": context.user_id,
            "case_id": context.case_id,
            "task_id": child_task_id,
            "classification_level": context.classification_level,
            "distribution": context.distribution,
            "requested_pipelines": [call.skill_id],
            # Internal adapter seam. It is not serialized by as_inputs or
            # projected into safe events, but cooperative adapters can use it.
            "_cancel_event": child_cancel_event,
        })
        return AdvisoryRequest(
            query=query,
            user_id=context.user_id,
            case_id=context.case_id,
            task_id=child_task_id,
            classification_level=context.classification_level,
            distribution=context.distribution,
            token_budget=call.policy.max_model_tokens,
            metadata=metadata,
            requested_pipelines=(call.skill_id,),
        )

    @staticmethod
    def _run_with_timeout(
        adapter: PipelineAdapter,
        request: AdvisoryRequest,
        *,
        timeout_ms: int,
        parent_cancel_event: Event,
        child_cancel_event: Event,
    ) -> tuple[PipelineResponse, bool]:
        result_queue: Queue[PipelineResponse | BaseException] = Queue(maxsize=1)

        def worker() -> None:
            try:
                result_queue.put(adapter.run(request))
            except BaseException as error:  # surfaced to the invoking runtime
                result_queue.put(error)

        Thread(target=worker, name="sudarshan-child-skill", daemon=True).start()
        deadline = monotonic() + (timeout_ms / 1000)
        while True:
            if parent_cancel_event.is_set():
                child_cancel_event.set()
                return PipelineResponse(
                    status="failed",
                    pipeline=adapter.name,
                    task_id=request.task_id,
                    run_id=request.parent_run_id or request.task_id,
                    failure="Child cancelled by parent",
                ), False
            remaining = deadline - monotonic()
            if remaining <= 0:
                child_cancel_event.set()
                return PipelineResponse(
                    status="failed",
                    pipeline=adapter.name,
                    task_id=request.task_id,
                    run_id=request.parent_run_id or request.task_id,
                    failure="Child timeout",
                ), True
            try:
                outcome = result_queue.get(timeout=min(remaining, 0.05))
            except Empty:
                continue
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome, False

    @staticmethod
    def _result_from_response(call: SkillCall, child_run_id: str, response: PipelineResponse) -> SkillResult:
        metadata = dict(response.metadata or {})
        artifact_ids: list[str] = []
        artifact = response.artifact
        if isinstance(artifact, Mapping):
            raw_ids = artifact.get("artifact_ids", artifact.get("artifact_id", []))
            if isinstance(raw_ids, str):
                artifact_ids = [raw_ids]
            elif isinstance(raw_ids, (list, tuple)):
                artifact_ids = [str(item) for item in raw_ids if str(item).strip()]
        raw_metadata_ids = metadata.get("artifact_ids", [])
        if not artifact_ids and isinstance(raw_metadata_ids, (list, tuple)):
            artifact_ids = [str(item) for item in raw_metadata_ids if str(item).strip()]
        status = {"pending": "waiting", "failed": "failed", "succeeded": "succeeded"}.get(response.status, "failed")
        return SkillResult(
            skill_call_id=call.skill_call_id,
            child_run_id=child_run_id,
            status=status,
            artifact_ids=artifact_ids,
            quality_report_id=metadata.get("quality_report_id"),
            usage_ids=[str(item) for item in metadata.get("usage_ids", []) if str(item).strip()],
            failure_code=metadata.get("failure_code") if status != "succeeded" else None,
            failure_message=response.failure if status != "succeeded" else None,
        )

    @staticmethod
    def _usage_from_response(call: SkillCall, response: PipelineResponse) -> UsageRecord:
        metadata = dict(response.metadata or {})
        raw_usage = metadata.get("usage")
        usage = dict(raw_usage) if isinstance(raw_usage, Mapping) else metadata
        return UsageRecord(
            usage_id=str(usage.get("usage_id", f"usage-{uuid4().hex}")),
            run_id=call.parent_run_id,
            node_id=call.parent_node_id,
            provider=str(usage.get("provider", "unknown")),
            model=str(usage.get("model", "unknown")),
            input_tokens=int(usage.get("input_tokens", 0) or 0),
            output_tokens=int(usage.get("output_tokens", 0) or 0),
            reasoning_tokens=(
                int(usage["reasoning_tokens"])
                if usage.get("reasoning_tokens") is not None else None
            ),
            cache_read_tokens=int(usage.get("cache_read_tokens", 0) or 0),
            cache_write_tokens=int(usage.get("cache_write_tokens", 0) or 0),
            tool_calls=int(usage.get("tool_calls", 0) or 0),
            latency_ms=int(usage.get("latency_ms", 0) or 0),
            estimated_cost=(
                float(usage["estimated_cost"])
                if usage.get("estimated_cost") is not None else None
            ),
            is_estimate=bool(usage.get("is_estimate", True)),
        )

    def _cancelled(self, call: SkillCall, child_run_id: str, code: str) -> SkillResult:
        result = SkillResult(
            skill_call_id=call.skill_call_id,
            child_run_id=child_run_id,
            status="cancelled",
            failure_code=code,
            failure_message="Child skill cancelled by its parent.",
        )
        self._emit("skill.cancelled", call, child_run_id=child_run_id, error_code=code)
        return result

    def _emit(self, name: str, call: SkillCall, **fields: Any) -> None:
        if self._event_sink is None:
            return
        payload = {
            "skill_call_id": call.skill_call_id,
            "parent_run_id": call.parent_run_id,
            "parent_node_id": call.parent_node_id,
            "skill_id": call.skill_id,
            **fields,
        }
        self._event_sink(name, payload)
