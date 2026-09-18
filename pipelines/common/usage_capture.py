"""Sanitized usage capture at the CrewAI pipeline boundary.

This module deliberately records counters and timing only.  It never stores
prompts, model output, memory text, or provider payloads.
"""

from __future__ import annotations

import os
from typing import Any, Mapping


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _model_reference(model_ref: Any) -> tuple[str, str]:
    raw = model_ref
    if raw is None or not str(raw).strip():
        raw = os.getenv("CREWAI_MODEL", "unknown")
    raw = getattr(raw, "model", raw)
    text = str(raw).strip() or "unknown"
    if "/" in text:
        provider, model = text.split("/", 1)
        return provider or "unknown", model or "unknown"
    return os.getenv("MODEL_PROVIDER", "unknown"), text


def capture_crew_usage(
    result: Any,
    *,
    run_id: str,
    pipeline: str,
    attempt: int,
    latency_ms: int,
    model_ref: Any = None,
) -> dict[str, Any]:
    """Normalize one CrewAI kickoff result into a safe usage record.

    CrewAI exposes provider-reported counters as ``usage_metrics`` on
    ``CrewOutput``.  A missing or zero-valued object is represented as
    ``usage_status=unavailable`` rather than being treated as free execution.
    ``latency_ms`` is intentionally labelled as CrewAI wall time: provider-only
    latency is not available at this boundary.
    """

    provider, model = _model_reference(model_ref)
    raw_usage = getattr(result, "usage_metrics", None)
    if callable(raw_usage):
        raw_usage = raw_usage()
    if raw_usage is None:
        raw_usage = getattr(result, "token_usage", None)
    if hasattr(raw_usage, "model_dump"):
        raw_usage = raw_usage.model_dump(mode="json")
    if not isinstance(raw_usage, Mapping):
        raw_usage = {}

    input_tokens = _int(raw_usage.get("prompt_tokens", raw_usage.get("input_tokens")))
    output_tokens = _int(raw_usage.get("completion_tokens", raw_usage.get("output_tokens")))
    reasoning_tokens = _int(raw_usage.get("reasoning_tokens"))
    cache_read_tokens = _int(
        raw_usage.get("cached_prompt_tokens", raw_usage.get("cache_read_tokens"))
    )
    cache_write_tokens = _int(
        raw_usage.get("cache_creation_tokens", raw_usage.get("cache_write_tokens"))
    )
    successful_requests = _int(raw_usage.get("successful_requests"))
    available = bool(
        input_tokens
        or output_tokens
        or reasoning_tokens
        or cache_read_tokens
        or cache_write_tokens
        or successful_requests
    )
    return {
        "usage_id": f"usage-{run_id}-{pipeline}-attempt-{max(1, attempt)}",
        "run_id": run_id,
        "attempt_id": f"{run_id}-attempt-{max(1, attempt)}",
        "pipeline": pipeline,
        "provider": provider,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "tool_calls": 0,
        "latency_ms": max(0, int(latency_ms)),
        "latency_scope": "crew_wall_time",
        "estimated_cost": None,
        "cost_status": "unavailable",
        "usage_status": "provider_reported" if available else "unavailable",
        "is_estimate": not available,
        "provider_request_id": None,
        "provider_fields": {"source": "crewai.CrewOutput.token_usage"},
    }


def aggregate_crew_usage(records: list[dict[str, Any]], *, run_id: str, pipeline: str) -> dict[str, Any]:
    """Aggregate attempt records once for the pipeline response boundary."""

    if not records:
        return capture_crew_usage(
            None,
            run_id=run_id,
            pipeline=pipeline,
            attempt=1,
            latency_ms=0,
        ) | {
            "usage_id": f"usage-{run_id}-{pipeline}",
            "attempt_id": None,
        }
    numeric = (
        "input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "tool_calls",
        "latency_ms",
    )
    aggregate = {key: sum(_int(record.get(key)) for record in records) for key in numeric}
    available = any(record.get("usage_status") == "provider_reported" for record in records)
    provider = next((str(record.get("provider")) for record in records if record.get("provider")), "unknown")
    model = next((str(record.get("model")) for record in records if record.get("model")), "unknown")
    return {
        "usage_id": f"usage-{run_id}-{pipeline}",
        "run_id": run_id,
        "attempt_id": None,
        "pipeline": pipeline,
        "provider": provider,
        "model": model,
        **aggregate,
        "latency_scope": "crew_wall_time",
        "estimated_cost": None,
        "cost_status": "unavailable",
        "usage_status": "provider_reported" if available else "unavailable",
        "is_estimate": not available,
        "provider_request_id": None,
        "provider_fields": {"source": "crewai.CrewOutput.token_usage", "attempt_count": len(records)},
    }


__all__ = ["aggregate_crew_usage", "capture_crew_usage"]
