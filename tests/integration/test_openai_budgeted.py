"""Opt-in real OpenAI smoke test with a hard local budget."""

from __future__ import annotations

import os
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import pytest
from dotenv import load_dotenv
from openai import OpenAI

from integrations.providers.router import ProviderRouter
from pipelines.orchestrator.budget import BudgetController
from pipelines.orchestrator.contracts import RunPolicy, UsageRecord


load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

_LIVE = os.getenv("RUN_LIVE_PROVIDER_TESTS", "").lower() in {"1", "true", "yes"}
_HAS_KEY = bool(os.getenv("OPENAI_API_KEY", "").strip())


@pytest.mark.skipif(
    not (_LIVE and _HAS_KEY),
    reason="live provider tests are opt-in; set RUN_LIVE_PROVIDER_TESTS=1 with OPENAI_API_KEY",
)
def test_real_openai_text_path_is_budgeted_and_records_observed_usage() -> None:
    run_id = f"live-openai-{uuid4().hex}"
    budget = BudgetController()
    budget.register_run(
        run_id,
        RunPolicy(
            max_model_tokens=256,
            max_tool_calls=0,
            max_wall_time_ms=30_000,
            max_cost=0.25,
            max_parallel_children=1,
        ),
    )
    reservation = budget.reserve(
        run_id,
        node_id="openai-text-smoke",
        model_tokens=256,
        wall_time_ms=30_000,
        cost=0.25,
    )
    committed = False
    started = perf_counter()
    try:
        route = ProviderRouter().select_model("text")
        assert route.provider == "openai"
        model = route.model.removeprefix("openai/")
        response = OpenAI(timeout=20).responses.create(
            model=model,
            input="Return exactly the word OK.",
            max_output_tokens=16,
        )
        usage = response.usage
        assert usage is not None
        output_details = getattr(usage, "output_tokens_details", None)
        receipt = UsageRecord(
            usage_id=f"usage-{uuid4().hex}",
            run_id=run_id,
            node_id="openai-text-smoke",
            provider=route.provider,
            model=model,
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            reasoning_tokens=int(getattr(output_details, "reasoning_tokens", 0) or 0),
            latency_ms=int((perf_counter() - started) * 1000),
            estimated_cost=None,
            is_estimate=False,
            provider_request_id=getattr(response, "id", None),
        )
        snapshot = budget.commit(reservation.reservation_id, receipt)
        committed = True
        assert snapshot.reserved_model_tokens == 0
        assert snapshot.used_model_tokens <= 256
        assert budget.reconciliation(run_id)["observed_record_count"] == 1
    finally:
        if not committed:
            budget.release(reservation.reservation_id)
