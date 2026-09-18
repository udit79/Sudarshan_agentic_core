from __future__ import annotations

from types import SimpleNamespace

from pipelines.common.task_state import TaskState
from pipelines.common.text_generation import TextTransformationFlow
from pipelines.orchestrator.spend_guard import (
    ProviderSpendGuard,
    TokenBudgetReservation,
    approximate_token_count,
    bound_text,
    declared_provider_reservation,
    output_tokens_per_call,
    usage_tokens,
)


class _PreflightHarness(SimpleNamespace):
    def _reject_preflight(self, reason: str) -> bool:
        return TextTransformationFlow._reject_preflight(self, reason)

    def _preflight_provider_budget(self) -> bool:
        return TextTransformationFlow._preflight_provider_budget(self)


def _preflight_harness(state: TaskState) -> _PreflightHarness:
    return _PreflightHarness(
        state=state,
        _preflight_reservation=None,
        _preflight_reserved_tokens=0,
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


def test_token_budget_reservation_rejects_a_projected_overage_before_execution() -> None:
    ledger = TokenBudgetReservation(max_tokens=1000)

    assert ledger.reserve(700) is True
    assert ledger.remaining_tokens == 300
    assert ledger.reserve(301) is False
    assert ledger.reservation_blocked is True
    assert ledger.used_tokens == 0


def test_token_budget_reservation_reconciles_actual_usage_without_double_counting() -> None:
    ledger = TokenBudgetReservation(max_tokens=1000)

    assert ledger.reserve(700) is True
    assert ledger.reconcile(700, 420) is True
    assert ledger.used_tokens == 420
    assert ledger.reserved_tokens == 0
    assert ledger.remaining_tokens == 580


def test_token_budget_reservation_fails_closed_when_actual_usage_exceeds_cap() -> None:
    ledger = TokenBudgetReservation(max_tokens=1000)

    assert ledger.reserve(900) is True
    assert ledger.reconcile(900, 1100) is False
    assert ledger.exceeded is True
    assert ledger.remaining_tokens == 0


def test_token_budget_reservation_does_not_store_sensitive_inputs() -> None:
    ledger = TokenBudgetReservation(max_tokens=1000)

    assert ledger.reserve(250) is True
    representation = repr(ledger)

    assert "prompt" not in representation.lower()
    assert "memory" not in representation.lower()
    assert "secret" not in representation.lower()


def test_declared_provider_reservation_is_deterministic() -> None:
    assert declared_provider_reservation(
        input_tokens_per_call=900,
        output_tokens_per_call=600,
        provider_call_count=4,
    ) == 6000


def test_text_flow_preflight_requires_an_explicit_pipeline_profile() -> None:
    state = TaskState(
        provider_token_budget=6000,
        pipeline_options={"provider_budget_preflight": True},
    )
    flow = _preflight_harness(state)

    assert TextTransformationFlow._preflight_provider_budget(flow) is False
    assert state.provider_budget_exceeded is True
    assert "PROVIDER_BUDGET_PREFLIGHT_REJECTED" in (state.failure or "")


def test_text_flow_preflight_reserves_a_declared_profile() -> None:
    state = TaskState(
        provider_token_budget=6000,
        pipeline_options={
            "provider_budget_preflight": True,
            "provider_input_token_budget": 900,
            "provider_output_token_budget": 600,
            "provider_call_count": 4,
        },
    )
    flow = _preflight_harness(state)

    assert TextTransformationFlow._preflight_provider_budget(flow) is True
    assert flow._preflight_reserved_tokens == 6000
    assert flow._preflight_reservation.remaining_tokens == 0


def test_text_flow_preflight_rejects_a_profile_before_provider_execution() -> None:
    state = TaskState(
        provider_token_budget=5000,
        pipeline_options={
            "provider_budget_preflight": True,
            "provider_input_token_budget": 900,
            "provider_output_token_budget": 600,
            "provider_call_count": 4,
        },
    )
    flow = _preflight_harness(state)

    assert TextTransformationFlow._preflight_provider_budget(flow) is False
    assert flow._preflight_reservation is None
    assert state.provider_budget_exceeded is True


def test_text_flow_keeps_preflight_disabled_by_default() -> None:
    state = TaskState(provider_token_budget=6000, pipeline_options={})
    flow = _preflight_harness(state)

    assert TextTransformationFlow._preflight_provider_budget(flow) is True
    assert flow._preflight_reservation is None


def test_text_flow_stops_before_a_retry_when_the_guard_is_exhausted() -> None:
    state = TaskState(
        run_id="run-budget",
        pipeline_name="executive_summary",
        attempt=1,
        max_attempts=2,
        provider_budget_exceeded=True,
    )
    flow = _PreflightHarness(
        state=state,
        _spend_guard=ProviderSpendGuard(max_tokens=1200, used_tokens=1400, attempts=1, exceeded=True),
        _preflight_reservation=None,
        _preflight_reserved_tokens=0,
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


def test_budgeted_gpt5_request_uses_provider_native_completion_token_parameter(monkeypatch) -> None:
    monkeypatch.setenv("CREWAI_MODEL", "openai/gpt-5.4")
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-no-network-key")
    flow = SimpleNamespace(
        state=TaskState(provider_token_budget=1200),
        llm=None,
    )

    llm = TextTransformationFlow._budgeted_llm(flow)
    params = llm._prepare_completion_params("test")

    assert params["max_completion_tokens"] == 240
    assert "max_tokens" not in params


def test_budgeted_non_gpt5_request_keeps_legacy_max_tokens(monkeypatch) -> None:
    monkeypatch.setenv("CREWAI_MODEL", "openai/gpt-4o-mini")
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-no-network-key")
    flow = SimpleNamespace(
        state=TaskState(provider_token_budget=1200),
        llm=None,
    )

    llm = TextTransformationFlow._budgeted_llm(flow)
    params = llm._prepare_completion_params("test")

    assert params["max_tokens"] == 240
    assert "max_completion_tokens" not in params


def test_pipeline_can_declare_a_contract_specific_completion_budget(monkeypatch) -> None:
    monkeypatch.setenv("CREWAI_MODEL", "openai/gpt-5.4")
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-no-network-key")
    flow = SimpleNamespace(
        state=TaskState(
            provider_token_budget=6000,
            pipeline_options={"provider_output_token_budget": 2400},
        ),
        llm=None,
    )

    llm = TextTransformationFlow._budgeted_llm(flow)
    params = llm._prepare_completion_params("test")

    assert params["max_completion_tokens"] == 2400
    assert "max_tokens" not in params
