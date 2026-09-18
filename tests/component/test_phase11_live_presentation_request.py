"""Offline contract checks for the one controlled Phase 11 live artifact request."""

from __future__ import annotations

import json
from pathlib import Path


FIXTURE = Path(__file__).parents[1] / "fixtures" / "phase11_g01_presentation_live_request.json"


def _request() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_phase11_live_request_is_single_pipeline_and_bounded() -> None:
    request = _request()

    assert request["pipeline"] == "presentation"
    assert request["requested_pipelines"] == ["presentation"]
    assert request["metadata"]["pipeline"] == "presentation"
    assert request["metadata"]["provider_context_compaction"] is True
    assert request["constraints"] == {
        "slide_count": 2,
        "page_count": 2,
        "theme_id": "ntro-briefing",
    }
    assert request["top_k"] == 6
    assert request["token_budget"] == 1500


def test_phase11_live_request_contains_no_credentials_or_raw_runtime_paths() -> None:
    raw = FIXTURE.read_text(encoding="utf-8")
    lowered = raw.lower()

    assert "api_key" not in lowered
    assert "authorization" not in lowered
    assert "openai_api_key" not in lowered
    assert "c:\\" not in lowered
    assert "\\artifacts\\" not in lowered
