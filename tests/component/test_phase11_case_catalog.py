from __future__ import annotations

import json
from pathlib import Path


CATALOG = Path(__file__).parents[1] / "fixtures" / "phase11_case_catalog.json"
GOLDEN_IDS = {f"G{i:02d}" for i in range(1, 11)}
HOLDOUT_IDS = {f"H{i:02d}" for i in range(1, 4)}
PIPELINES = {"advisory", "executive_summary", "presentation", "infographic"}


def _catalog() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def test_phase11_catalog_has_all_golden_and_holdout_cases_without_overlap() -> None:
    data = _catalog()
    golden = {item["case_id"] for item in data["golden"]}
    holdout = {item["case_id"] for item in data["holdout"]}

    assert data["sanitized"] is True
    assert golden == GOLDEN_IDS
    assert holdout == HOLDOUT_IDS
    assert golden.isdisjoint(holdout)


def test_phase11_cases_have_executable_evaluation_contracts() -> None:
    data = _catalog()
    for case in [*data["golden"], *data["holdout"]]:
        assert case["source_document_ids"]
        assert case["operator_request"]
        assert case["expected_evidence"]
        assert set(case["pipelines"]) <= PIPELINES
        assert case["constraints"]
        assert case["artifact_properties"]
        assert case["failure_conditions"]

    g10 = next(item for item in data["golden"] if item["case_id"] == "G10")
    assert "exactly 2 slides" in g10["constraints"]
    g07 = next(item for item in data["golden"] if item["case_id"] == "G07")
    assert "no forced artifact" in g07["constraints"]


def test_phase11_catalog_keeps_document_ownership_unique_and_sanitized() -> None:
    data = _catalog()
    all_document_ids = [
        document_id
        for case in [*data["golden"], *data["holdout"]]
        for document_id in case["source_document_ids"]
    ]
    assert len(all_document_ids) == len(set(all_document_ids))

    encoded = CATALOG.read_text(encoding="utf-8").lower()
    assert "openai_api_key" not in encoded
    assert "secret-value" not in encoded
    assert "password" not in encoded
