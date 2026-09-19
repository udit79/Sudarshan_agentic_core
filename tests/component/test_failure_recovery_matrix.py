from __future__ import annotations

from threading import Event
from time import sleep
from urllib.error import HTTPError

import pytest

from integrations.providers.moneyprinterturbo.client import (
    MoneyPrinterTurboClient,
    MoneyPrinterTurboError,
)
from integrations.providers.router import ProviderRouter
from integrations.deepseek_harness.application import SudarshanApplication
from pipelines.common.contracts import PipelineResponse
from pipelines.common.release_gate import can_release_to_case_memory
from pipelines.orchestrator.contracts import RunPolicy, SkillCall, SkillManifest
from pipelines.orchestrator.observability import runtime_event
from pipelines.orchestrator.skill_runtime import RunContext, SkillRuntime
from pipelines.orchestrator.types import PipelineAdapter


def _manifest() -> SkillManifest:
    return SkillManifest(
        skill_id="visual.flowchart",
        version="1.0.0",
        purpose="failure matrix specialist",
        input_schema="ContextPack",
        output_artifact_types=["diagram.ir"],
        required_capabilities=["render.diagram"],
        allowed_tools=["diagram.layout"],
        risk_class="RESTRICTED",
    )


def _call(*, policy: RunPolicy | None = None) -> SkillCall:
    return SkillCall(
        skill_call_id="failure-call-1",
        parent_run_id="failure-run-1",
        parent_node_id="failure-node-1",
        skill_id="visual.flowchart",
        skill_version="1.0.0",
        policy=policy or RunPolicy(max_model_tokens=1000, max_wall_time_ms=500),
        input_payload={"query": "make a safe test flowchart"},
    )


def _context(**overrides) -> RunContext:
    values = {
        "run_id": "failure-run-1",
        "task_id": "failure-task-1",
        "user_id": "user-1",
        "case_id": "case-1",
        "policy": RunPolicy(max_model_tokens=1000, max_wall_time_ms=500),
        "allowed_capabilities": frozenset({"render.diagram"}),
        "allowed_tools": frozenset({"diagram.layout"}),
    }
    values.update(overrides)
    return RunContext(**values)


def _runtime(runner, events):
    return SkillRuntime(
        {"visual.flowchart": PipelineAdapter("visual.flowchart", runner)},
        {"visual.flowchart": _manifest()},
        event_sink=lambda name, payload: events.append((name, payload)),
    )


def test_pipeline_exception_fails_without_artifact_and_exposes_safe_failure_event() -> None:
    events = []

    def provider_or_pipeline_failure(_request):
        raise RuntimeError("provider HTTP 503 response body must not be logged")

    result = _runtime(provider_or_pipeline_failure, events).invoke(_call(), parent_context=_context())

    assert result.status == "failed"
    assert result.failure_code == "CHILD_EXCEPTION"
    assert result.artifact_ids == []
    assert [name for name, _ in events] == ["skill.started", "skill.failed"]
    assert events[-1][1]["error_code"] == "CHILD_EXCEPTION"
    assert "response body" not in str(events[-1][1])


def test_partial_result_is_visible_as_partial_and_usage_is_counted_once() -> None:
    events = []

    def partial_runner(request):
        return PipelineResponse(
            status="partial",
            pipeline="visual.flowchart",
            task_id=request.task_id,
            run_id=request.parent_run_id or request.task_id,
            output={"status": "partial"},
            artifact={"artifact_ids": ["artifact-partial"]},
            failure="one optional branch failed",
            metadata={
                "usage": {
                    "provider": "fixture",
                    "model": "fixture-model",
                    "input_tokens": 100,
                    "output_tokens": 25,
                    "latency_ms": 7,
                    "is_estimate": True,
                }
            },
        )

    result = _runtime(partial_runner, events).invoke(_call(), parent_context=_context())

    assert result.status == "partial"
    assert result.artifact_ids == ["artifact-partial"]
    # A partial result is recoverable/degraded, not a total failure.
    assert events[-1][0] == "skill.partial"
    assert events[-1][1]["artifact_ids"] == ["artifact-partial"]
    assert events[-1][1]["usage"]["input_tokens"] == 100
    assert events[-1][1]["usage"]["output_tokens"] == 25
    projected = runtime_event("skill.partial", events[-1][1])
    assert projected is not None
    assert projected.status == "partial"


def test_application_progress_projection_preserves_partial_status() -> None:
    published = []

    class Sink:
        def publish(self, event):
            published.append(event)

    app = object.__new__(SudarshanApplication)
    app.observability = None
    app._run_contexts = {"failure-run-1": {"task_id": "failure-task-1"}}
    app.progress_sink = Sink()
    app._publish_skill_event(
        "skill.partial",
        {
            "parent_run_id": "failure-run-1",
            "parent_node_id": "failure-node-1",
            "skill_id": "visual.flowchart",
            "skill_call_id": "failure-call-1",
            "child_run_id": "child-failure-1",
            "artifact_ids": ["artifact-partial"],
        },
    )

    assert len(published) == 1
    assert published[0].status == "partial"
    assert published[0].artifact_id == "artifact-partial"


def test_timeout_is_failed_without_usage_or_artifact_and_cancellation_is_explicit() -> None:
    events = []

    def slow_runner(_request):
        sleep(0.12)
        return PipelineResponse(
            status="succeeded",
            pipeline="visual.flowchart",
            task_id="failure-task-1",
            run_id="failure-run-1",
            output={"late": True},
        )

    runtime = _runtime(slow_runner, events)
    timeout_policy = RunPolicy(max_model_tokens=1000, max_wall_time_ms=25)
    timed_out = runtime.invoke(_call(policy=timeout_policy), parent_context=_context(policy=timeout_policy))

    assert timed_out.status == "failed"
    assert timed_out.failure_code == "CHILD_TIMEOUT"
    assert events[-1][0] == "skill.failed"
    assert events[-1][1]["error_code"] == "CHILD_TIMEOUT"
    assert "usage" not in events[-1][1]
    assert timed_out.artifact_ids == []

    cancel_events = []
    cancel_event = Event()
    cancel_event.set()
    cancelled = _runtime(slow_runner, cancel_events).invoke(
        _call(), parent_context=_context(cancel_event=cancel_event)
    )
    assert cancelled.status == "cancelled"
    assert cancelled.failure_code == "PARENT_CANCELLED"
    assert cancel_events[-1][0] == "skill.cancelled"


def test_malformed_external_worker_responses_fail_closed_without_fake_artifact() -> None:
    client = MoneyPrinterTurboClient(
        "http://worker.test",
        transport=lambda *_args: {"data": []},
        wait_for_completion=False,
    )

    with pytest.raises(MoneyPrinterTurboError, match="data is not an object"):
        client.generate(subject="fixture")


def test_external_http_error_is_translated_and_provider_health_enters_cooldown(monkeypatch) -> None:
    def raise_http_error(*_args, **_kwargs):
        raise HTTPError("https://worker.test", 503, "unavailable", {}, None)

    monkeypatch.setattr("integrations.providers.moneyprinterturbo.client.urlopen", raise_http_error)
    client = MoneyPrinterTurboClient("http://worker.test", wait_for_completion=False)

    with pytest.raises(MoneyPrinterTurboError, match="request failed"):
        client.generate(subject="fixture")

    router = ProviderRouter(cooldown_seconds=30, clock=lambda: 100.0)
    failure_class = router.record_failure("moneyprinterturbo", "video", HTTPError(
        "https://worker.test", 503, "unavailable", {}, None
    ))
    assert failure_class == "transient"
    assert router.snapshot()[0]["status"] == "transient"


def test_failed_partial_and_degraded_outputs_cannot_enter_case_memory() -> None:
    for status in ("failed", "partial", "pending"):
        allowed, reason = can_release_to_case_memory(
            pipeline="fixture",
            output={"claim": "safe fixture"},
            quality_approved=True,
            status=status,
        )
        assert allowed is False
        assert reason

    allowed, reason = can_release_to_case_memory(
        pipeline="fixture",
        output={"claim": "safe fixture"},
        quality_approved=True,
        status="succeeded",
        is_degraded=True,
    )
    assert allowed is False
    assert "waiver" in reason.lower()
