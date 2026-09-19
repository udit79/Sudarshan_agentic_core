"""Offline proof for provider-usage and latency capture at pipeline boundary."""

from types import SimpleNamespace

from pipelines.common.usage_capture import aggregate_crew_usage, capture_crew_usage, capture_task_usage
from pipelines.orchestrator.graph import _response_usage


def test_crew_output_usage_is_normalized_without_raw_content() -> None:
    result = SimpleNamespace(
        usage_metrics={
            "prompt_tokens": 120,
            "completion_tokens": 45,
            "reasoning_tokens": 9,
            "cached_prompt_tokens": 12,
            "successful_requests": 3,
        },
        raw="DO NOT STORE THIS MODEL OUTPUT",
    )

    usage = capture_crew_usage(
        result,
        run_id="run-usage-1",
        pipeline="executive_summary",
        attempt=1,
        latency_ms=812,
        model_ref="openai/gpt-test",
    )

    assert usage["provider"] == "openai"
    assert usage["model"] == "gpt-test"
    assert usage["input_tokens"] == 120
    assert usage["output_tokens"] == 45
    assert usage["reasoning_tokens"] == 9
    assert usage["latency_ms"] == 812
    assert usage["latency_scope"] == "crew_wall_time"
    assert usage["usage_status"] == "provider_reported"
    assert usage["estimated_cost"] is None
    assert "DO NOT STORE" not in str(usage)


def test_retry_attempts_are_aggregated_once_at_pipeline_boundary() -> None:
    records = [
        capture_crew_usage(
            SimpleNamespace(usage_metrics={"prompt_tokens": 100, "completion_tokens": 20}),
            run_id="run-usage-2",
            pipeline="executive_summary",
            attempt=1,
            latency_ms=500,
            model_ref="openai/gpt-test",
        ),
        capture_crew_usage(
            SimpleNamespace(usage_metrics={"prompt_tokens": 110, "completion_tokens": 25}),
            run_id="run-usage-2",
            pipeline="executive_summary",
            attempt=2,
            latency_ms=700,
            model_ref="openai/gpt-test",
        ),
    ]

    aggregate = aggregate_crew_usage(records, run_id="run-usage-2", pipeline="executive_summary")

    assert aggregate["usage_id"] == "usage-run-usage-2-executive_summary"
    assert aggregate["input_tokens"] == 210
    assert aggregate["output_tokens"] == 45
    assert aggregate["latency_ms"] == 1200
    assert aggregate["provider_fields"]["attempt_count"] == 2
    assert aggregate["estimated_cost"] is None


def test_missing_provider_usage_is_explicitly_unavailable() -> None:
    usage = capture_crew_usage(
        None,
        run_id="run-usage-3",
        pipeline="executive_summary",
        attempt=1,
        latency_ms=321,
        model_ref="openai/gpt-test",
    )

    assert usage["usage_status"] == "unavailable"
    assert usage["is_estimate"] is True
    assert usage["latency_ms"] == 321
    assert usage["estimated_cost"] is None


def test_task_usage_is_captured_per_stage_without_raw_output() -> None:
    usage = capture_task_usage(
        SimpleNamespace(
            usage_metrics={
                "prompt_tokens": 310,
                "completion_tokens": 90,
                "reasoning_tokens": 12,
                "cached_prompt_tokens": 40,
            },
            raw="DO NOT STORE THIS TASK OUTPUT",
        ),
        stage="executive_summary_writer",
    )

    assert usage["stage"] == "executive_summary_writer"
    assert usage["input_tokens"] == 310
    assert usage["output_tokens"] == 90
    assert usage["reasoning_tokens"] == 12
    assert usage["cache_read_tokens"] == 40
    assert usage["usage_status"] == "provider_reported"
    assert "DO NOT STORE" not in str(usage)


def test_response_usage_uses_existing_safe_telemetry_contract() -> None:
    usage, usage_id = _response_usage({
        "metadata": {
            "usage": {
                "usage_id": "usage-run-4-executive_summary",
                "provider": "openai",
                "model": "gpt-test",
                "input_tokens": 30,
                "output_tokens": 10,
                "reasoning_tokens": 4,
                "latency_ms": 900,
                "estimated_cost": None,
                "usage_status": "provider_reported",
            }
        }
    })

    assert usage is not None
    assert usage_id == "usage-run-4-executive_summary"
    assert usage.input_tokens == 30
    assert usage.output_tokens == 10
    assert usage.reasoning_tokens == 4
    assert usage.latency_ms == 900
    assert usage.is_estimate is True  # cost is still unavailable
