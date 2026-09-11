"""Small capability-aware provider/model router.

The pipeline and skill routers decide *what* to execute.  This module decides
whether a provider/model is currently safe to call for a capability such as
``image`` or ``tts``.  Health is intentionally process-local for the first
slice; a shared control-plane backend can persist the same state later.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from threading import RLock
from typing import Callable

class ProviderUnavailableError(RuntimeError):
    """Raised when a provider is in cooldown for a capability."""

    def __init__(self, provider: str, capability: str, failure_class: str, retry_after_seconds: float) -> None:
        self.provider = provider
        self.capability = capability
        self.failure_class = failure_class
        self.retry_after_seconds = max(0.0, float(retry_after_seconds))
        super().__init__(
            f"provider '{provider}' is unavailable for {capability}: "
            f"{failure_class}; retry after {self.retry_after_seconds:.0f}s"
        )


@dataclass(frozen=True, slots=True)
class ModelRoute:
    capability: str
    provider: str
    model: str


@dataclass(slots=True)
class ProviderHealth:
    provider: str
    capability: str
    status: str = "available"
    failure_class: str | None = None
    cooldown_until: float = 0.0
    failure_count: int = 0
    last_error: str | None = None

    def snapshot(self, *, now: float) -> dict[str, object]:
        remaining = max(0.0, self.cooldown_until - now)
        status = self.status if remaining > 0 else "available"
        return {
            "provider": self.provider,
            "capability": self.capability,
            "status": status,
            "failure_class": self.failure_class,
            "cooldown_seconds": round(remaining, 3),
            "failure_count": self.failure_count,
        }


class ProviderRouter:
    """Select configured models and apply a lightweight provider circuit breaker."""

    _MODEL_ENV = {
        "text": "CREWAI_MODEL",
        "image": "OPENAI_IMAGE_MODEL",
        "tts": "OPENAI_TTS_MODEL",
        "video_script": "OPENAI_VIDEO_SCRIPT_MODEL",
    }

    def __init__(
        self,
        *,
        cooldown_seconds: float | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.cooldown_seconds = max(
            1.0,
            float(cooldown_seconds or os.getenv("SUDARSHAN_PROVIDER_COOLDOWN_SECONDS", "300")),
        )
        self._clock = clock or time.monotonic
        self._lock = RLock()
        self._health: dict[tuple[str, str], ProviderHealth] = {}

    def select_model(self, capability: str, requested: str | None = None) -> ModelRoute:
        """Resolve a model without making a provider call."""

        model = (requested or os.getenv(self._MODEL_ENV.get(capability, ""), "")).strip()
        if not model:
            defaults = {
                "text": "openai/gpt-5.4",
                "image": "gpt-image-1",
                "tts": "tts-1",
                "video_script": "gpt-5.4",
            }
            model = defaults.get(capability, "unknown")
        provider = "openai" if capability in {"image", "tts", "video_script"} else "openai"
        return ModelRoute(capability=capability, provider=provider, model=model)

    def before_call(self, provider: str, capability: str) -> None:
        with self._lock:
            health = self._get(provider, capability)
            now = self._clock()
            if health.cooldown_until > now:
                raise ProviderUnavailableError(
                    provider,
                    capability,
                    health.failure_class or "provider_unavailable",
                    health.cooldown_until - now,
                )

    def record_success(self, provider: str, capability: str) -> None:
        with self._lock:
            health = self._get(provider, capability)
            health.status = "available"
            health.failure_class = None
            health.cooldown_until = 0.0
            health.last_error = None
            health.failure_count = 0

    def record_failure(
        self,
        provider: str,
        capability: str,
        error: Exception,
        *,
        retry_after_seconds: float | None = None,
    ) -> str:
        """Record an error and return its stable operational classification."""

        # Keep this import lazy: receipts depends on pipeline contracts, while
        # pipeline packages may construct this router during import.
        from integrations.providers.receipts import classify_provider_error

        failure_class = classify_provider_error(error)
        with self._lock:
            health = self._get(provider, capability)
            health.failure_class = failure_class
            health.last_error = str(error)[:500]
            health.failure_count += 1
            # Permanent quota/auth failures and transient rate limits should stop
            # a retry storm. Invalid requests are caller bugs and remain open.
            if failure_class in {"quota_exhausted", "auth", "rate_limit", "transient"}:
                delay = retry_after_seconds if retry_after_seconds is not None else self.cooldown_seconds
                health.cooldown_until = self._clock() + max(1.0, float(delay))
                health.status = failure_class
        return failure_class

    def snapshot(self) -> list[dict[str, object]]:
        with self._lock:
            now = self._clock()
            return [health.snapshot(now=now) for health in self._health.values()]

    def _get(self, provider: str, capability: str) -> ProviderHealth:
        key = (provider, capability)
        if key not in self._health:
            self._health[key] = ProviderHealth(provider=provider, capability=capability)
        return self._health[key]


__all__ = ["ModelRoute", "ProviderHealth", "ProviderRouter", "ProviderUnavailableError"]
