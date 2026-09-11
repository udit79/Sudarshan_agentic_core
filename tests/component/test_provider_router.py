from __future__ import annotations

import pytest

from integrations.providers.router import ProviderRouter, ProviderUnavailableError


def test_provider_router_opens_cooldown_for_quota_and_blocks_repeat_calls() -> None:
    now = [100.0]
    router = ProviderRouter(cooldown_seconds=30, clock=lambda: now[0])

    assert router.select_model("image").model == "gpt-image-1"
    assert router.record_failure("openai", "image", RuntimeError("insufficient_quota")) == "quota_exhausted"

    with pytest.raises(ProviderUnavailableError) as caught:
        router.before_call("openai", "image")
    assert caught.value.failure_class == "quota_exhausted"
    assert caught.value.retry_after_seconds == 30
    assert router.snapshot()[0]["status"] == "quota_exhausted"

    now[0] = 131.0
    router.before_call("openai", "image")


def test_provider_router_success_resets_health() -> None:
    router = ProviderRouter(cooldown_seconds=30)
    router.record_failure("openai", "tts", RuntimeError("503 unavailable"))
    router.record_success("openai", "tts")
    state = router.snapshot()[0]
    assert state["status"] == "available"
    assert state["failure_count"] == 0
