"""Sanitized benchmark records for real-case and holdout evaluation.

This module deliberately accepts already-projected status, telemetry, and
observability mappings. It never receives prompts, raw memory, credentials,
or provider response bodies. Missing measurements stay ``None`` instead of
being reported as zero.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field


class BenchmarkTokens(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: int | None = Field(default=None, ge=0)
    estimated: int | None = Field(default=None, ge=0)
    reconciled: int | None = Field(default=None, ge=0)


class BenchmarkCache(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hit: bool | None = None
    misses: int | None = Field(default=None, ge=0)
    waits: int | None = Field(default=None, ge=0)


class BenchmarkArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(min_length=1)
    sha256: str | None = None


class BenchmarkRecord(BaseModel):
    """One safe row suitable for JSONL storage and later charting."""

    model_config = ConfigDict(extra="forbid")

    case: str = Field(min_length=1)
    pipeline: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    quality_status: str | None = None
    degraded: bool | None = None
    admission_ms: int | None = Field(default=None, ge=0)
    wall_ms: int | None = Field(default=None, ge=0)
    queue_ms: int | None = Field(default=None, ge=0)
    provider_ms: int | None = Field(default=None, ge=0)
    attempts: int | None = Field(default=None, ge=0)
    tokens: BenchmarkTokens = Field(default_factory=BenchmarkTokens)
    cache: BenchmarkCache = Field(default_factory=BenchmarkCache)
    artifacts: list[BenchmarkArtifact] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    measurement_notes: list[str] = Field(default_factory=list)


def _timestamp_ms(value: Any) -> int | None:
    if isinstance(value, (int, float)):
        return max(0, round(float(value) * 1000))
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return round(parsed.timestamp() * 1000)


def _duration_ms(start: Any, end: Any) -> int | None:
    started = _timestamp_ms(start)
    finished = _timestamp_ms(end)
    if started is None or finished is None:
        return None
    return max(0, finished - started)


def _response(status: Mapping[str, Any]) -> Mapping[str, Any]:
    response = status.get("response")
    if isinstance(response, Mapping):
        return response
    responses = status.get("responses")
    if isinstance(responses, Mapping):
        for candidate in responses.values():
            if isinstance(candidate, Mapping):
                return candidate
    return {}


def _quality_status(status: Mapping[str, Any], response: Mapping[str, Any]) -> str | None:
    for source in (status, response, response.get("metadata", {})):
        if not isinstance(source, Mapping):
            continue
        for key in ("quality_status", "quality_state"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        quality = source.get("quality_report")
        if isinstance(quality, Mapping) and isinstance(quality.get("status"), str):
            return str(quality["status"])
    return None


def _issues(status: Mapping[str, Any], response: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for source in (status, response, response.get("metadata", {})):
        if not isinstance(source, Mapping):
            continue
        for key in ("error", "failure", "error_code"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                values.append(value.strip()[:500])
        quality = source.get("quality_review")
        if isinstance(quality, Mapping):
            for key in ("issues", "required_revisions"):
                entries = quality.get(key)
                if isinstance(entries, list):
                    values.extend(str(item).strip()[:500] for item in entries if str(item).strip())
    return list(dict.fromkeys(values))


def _artifacts(status: Mapping[str, Any], response: Mapping[str, Any]) -> list[BenchmarkArtifact]:
    candidates: list[Any] = []
    for source in (status, response):
        if not isinstance(source, Mapping):
            continue
        value = source.get("artifacts")
        if isinstance(value, list):
            candidates.extend(value)
        value = source.get("artifact")
        if isinstance(value, Mapping):
            candidates.append(value)
    result: list[BenchmarkArtifact] = []
    seen: set[str] = set()
    for item in candidates:
        if not isinstance(item, Mapping):
            continue
        artifact_id = item.get("artifact_id") or item.get("id")
        if not isinstance(artifact_id, str) or not artifact_id.strip():
            continue
        artifact_id = artifact_id.strip()
        if artifact_id in seen:
            continue
        seen.add(artifact_id)
        checksum = item.get("sha256") or item.get("checksum")
        result.append(BenchmarkArtifact(
            artifact_id=artifact_id,
            sha256=str(checksum).strip() if checksum else None,
        ))
    return result


def build_benchmark_record(
    *,
    case: str,
    pipeline: str,
    run_id: str,
    status: Mapping[str, Any],
    telemetry: Mapping[str, Any],
    events: list[Mapping[str, Any]] | None = None,
    admission_ms: int | None = None,
) -> BenchmarkRecord:
    """Build a benchmark row from sanitized API projections only."""

    response = _response(status)
    event_rows = events or []
    notes: list[str] = []

    wall_ms = status.get("wall_ms")
    if not isinstance(wall_ms, (int, float)):
        wall_ms = _duration_ms(status.get("started_at"), status.get("finished_at"))
    queue_ms = status.get("queue_ms")
    if not isinstance(queue_ms, (int, float)):
        queue_ms = _duration_ms(status.get("queued_at"), status.get("started_at"))

    provider_ms: int | None = None
    for event in event_rows:
        usage = event.get("usage") if isinstance(event, Mapping) else None
        if not isinstance(usage, Mapping):
            continue
        if str(usage.get("latency_scope", "")).strip().lower() == "provider":
            provider_ms = (provider_ms or 0) + max(0, int(usage.get("latency_ms", 0) or 0))
    if provider_ms is None:
        notes.append("provider_ms unavailable; recorded CrewAI or harness wall time is not provider-only latency")

    input_tokens = telemetry.get("input_tokens")
    output_tokens = telemetry.get("output_tokens")
    reasoning_tokens = telemetry.get("reasoning_tokens")
    measured_tokens: int | None = None
    if any(isinstance(value, (int, float)) and value > 0 for value in (input_tokens, output_tokens, reasoning_tokens)):
        measured_tokens = sum(max(0, int(value or 0)) for value in (input_tokens, output_tokens, reasoning_tokens))
    # The existing aggregate flag may be true because cost is unavailable,
    # even when input/output counters came directly from the provider. Keep
    # token truth separate; callers may explicitly mark token estimates.
    tokens_are_estimate = bool(telemetry.get("tokens_are_estimate", False))
    tokens = BenchmarkTokens(
        provider=None if measured_tokens is None else measured_tokens,
        estimated=measured_tokens if tokens_are_estimate else None,
        reconciled=None,
    )
    if telemetry.get("estimated_cost") in (None, ""):
        notes.append("cost unavailable; no pricing or billing reconciliation was supplied")

    cache_hits = telemetry.get("cache_hits")
    cache_misses = telemetry.get("cache_misses")
    cache_waits = telemetry.get("cache_waits")
    cache_observed = any(isinstance(value, (int, float)) and value > 0 for value in (cache_hits, cache_misses, cache_waits))
    cache = BenchmarkCache(
        hit=bool(cache_hits) if cache_observed else None,
        misses=max(0, int(cache_misses)) if isinstance(cache_misses, (int, float)) and cache_observed else None,
        waits=max(0, int(cache_waits)) if isinstance(cache_waits, (int, float)) and cache_observed else None,
    )
    if not cache_observed:
        notes.append("cache behavior not exercised or not distinguishable from zero")

    attempts = status.get("attempts") or response.get("attempts")
    quality_status = _quality_status(status, response)
    final_status = str(status.get("status") or response.get("status") or "unknown")
    degraded = status.get("degraded")
    if degraded is None:
        degraded = final_status in {"partial", "degraded"}

    return BenchmarkRecord(
        case=case,
        pipeline=pipeline,
        run_id=run_id,
        status=final_status,
        quality_status=quality_status,
        degraded=bool(degraded),
        admission_ms=admission_ms,
        wall_ms=max(0, round(float(wall_ms))) if isinstance(wall_ms, (int, float)) else None,
        queue_ms=max(0, round(float(queue_ms))) if isinstance(queue_ms, (int, float)) else None,
        provider_ms=provider_ms,
        attempts=max(0, int(attempts)) if isinstance(attempts, (int, float)) else None,
        tokens=tokens,
        cache=cache,
        artifacts=_artifacts(status, response),
        issues=_issues(status, response),
        measurement_notes=notes,
    )


__all__ = ["BenchmarkArtifact", "BenchmarkCache", "BenchmarkRecord", "BenchmarkTokens", "build_benchmark_record"]
