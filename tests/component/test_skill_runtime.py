from __future__ import annotations

from threading import Event
from time import sleep

from pipelines.common.contracts import PipelineResponse
from pipelines.orchestrator.budget import BudgetController
from pipelines.orchestrator.cache import CacheStore
from pipelines.orchestrator.contracts import RunPolicy, SkillCall, SkillManifest
from pipelines.orchestrator.skill_runtime import RunContext, SkillRuntime
from pipelines.orchestrator.types import PipelineAdapter


def manifest(skill_id: str = "visual.flowchart") -> SkillManifest:
    return SkillManifest(
        skill_id=skill_id,
        version="1.0.0",
        purpose="test specialist",
        input_schema="ContextPack",
        output_artifact_types=["diagram.ir"],
        required_capabilities=["render.diagram"],
        allowed_tools=["diagram.layout"],
        risk_class="RESTRICTED",
    )


def call(*, skill_id: str = "visual.flowchart", policy: RunPolicy | None = None) -> SkillCall:
    return SkillCall(
        skill_call_id="call-1",
        parent_run_id="run-1",
        parent_node_id="node-1",
        skill_id=skill_id,
        skill_version="1.0.0",
        policy=policy or RunPolicy(max_model_tokens=1000, max_wall_time_ms=500),
        input_payload={"query": "make a flowchart", "metadata": {"source": "test"}},
    )


def context(**kwargs) -> RunContext:
    values = {
        "run_id": "run-1",
        "task_id": "task-1",
        "user_id": "operator-1",
        "case_id": "case-1",
        "policy": RunPolicy(max_model_tokens=1000, max_wall_time_ms=500),
        "allowed_capabilities": frozenset({"render.diagram"}),
        "allowed_tools": frozenset({"diagram.layout"}),
    }
    values.update(kwargs)
    return RunContext(**values)


def test_runtime_wraps_adapter_and_returns_typed_artifact_references() -> None:
    events = []

    def runner(request):
        return PipelineResponse(
            status="succeeded",
            pipeline="visual.flowchart",
            task_id=request.task_id,
            run_id=request.parent_run_id or request.task_id,
            output={"kind": "DiagramIR"},
            artifact={"artifact_ids": ["artifact-1"]},
            metadata={"quality_report_id": "quality-1", "usage_ids": ["usage-1"]},
        )

    runtime = SkillRuntime(
        {"visual.flowchart": PipelineAdapter("visual.flowchart", runner)},
        {"visual.flowchart": manifest()},
        event_sink=lambda name, payload: events.append((name, payload)),
    )
    result = runtime.invoke(call(), parent_context=context())

    assert result.status == "succeeded"
    assert result.artifact_ids == ["artifact-1"]
    assert result.quality_report_id == "quality-1"
    assert [name for name, _ in events] == ["skill.started", "skill.completed"]
    assert events[0][1]["parent_run_id"] == "run-1"


def test_runtime_rejects_cycle_budget_and_permission_violations_before_adapter() -> None:
    invoked = []
    runtime = SkillRuntime(
        {"visual.flowchart": PipelineAdapter("visual.flowchart", lambda request: invoked.append(request))},
        {"visual.flowchart": manifest()},
    )

    cycle = runtime.invoke(call(), parent_context=context(ancestors=("visual.flowchart",)))
    budget = runtime.invoke(
        call(policy=RunPolicy(max_model_tokens=2000, max_wall_time_ms=500)),
        parent_context=context(),
    )
    denied = runtime.invoke(
        call(),
        parent_context=context(allowed_capabilities=frozenset()),
    )

    assert cycle.status == "blocked" and cycle.failure_code == "SKILL_CYCLE"
    assert budget.status == "blocked" and budget.failure_code == "TOKEN_BUDGET"
    assert denied.status == "blocked" and denied.failure_code == "CAPABILITY_DENIED"
    assert invoked == []


def test_runtime_timeout_is_bounded_and_parent_cancellation_is_cooperative() -> None:
    def slow_runner(request):
        sleep(0.2)
        return PipelineResponse(
            status="succeeded",
            pipeline="visual.flowchart",
            task_id=request.task_id,
            run_id=request.task_id,
            output={"ok": True},
        )

    runtime = SkillRuntime(
        {"visual.flowchart": PipelineAdapter("visual.flowchart", slow_runner)},
        {"visual.flowchart": manifest()},
    )
    timed_out = runtime.invoke(
        call(policy=RunPolicy(max_model_tokens=1000, max_wall_time_ms=30)),
        parent_context=context(policy=RunPolicy(max_model_tokens=1000, max_wall_time_ms=30)),
    )
    assert timed_out.status == "failed"
    assert timed_out.failure_code == "CHILD_TIMEOUT"

    cancel_event = Event()
    cancel_event.set()
    cancelled = runtime.invoke(call(), parent_context=context(cancel_event=cancel_event))
    assert cancelled.status == "cancelled"
    assert cancelled.failure_code == "PARENT_CANCELLED"


def test_runtime_reserves_and_commits_provider_usage() -> None:
    controller = BudgetController()

    def runner(request):
        return PipelineResponse(
            status="succeeded",
            pipeline="visual.flowchart",
            task_id=request.task_id,
            run_id=request.task_id,
            output={"ok": True},
            metadata={
                "usage": {
                    "provider": "test",
                    "model": "test-model",
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "tool_calls": 1,
                    "latency_ms": 25,
                    "is_estimate": True,
                }
            },
        )

    runtime = SkillRuntime(
        {"visual.flowchart": PipelineAdapter("visual.flowchart", runner)},
        {"visual.flowchart": manifest()},
        budget_controller=controller,
    )
    result = runtime.invoke(
        call(policy=RunPolicy(max_model_tokens=1000, max_wall_time_ms=500, max_tool_calls=2)),
        parent_context=context(policy=RunPolicy(max_model_tokens=1000, max_wall_time_ms=500, max_tool_calls=2)),
    )

    assert result.status == "succeeded"
    snapshot = controller.snapshot("run-1")
    assert snapshot.used_model_tokens == 150
    assert snapshot.used_tool_calls == 1
    assert snapshot.active_concurrency == 0


def test_runtime_reuses_only_quality_passed_artifact_from_cache() -> None:
    invocations = []

    def runner(request):
        invocations.append(request)
        return PipelineResponse(
            status="succeeded",
            pipeline="visual.flowchart",
            task_id=request.task_id,
            run_id=request.task_id,
            output={"ok": True},
            artifact={"artifact_ids": ["artifact-cached"]},
            metadata={
                "quality_status": "passed",
                "quality_report_id": "quality-cached",
            },
        )

    events = []
    runtime = SkillRuntime(
        {"visual.flowchart": PipelineAdapter("visual.flowchart", runner)},
        {"visual.flowchart": manifest()},
        cache_store=CacheStore(":memory:"),
        event_sink=lambda name, payload: events.append((name, payload)),
    )
    first = runtime.invoke(call(), parent_context=context())
    second = runtime.invoke(call(), parent_context=context())

    assert first.status == "succeeded"
    assert second.status == "succeeded"
    assert second.artifact_ids == ["artifact-cached"]
    assert len(invocations) == 1
    assert [name for name, _ in events].count("skill.cache_hit") == 1
