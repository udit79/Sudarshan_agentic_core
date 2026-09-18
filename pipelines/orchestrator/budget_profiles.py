"""Explicit, reviewable provider budget profiles for benchmark runs."""

from __future__ import annotations

from dataclasses import dataclass
import math

from pipelines.orchestrator.spend_guard import declared_provider_reservation


@dataclass(frozen=True, slots=True)
class ProviderBudgetProfile:
    """A pipeline-specific token profile that requires explicit approval."""

    pipeline: str
    total_tokens: int
    input_tokens_per_call: int
    output_tokens_per_call: int
    provider_call_count: int
    approved: bool = False
    rationale: str = ""

    @property
    def reserved_tokens(self) -> int:
        return declared_provider_reservation(
            input_tokens_per_call=self.input_tokens_per_call,
            output_tokens_per_call=self.output_tokens_per_call,
            provider_call_count=self.provider_call_count,
        )

    @property
    def fits_budget(self) -> bool:
        return self.reserved_tokens <= self.total_tokens

    def as_preflight_metadata(self, *, allow_unapproved: bool = False) -> dict[str, object]:
        """Return opt-in metadata only for an approved or diagnostic profile."""

        if not self.approved and not allow_unapproved:
            raise ValueError(f"provider budget profile is not approved: {self.pipeline}")
        return {
            "provider_token_budget": self.total_tokens,
            "provider_budget_preflight": True,
            "provider_input_token_budget": self.input_tokens_per_call,
            "provider_output_token_budget": self.output_tokens_per_call,
            "provider_call_count": self.provider_call_count,
        }


def diagnostic_profile_from_observed_run(
    *,
    pipeline: str,
    configured_budget: int,
    observed_input_tokens: int,
    observed_output_tokens: int,
    provider_call_count: int,
    rationale: str,
) -> ProviderBudgetProfile:
    """Create a conservative diagnostic profile from recorded usage only.

    The per-call values are rounded upward from the aggregate receipt. This is
    a diagnostic ceiling, not a claim that every call used the same amount.
    The returned profile is deliberately unapproved.
    """

    calls = max(1, int(provider_call_count))
    return ProviderBudgetProfile(
        pipeline=pipeline,
        total_tokens=max(0, int(configured_budget)),
        input_tokens_per_call=max(1, math.ceil(max(0, int(observed_input_tokens)) / calls)),
        output_tokens_per_call=max(1, math.ceil(max(0, int(observed_output_tokens)) / calls)),
        provider_call_count=calls,
        approved=False,
        rationale=rationale,
    )


EXECUTIVE_SUMMARY_G01_DIAGNOSTIC_PROFILE = diagnostic_profile_from_observed_run(
    pipeline="executive_summary",
    configured_budget=12_000,
    observed_input_tokens=54_165,
    observed_output_tokens=11_919,
    provider_call_count=4,
    rationale=(
        "Derived from the recorded G01 provider receipt; diagnostic only until "
        "context reduction and stage-level measurements are complete."
    ),
)


__all__ = [
    "EXECUTIVE_SUMMARY_G01_DIAGNOSTIC_PROFILE",
    "ProviderBudgetProfile",
    "diagnostic_profile_from_observed_run",
]
