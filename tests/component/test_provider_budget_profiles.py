from __future__ import annotations

import pytest

from pipelines.orchestrator.budget_profiles import (
    EXECUTIVE_SUMMARY_G01_DIAGNOSTIC_PROFILE,
    ProviderBudgetProfile,
    diagnostic_profile_from_observed_run,
)


def test_g01_diagnostic_profile_is_traceable_and_not_approved() -> None:
    profile = EXECUTIVE_SUMMARY_G01_DIAGNOSTIC_PROFILE

    assert profile.pipeline == "executive_summary"
    assert profile.total_tokens == 12_000
    assert profile.approved is False
    assert "66,084" not in profile.rationale
    assert profile.reserved_tokens > profile.total_tokens
    assert "recorded G01 provider receipt" in profile.rationale


def test_unapproved_profile_cannot_be_activated_accidentally() -> None:
    with pytest.raises(ValueError, match="not approved"):
        EXECUTIVE_SUMMARY_G01_DIAGNOSTIC_PROFILE.as_preflight_metadata()


def test_diagnostic_profile_can_be_used_only_explicitly_for_offline_rejection() -> None:
    metadata = EXECUTIVE_SUMMARY_G01_DIAGNOSTIC_PROFILE.as_preflight_metadata(
        allow_unapproved=True
    )

    assert metadata["provider_budget_preflight"] is True
    assert metadata["provider_token_budget"] == 12_000
    assert metadata["provider_call_count"] == 4


def test_profile_from_observed_usage_rounds_up_conservatively() -> None:
    profile = diagnostic_profile_from_observed_run(
        pipeline="executive_summary",
        configured_budget=10_000,
        observed_input_tokens=1001,
        observed_output_tokens=501,
        provider_call_count=4,
        rationale="offline fixture",
    )

    assert profile.input_tokens_per_call == 251
    assert profile.output_tokens_per_call == 126
    assert profile.reserved_tokens == (251 + 126) * 4
    assert profile.approved is False
