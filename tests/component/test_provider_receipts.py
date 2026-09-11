from __future__ import annotations

from integrations.providers.receipts import classify_provider_error, normalize_provider_response


def test_provider_receipt_normalizes_compatible_usage_without_raw_payload():
    receipt = normalize_provider_response(
        "deepseek",
        {
            "id": "request-1",
            "model": "deepseek-chat",
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 7,
                "prompt_cache_hit_tokens": 3,
            },
            "finish_reason": "stop",
            "secret_prompt": "must not survive",
        },
        latency_ms=42,
    )
    assert receipt.request_id == "request-1"
    assert receipt.input_tokens == 10
    assert receipt.output_tokens == 7
    assert receipt.cache_read_tokens == 3
    assert receipt.is_estimate is False
    assert "secret_prompt" not in receipt.provider_fields
    usage = receipt.to_usage_record(usage_id="u-1", run_id="run-1")
    assert usage.provider_request_id == "request-1"
    assert usage.finish_reason == "stop"


def test_provider_errors_have_distinct_retry_classes():
    assert classify_provider_error(TimeoutError("deadline exceeded")) == "timeout"
    assert classify_provider_error(RuntimeError("429 rate limit")) == "rate_limit"
    assert classify_provider_error(RuntimeError("insufficient_quota: exceeded your current quota")) == "quota_exhausted"
    assert classify_provider_error(PermissionError("unauthorized")) == "auth"
    assert classify_provider_error(ValueError("bad request")) == "invalid_request"
