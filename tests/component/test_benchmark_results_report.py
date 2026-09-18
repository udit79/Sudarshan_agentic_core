from __future__ import annotations

import json
from pathlib import Path

from scripts.build_benchmark_results import build_outputs


DATASET = Path(__file__).parents[2] / "docs" / "all test phases" / "benchmark-results" / "benchmark-results.json"


def test_benchmark_dataset_preserves_unknown_measurements_as_null() -> None:
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    live = next(item for item in data["records"] if item["record_id"] == "case-g01-live-usage-20260918")
    assert live["objective_metrics"]["cost_usd"] is None
    assert live["operational_measurements"]["provider_latency_ms"] is None
    assert live["operational_measurements"]["cost_status"] == "unavailable"


def test_benchmark_report_builds_traceable_csv_and_pngs(tmp_path: Path) -> None:
    outputs = build_outputs(DATASET, tmp_path)
    names = {path.name for path in outputs}
    assert "benchmark-results.csv" in names
    assert "chart-manifest.json" in names
    pngs = [path for path in outputs if path.suffix == ".png"]
    assert len(pngs) == 5
    assert all(path.read_bytes().startswith(b"\x89PNG") for path in pngs)

    manifest = json.loads((tmp_path / "chart-manifest.json").read_text(encoding="utf-8"))
    dataset_ids = {item["record_id"] for item in json.loads(DATASET.read_text(encoding="utf-8"))["records"]}
    assert manifest["dataset"] == DATASET.name
    assert all(set(chart["record_ids"]) <= dataset_ids for chart in manifest["charts"])


def test_benchmark_report_does_not_emit_sensitive_fixture_text(tmp_path: Path) -> None:
    build_outputs(DATASET, tmp_path)
    for path in tmp_path.iterdir():
        if path.suffix in {".csv", ".json"}:
            text = path.read_text(encoding="utf-8")
            assert "api_key" not in text.lower()
            assert "secret-value" not in text
