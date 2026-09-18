from __future__ import annotations

from types import SimpleNamespace

from pipelines.common.task_state import TaskState
from pipelines.common.text_generation import TextTransformationFlow
from pipelines.orchestrator.spend_guard import ProviderSpendGuard, usage_tokens


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
