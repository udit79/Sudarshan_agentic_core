from __future__ import annotations

import pytest

from pipelines.orchestrator.budget import BudgetController, BudgetExceededError
from pipelines.orchestrator.contracts import RunPolicy, UsageRecord


def usage(run_id: str, *, node_id: str = "node-1") -> UsageRecord:
    return UsageRecord(
        usage_id="usage-1",
        run_id=run_id,
        node_id=node_id,
        provider="test",
        model="test-model",
        input_tokens=100,
        output_tokens=50,
        tool_calls=1,
        latency_ms=100,
        estimated_cost=0.25,
        is_estimate=True,
    )


def test_budget_reservation_commit_and_usage_projection() -> None:
    controller = BudgetController()
    controller.register_run(
        "run-1",
        RunPolicy(max_model_tokens=1000, max_tool_calls=4, max_wall_time_ms=1000, max_cost=1.0, max_parallel_children=2),
    )
    reservation = controller.reserve(
        "run-1",
        node_id="node-1",
        model_tokens=500,
        tool_calls=2,
        wall_time_ms=500,
        cost=0.5,
    )
    reserved = controller.snapshot("run-1")
    assert reserved.remaining_model_tokens == 500
    assert reserved.active_concurrency == 1

    committed = controller.commit(reservation.reservation_id, usage("run-1"))
    assert committed.used_model_tokens == 150
    assert committed.used_tool_calls == 1
    assert committed.used_cost == 0.25
    assert controller.usage("run-1")["model_tokens"]["remaining"] == 850


def test_budget_rejects_overcommit_and_releases_unused_reservations() -> None:
    controller = BudgetController()
    controller.register_run("run-2", RunPolicy(max_model_tokens=256, max_parallel_children=1))
    reservation = controller.reserve("run-2", model_tokens=256)
    with pytest.raises(BudgetExceededError, match="TOKEN_BUDGET"):
        controller.reserve("run-2", model_tokens=1)
    controller.release(reservation.reservation_id)
    assert controller.snapshot("run-2").remaining_model_tokens == 256


def test_budget_rejects_usage_larger_than_reservation_without_negative_totals() -> None:
    controller = BudgetController()
    controller.register_run("run-3", RunPolicy(max_model_tokens=1000, max_tool_calls=4, max_wall_time_ms=1000))
    reservation = controller.reserve("run-3", model_tokens=100, tool_calls=1, wall_time_ms=100)
    oversized = UsageRecord(
        usage_id="usage-oversized",
        run_id="run-3",
        provider="test",
        model="test-model",
        input_tokens=101,
    )
    with pytest.raises(BudgetExceededError, match="TOKEN_RESERVATION_EXCEEDED"):
        controller.commit(reservation.reservation_id, oversized)
    assert controller.snapshot("run-3").reserved_model_tokens == 100
    controller.release(reservation.reservation_id)
