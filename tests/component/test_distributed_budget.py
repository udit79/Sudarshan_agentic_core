from __future__ import annotations

import threading

import pytest

from pipelines.orchestrator.budget import BudgetController, BudgetExceededError
from pipelines.orchestrator.contracts import RunPolicy, UsageRecord


class FakeBudgetPlane:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.states: dict[str, dict[str, object]] = {}
        self.reservations: dict[str, dict[str, object]] = {}
        self.usage: dict[str, list[dict[str, object]]] = {}

    def usage_record(self, record):
        with self._lock:
            self.usage.setdefault(str(record["run_id"]), []).append(dict(record))

    def usage_records(self, run_id):
        with self._lock:
            return tuple(dict(item) for item in self.usage.get(str(run_id), []))

    def budget_register(self, run_id, policy):
        with self._lock:
            existing = self.states.get(run_id)
            if existing is not None:
                if existing["policy"] != dict(policy):
                    return {"error": "POLICY_CONFLICT"}
            else:
                self.states[run_id] = {
                    "policy": dict(policy),
                    "max_model_tokens": policy["max_model_tokens"],
                    "max_tool_calls": policy["max_tool_calls"],
                    "max_wall_time_ms": policy["max_wall_time_ms"],
                    "max_parallel_children": policy["max_parallel_children"],
                    "max_cost": policy.get("max_cost"),
                    "used_model_tokens": 0,
                    "reserved_model_tokens": 0,
                    "used_tool_calls": 0,
                    "reserved_tool_calls": 0,
                    "used_wall_time_ms": 0,
                    "reserved_wall_time_ms": 0,
                    "used_cost": 0.0,
                    "reserved_cost": 0.0,
                    "active_concurrency": 0,
                }
            return dict(self.states[run_id])

    def budget_reserve(self, run_id, reservation):
        with self._lock:
            state = self.states[run_id]
            if state["used_model_tokens"] + state["reserved_model_tokens"] + reservation["model_tokens"] > state["max_model_tokens"]:
                return {"error": "TOKEN_BUDGET"}
            if state["active_concurrency"] + reservation["concurrency"] > state["max_parallel_children"]:
                return {"error": "CONCURRENCY_BUDGET"}
            stored = dict(reservation)
            stored["run_id"] = run_id
            self.reservations[reservation["reservation_id"]] = stored
            state["reserved_model_tokens"] += reservation["model_tokens"]
            state["reserved_tool_calls"] += reservation["tool_calls"]
            state["reserved_wall_time_ms"] += reservation["wall_time_ms"]
            state["reserved_cost"] += reservation["cost"]
            state["active_concurrency"] += reservation["concurrency"]
            return dict(state)

    def budget_commit(self, reservation_id, usage):
        with self._lock:
            reservation = self.reservations.pop(reservation_id)
            state = self.states[reservation["run_id"]]
            model_tokens = usage["input_tokens"] + usage["output_tokens"] + (usage.get("reasoning_tokens") or 0)
            if model_tokens > reservation["model_tokens"]:
                self.reservations[reservation_id] = reservation
                return {"error": "TOKEN_RESERVATION_EXCEEDED"}
            state["reserved_model_tokens"] -= reservation["model_tokens"]
            state["reserved_tool_calls"] -= reservation["tool_calls"]
            state["reserved_wall_time_ms"] -= reservation["wall_time_ms"]
            state["reserved_cost"] -= reservation["cost"]
            state["active_concurrency"] -= reservation["concurrency"]
            state["used_model_tokens"] += model_tokens
            state["used_tool_calls"] += usage["tool_calls"]
            state["used_wall_time_ms"] += usage["latency_ms"]
            state["used_cost"] += usage.get("estimated_cost") or 0.0
            return dict(state)

    def budget_release(self, reservation_id):
        with self._lock:
            reservation = self.reservations.pop(reservation_id)
            state = self.states[reservation["run_id"]]
            state["reserved_model_tokens"] -= reservation["model_tokens"]
            state["reserved_tool_calls"] -= reservation["tool_calls"]
            state["reserved_wall_time_ms"] -= reservation["wall_time_ms"]
            state["reserved_cost"] -= reservation["cost"]
            state["active_concurrency"] -= reservation["concurrency"]
            return dict(state)

    def budget_snapshot(self, run_id):
        with self._lock:
            return dict(self.states[run_id])


def test_distributed_budget_prevents_overcommit_and_reconciles_usage():
    control = FakeBudgetPlane()
    policy = RunPolicy(max_model_tokens=256, max_tool_calls=4, max_wall_time_ms=1000, max_parallel_children=2)
    first = BudgetController(control_plane=control)
    second = BudgetController(control_plane=control)
    first.register_run("run-budget", policy)
    second.register_run("run-budget", policy)

    reservation = first.reserve("run-budget", node_id="node-1", model_tokens=256, tool_calls=2, wall_time_ms=500)
    with pytest.raises(BudgetExceededError, match="TOKEN_BUDGET"):
        second.reserve("run-budget", node_id="node-2", model_tokens=1)

    snapshot = first.commit(
        reservation.reservation_id,
        UsageRecord(
            usage_id="usage-1",
            run_id="run-budget",
            node_id="node-1",
            provider="test",
            model="test-model",
            input_tokens=100,
            output_tokens=50,
            tool_calls=1,
            latency_ms=100,
            estimated_cost=0.25,
            is_estimate=True,
        ),
    )
    assert snapshot.used_model_tokens == 150
    assert snapshot.reserved_model_tokens == 0
    assert second.snapshot("run-budget").remaining_model_tokens == 106
    report = second.reconciliation("run-budget")
    assert report["estimated_record_count"] == 1
    assert report["estimated_tokens"] == 150
    assert report["by_charge_type"]["provider"]["estimated_tokens"] == 150
    assert report["unreconciled_usage"] == ["usage-1"]
