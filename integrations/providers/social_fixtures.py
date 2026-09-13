"""Deterministic, network-free social adapters for contract tests.

These adapters deliberately implement the same small ``SocialAdapter`` seam as
an approved provider.  They return provider-neutral mappings or raise ordinary
provider-shaped exceptions; ``SocialCapabilityBoundary`` remains responsible
for approval, cancellation, timeout, classification, and receipt formation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import sleep
from threading import Event
from typing import Any, Mapping

from integrations.providers.social import ManualSocialAdapter, SocialRequest


@dataclass(slots=True)
class FixtureSocialAdapter:
    """A configurable adapter with deterministic calls and no network access."""

    provider: str
    response: Mapping[str, Any] = field(default_factory=dict)
    error: Exception | None = None
    delay_seconds: float = 0.0
    calls: int = 0

    def execute(self, request: SocialRequest, *, cancel_event: Event | None = None) -> Mapping[str, Any]:
        if cancel_event is not None and cancel_event.is_set():
            return {"status": "cancelled"}
        self.calls += 1
        if self.delay_seconds > 0:
            sleep(self.delay_seconds)
        if self.error is not None:
            raise self.error
        return dict(self.response)


def build_social_fixture_adapters() -> dict[str, FixtureSocialAdapter | ManualSocialAdapter]:
    """Return the complete offline scenario set used by social contract tests."""

    return {
        "manual": ManualSocialAdapter(),
        "mcp": FixtureSocialAdapter(
            "mcp",
            {"status": "pending", "request_id": "mcp-request-1", "provider_request_id": "mcp-provider-1"},
        ),
        "success": FixtureSocialAdapter(
            "success",
            {"status": "succeeded", "request_id": "provider-request-1", "provider_request_id": "provider-1", "data": {"published": True}},
        ),
        "retry": FixtureSocialAdapter(
            "retry",
            {"status": "failed", "request_id": "retry-request-1", "retry_after_seconds": 30, "error_code": "SOCIAL_RATE_LIMIT"},
        ),
        "timeout": FixtureSocialAdapter("timeout", delay_seconds=0.02),
        "quota": FixtureSocialAdapter("quota", error=RuntimeError("insufficient_quota: exceeded your current quota")),
        "rate_limit": FixtureSocialAdapter("rate_limit", error=RuntimeError("429 rate limit; retry-after=30")),
        "authorization": FixtureSocialAdapter("authorization", error=PermissionError("unauthorized")),
    }


__all__ = ["FixtureSocialAdapter", "build_social_fixture_adapters"]
