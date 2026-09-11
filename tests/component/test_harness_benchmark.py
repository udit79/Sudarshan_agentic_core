from __future__ import annotations

from scripts.benchmark_harness import build_report


def test_harness_benchmark_is_offline_and_reports_boundary_controls() -> None:
    report = build_report()

    assert report["cost"] == {"provider_calls": 0, "model_tokens": 0, "network_calls": 0}
    assert report["schema"]["artifact_profile_tools"] < report["schema"]["full_mcp_tools"]
    assert report["quality"]["renderer_count"] >= 1
    assert report["quality"]["sandbox"]["success"] is True
    assert report["safe_logging"]["secret_redaction_passed"] is True
