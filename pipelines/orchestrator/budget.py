"""Hard budget reservations and provider-normalized usage accounting."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Any
from uuid import uuid4

from pipelines.orchestrator.contracts import RunPolicy, UsageRecord


class BudgetExceededError(RuntimeError):
    """A reservation or committed usage would exceed a hard run budget."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True, slots=True)
class BudgetReservation:
    reservation_id: str
    run_id: str
    node_id: str | None
    model_tokens: int
    tool_calls: int
    wall_time_ms: int
    cost: float
    concurrency: int


@dataclass(frozen=True, slots=True)
class BudgetSnapshot:
    run_id: str
    max_model_tokens: int
    used_model_tokens: int
    reserved_model_tokens: int
    max_tool_calls: int
    used_tool_calls: int
    reserved_tool_calls: int
    max_wall_time_ms: int
    used_wall_time_ms: int
    reserved_wall_time_ms: int
    max_cost: float | None
    used_cost: float
    reserved_cost: float
    max_parallel_children: int
    active_concurrency: int

    @property
    def remaining_model_tokens(self) -> int:
        return max(0, self.max_model_tokens - self.used_model_tokens - self.reserved_model_tokens)

    @property
    def remaining_tool_calls(self) -> int:
        return max(0, self.max_tool_calls - self.used_tool_calls - self.reserved_tool_calls)

    @property
    def remaining_wall_time_ms(self) -> int:
        return max(0, self.max_wall_time_ms - self.used_wall_time_ms - self.reserved_wall_time_ms)


@dataclass
class _BudgetState:
    policy: RunPolicy
    used_model_tokens: int = 0
    reserved_model_tokens: int = 0
    used_tool_calls: int = 0
    reserved_tool_calls: int = 0
    used_wall_time_ms: int = 0
    reserved_wall_time_ms: int = 0
    used_cost: float = 0.0
    reserved_cost: float = 0.0
    active_concurrency: int = 0


class BudgetController:
    """Thread-safe in-process budget ledger for one control-plane instance."""

    def __init__(self) -> None:
        self._states: dict[str, _BudgetState] = {}
        self._reservations: dict[str, BudgetReservation] = {}
        self._lock = Lock()

    def register_run(self, run_id: str, policy: RunPolicy) -> BudgetSnapshot:
        with self._lock:
            existing = self._states.get(run_id)
            if existing is not None:
                if existing.policy != policy:
                    raise BudgetExceededError("POLICY_CONFLICT", "Run already has a different budget policy")
                return self._snapshot_locked(run_id, existing)
            self._states[run_id] = _BudgetState(policy=policy)
            return self._snapshot_locked(run_id, self._states[run_id])

    def reserve(
        self,
        run_id: str,
        *,
        node_id: str | None = None,
        model_tokens: int = 0,
        tool_calls: int = 0,
        wall_time_ms: int = 0,
        cost: float = 0.0,
        concurrency: int = 1,
    ) -> BudgetReservation:
        self._validate_non_negative(model_tokens, tool_calls, wall_time_ms, cost, concurrency)
        with self._lock:
            state = self._require_locked(run_id)
            self._ensure_limit(
                state.used_model_tokens + state.reserved_model_tokens + model_tokens,
                state.policy.max_model_tokens,
                "TOKEN_BUDGET",
            )
            self._ensure_limit(
                state.used_tool_calls + state.reserved_tool_calls + tool_calls,
                state.policy.max_tool_calls,
                "TOOL_BUDGET",
            )
            self._ensure_limit(
                state.used_wall_time_ms + state.reserved_wall_time_ms + wall_time_ms,
                state.policy.max_wall_time_ms,
                "WALL_TIME_BUDGET",
            )
            if state.policy.max_cost is not None:
                self._ensure_limit(
                    state.used_cost + state.reserved_cost + cost,
                    state.policy.max_cost,
                    "COST_BUDGET",
                )
            if state.active_concurrency + concurrency > state.policy.max_parallel_children:
                raise BudgetExceededError("CONCURRENCY_BUDGET", "Parallel child budget is exhausted")
            reservation = BudgetReservation(
                reservation_id=f"budget-{uuid4().hex}",
                run_id=run_id,
                node_id=node_id,
                model_tokens=model_tokens,
                tool_calls=tool_calls,
                wall_time_ms=wall_time_ms,
                cost=cost,
                concurrency=concurrency,
            )
            self._reservations[reservation.reservation_id] = reservation
            state.reserved_model_tokens += model_tokens
            state.reserved_tool_calls += tool_calls
            state.reserved_wall_time_ms += wall_time_ms
            state.reserved_cost += cost
            state.active_concurrency += concurrency
            return reservation

    def commit(self, reservation_id: str, usage: UsageRecord) -> BudgetSnapshot:
        with self._lock:
            reservation = self._reservations.get(reservation_id)
            if reservation is None:
                raise BudgetExceededError("RESERVATION_NOT_FOUND", "Budget reservation does not exist")
            if usage.run_id != reservation.run_id:
                raise BudgetExceededError("RUN_MISMATCH", "Usage record does not belong to the reservation")
            state = self._require_locked(reservation.run_id)
            model_tokens = usage.input_tokens + usage.output_tokens + (usage.reasoning_tokens or 0)
            cost = float(usage.estimated_cost or 0.0)
            if model_tokens > reservation.model_tokens:
                raise BudgetExceededError("TOKEN_RESERVATION_EXCEEDED", "Observed model usage exceeded its reservation")
            if usage.tool_calls > reservation.tool_calls:
                raise BudgetExceededError("TOOL_RESERVATION_EXCEEDED", "Observed tool usage exceeded its reservation")
            if usage.latency_ms > reservation.wall_time_ms:
                raise BudgetExceededError("WALL_TIME_RESERVATION_EXCEEDED", "Observed latency exceeded its reservation")
            if reservation.cost > 0 and cost > reservation.cost:
                raise BudgetExceededError("COST_RESERVATION_EXCEEDED", "Observed cost exceeded its reservation")
            self._reservations.pop(reservation_id, None)
            self._release_reserved(state, reservation)
            state.used_model_tokens += model_tokens
            state.used_tool_calls += usage.tool_calls
            state.used_wall_time_ms += usage.latency_ms
            state.used_cost += cost
            return self._snapshot_locked(reservation.run_id, state)

    def release(self, reservation_id: str) -> BudgetSnapshot:
        with self._lock:
            reservation = self._reservations.pop(reservation_id, None)
            if reservation is None:
                raise BudgetExceededError("RESERVATION_NOT_FOUND", "Budget reservation does not exist")
            state = self._require_locked(reservation.run_id)
            self._release_reserved(state, reservation)
            return self._snapshot_locked(reservation.run_id, state)

    def snapshot(self, run_id: str) -> BudgetSnapshot:
        with self._lock:
            state = self._require_locked(run_id)
            return self._snapshot_locked(run_id, state)

    def usage(self, run_id: str) -> dict[str, Any]:
        snapshot = self.snapshot(run_id)
        return {
            "run_id": run_id,
            "model_tokens": {
                "used": snapshot.used_model_tokens,
                "reserved": snapshot.reserved_model_tokens,
                "remaining": snapshot.remaining_model_tokens,
                "limit": snapshot.max_model_tokens,
            },
            "tool_calls": {
                "used": snapshot.used_tool_calls,
                "reserved": snapshot.reserved_tool_calls,
                "remaining": snapshot.remaining_tool_calls,
                "limit": snapshot.max_tool_calls,
            },
            "wall_time_ms": {
                "used": snapshot.used_wall_time_ms,
                "reserved": snapshot.reserved_wall_time_ms,
                "remaining": snapshot.remaining_wall_time_ms,
                "limit": snapshot.max_wall_time_ms,
            },
            "cost": {
                "used": snapshot.used_cost,
                "reserved": snapshot.reserved_cost,
                "limit": snapshot.max_cost,
            },
            "active_concurrency": snapshot.active_concurrency,
            "max_parallel_children": snapshot.max_parallel_children,
        }

    @staticmethod
    def _validate_non_negative(*values: int | float) -> None:
        if any(value < 0 for value in values):
            raise BudgetExceededError("INVALID_BUDGET", "Budget values must be non-negative")

    @staticmethod
    def _ensure_limit(value: int | float, limit: int | float, code: str) -> None:
        if value > limit:
            raise BudgetExceededError(code, f"Requested budget exceeds the {code.lower()} limit")

    def _require_locked(self, run_id: str) -> _BudgetState:
        state = self._states.get(run_id)
        if state is None:
            raise BudgetExceededError("RUN_NOT_REGISTERED", f"Run '{run_id}' has no budget policy")
        return state

    @staticmethod
    def _release_reserved(state: _BudgetState, reservation: BudgetReservation) -> None:
        state.reserved_model_tokens -= reservation.model_tokens
        state.reserved_tool_calls -= reservation.tool_calls
        state.reserved_wall_time_ms -= reservation.wall_time_ms
        state.reserved_cost -= reservation.cost
        state.active_concurrency -= reservation.concurrency

    @staticmethod
    def _snapshot_locked(run_id: str, state: _BudgetState) -> BudgetSnapshot:
        return BudgetSnapshot(
            run_id=run_id,
            max_model_tokens=state.policy.max_model_tokens,
            used_model_tokens=state.used_model_tokens,
            reserved_model_tokens=state.reserved_model_tokens,
            max_tool_calls=state.policy.max_tool_calls,
            used_tool_calls=state.used_tool_calls,
            reserved_tool_calls=state.reserved_tool_calls,
            max_wall_time_ms=state.policy.max_wall_time_ms,
            used_wall_time_ms=state.used_wall_time_ms,
            reserved_wall_time_ms=state.reserved_wall_time_ms,
            max_cost=state.policy.max_cost,
            used_cost=state.used_cost,
            reserved_cost=state.reserved_cost,
            max_parallel_children=state.policy.max_parallel_children,
            active_concurrency=state.active_concurrency,
        )


__all__ = [
    "BudgetController",
    "BudgetExceededError",
    "BudgetReservation",
    "BudgetSnapshot",
]
