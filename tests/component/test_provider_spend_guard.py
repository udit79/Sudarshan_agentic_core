from __future__ import annotations

from types import SimpleNamespace

from pipelines.common.task_state import TaskState
from pipelines.common.text_generation import TextTransformationFlow
from pipelines.orchestrator.spend_guard import (
    ProviderSpendGuard,
    approximate_token_count,
    bound_text,
    output_tokens_per_call,
    usage_tokens,
)


def test_provider_spend_guard_denies_retry_after_observed_cap() -> None:
    guard = ProviderSpendGuard(max_tokens=1200)

    assert guard.admit_attempt() is True
    assert guard.record(1400) is True
    assert guard.remaining_tokens == 0
    assert guard.admit_attempt() is False


def test_provider_spend_guard_denies_unbudgeted_retry_even_before_overage() -> None:
    guard = ProviderSpendGuard(max_tokens=1200, max_attempts=1)

    assert guard.admit_attempt() is True
    assert guard.record(200) is False
    assert guard.admit_attempt() is False


def test_provider_spend_guard_allows_unlimited_mode_only_when_no_cap_is_set() -> None:
    guard = ProviderSpendGuard()

    assert guard.admit_attempt() is True
    assert guard.record(50) is False
    assert guard.admit_attempt() is True
    assert guard.used_tokens == 50


def test_text_flow_stops_before_a_retry_when_the_guard_is_exhausted() -> None:
    state = TaskState(
        run_id="run-budget",
        pipeline_name="executive_summary",
        attempt=1,
        max_attempts=2,
        provider_budget_exceeded=True,
    )
    flow = SimpleNamespace(
        state=state,
        _spend_guard=ProviderSpendGuard(max_tokens=1200, used_tokens=1400, attempts=1, exceeded=True),
    )

    result = TextTransformationFlow._run_crew(flow)

    assert result.error is not None
    assert "PROVIDER_TOKEN_BUDGET_EXCEEDED" in result.error
    assert state.attempt == 1
    assert TextTransformationFlow.route_validation(flow) == "failed"


def test_usage_token_sum_uses_only_sanitized_counters() -> None:
    assert usage_tokens({
        "input_tokens": 100,
        "output_tokens": 40,
        "reasoning_tokens": 5,
        "raw_prompt": "must not be inspected",
    }) == 145


def test_prompt_bound_is_deterministic_and_preserves_both_ends() -> None:
    source = "BEGIN-" + ("x" * 5000) + "-END"

    bounded = bound_text(source, 40)

    assert approximate_token_count(bounded) <= 40
    assert bounded.startswith("BEGIN-")
    assert bounded.endswith("-END")
    assert "bounded for provider budget" in bounded


def test_output_cap_is_allocated_across_the_current_agent_count() -> None:
    assert output_tokens_per_call(1200) == 240
    assert output_tokens_per_call(1200, call_count=3) == 400
    assert output_tokens_per_call(256, call_count=1000) == 1


def test_text_flow_bounds_dynamic_inputs_only_when_provider_budget_is_explicit() -> None:
    state = TaskState(
        provider_token_budget=1200,
        pipeline_options={"provider_input_token_budget": 1000},
        query="q" * 2000,
        memory_context="m" * 8000,
        prompt_plan={"plan": "p" * 3000},
        request_understanding={"understanding": "u" * 3000},
    )
    flow = SimpleNamespace(state=state)

    bounded = TextTransformationFlow._crew_inputs(flow, "f" * 3000)

    assert len(bounded["memory_context"]) < len(state.memory_context)
    assert len(bounded["query"]) < len(state.query)
    assert "bounded for provider budget" in bounded["memory_context"]


def test_text_flow_keeps_default_inputs_unchanged_without_provider_budget() -> None:
    state = TaskState(query="q" * 2000, memory_context="m" * 8000)
    flow = SimpleNamespace(state=state)

    inputs = TextTransformationFlow._crew_inputs(flow, "feedback")

    assert inputs["query"] == state.query
    assert inputs["memory_context"] == state.memory_context
