"""Provider-neutral receipts and retry classification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from pipelines.orchestrator.contracts import UsageRecord


@dataclass(frozen=True, slots=True)
class ProviderReceipt:
    provider: str
    model: str
    request_id: str | None
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int | None
    cache_read_tokens: int
    cache_write_tokens: int
    media_units: float | None
    finish_reason: str | None
    retry_after_seconds: float | None
    latency_ms: int
    is_estimate: bool
    provider_fields: dict[str, Any]

    def to_usage_record(self, *, usage_id: str, run_id: str, node_id: str | None = None, estimated_cost: float | None = None) -> UsageRecord:
        # Keep provider receipt imports lightweight; orchestrator contracts
        # import provider-aware runtime modules during application startup.
        from pipelines.orchestrator.contracts import UsageRecord

        return UsageRecord(
            usage_id=usage_id,
            run_id=run_id,
            node_id=node_id,
            provider=self.provider,
            model=self.model,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            reasoning_tokens=self.reasoning_tokens,
            cache_read_tokens=self.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens,
            latency_ms=self.latency_ms,
            estimated_cost=estimated_cost,
            is_estimate=self.is_estimate,
            provider_request_id=self.request_id,
            media_units=self.media_units,
            finish_reason=self.finish_reason,
            retry_after_seconds=self.retry_after_seconds,
            provider_fields=self.provider_fields,
        )


def normalize_provider_response(
    provider: str,
    response: Mapping[str, Any] | None,
    *,
    model: str | None = None,
    latency_ms: int = 0,
) -> ProviderReceipt:
    """Map common OpenAI/DeepSeek-compatible fields and preserve safe extras."""

    raw = dict(response or {})
    usage = raw.get("usage") if isinstance(raw.get("usage"), Mapping) else raw
    usage = dict(usage)
    request_id = _first(raw, "request_id", "requestId", "id")
    finish_reason = _first(raw, "finish_reason", "finishReason")
    retry_after = _number(_first(raw, "retry_after_seconds", "retry_after", "retryAfter"))
    common = {
        "provider": str(provider or "unknown"),
        "model": str(model or raw.get("model") or "unknown"),
        "request_id": request_id,
        "input_tokens": _int(usage.get("input_tokens", usage.get("prompt_tokens", 0))),
        "output_tokens": _int(usage.get("output_tokens", usage.get("completion_tokens", 0))),
        "reasoning_tokens": _optional_int(usage.get("reasoning_tokens")),
        "cache_read_tokens": _int(usage.get("cache_read_tokens", usage.get("prompt_cache_hit_tokens", 0))),
        "cache_write_tokens": _int(usage.get("cache_write_tokens", usage.get("prompt_cache_miss_tokens", 0))),
        "media_units": _number(usage.get("media_units", usage.get("seconds"))),
        "finish_reason": finish_reason,
        "retry_after_seconds": retry_after,
        "latency_ms": max(0, int(latency_ms)),
        "is_estimate": not any(key in usage for key in ("input_tokens", "prompt_tokens", "output_tokens", "completion_tokens")),
    }
    safe_fields = {
        str(key): value for key, value in raw.items()
        if str(key) in {"model", "system_fingerprint", "service_tier", "media_type", "provider_request_id"}
        and isinstance(value, (str, int, float, bool))
    }
    return ProviderReceipt(**common, provider_fields=safe_fields)


def classify_provider_error(error: Exception) -> str:
    message = f"{type(error).__name__}: {error}".lower()
    if any(marker in message for marker in ("authentication", "unauthorized", "forbidden", "invalid api key")):
        return "auth"
    if any(marker in message for marker in (
        "insufficient_quota",
        "quota_exhausted",
        "insufficient quota",
        "exceeded your current quota",
        "quota exceeded",
        "billing hard limit",
        "out of credits",
        "no credits",
    )):
        return "quota_exhausted"
    if any(marker in message for marker in ("429", "rate limit", "too many requests", "retry-after")):
        return "rate_limit"
    if any(marker in message for marker in ("timeout", "timed out", "deadline")):
        return "timeout"
    if any(marker in message for marker in ("connection", "temporarily", "503", "502", "unavailable")):
        return "transient"
    return "invalid_request" if isinstance(error, ValueError) else "unknown"


def _first(value: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        current = value.get(key)
        if current is not None and str(current).strip():
            return str(current).strip()
    return None


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _optional_int(value: Any) -> int | None:
    return None if value is None else _int(value)


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None


__all__ = ["ProviderReceipt", "classify_provider_error", "normalize_provider_response"]
