from __future__ import annotations

import json

from ingestion_pipelines import archive_benchmark_report
from ingestion_pipelines.evaluation import (
    BenchmarkMetrics,
    BenchmarkObservation,
    BenchmarkReport,
    BenchmarkSignals,
    PromotionDecision,
    PromotionThresholds,
)


def test_benchmark_report_archives_corpus_and_artifact_type(tmp_path):
    metrics = BenchmarkMetrics(1, 1, 1, 1, 1, 1, 1, 0, 1, 1, 1, 0, 0, 0)
    report = BenchmarkReport(
        metrics,
        metrics,
        (BenchmarkObservation("typed_evidence", "case", "doc", (), (), (), 1, 1, 1, BenchmarkSignals()),),
        PromotionDecision(True, (), PromotionThresholds()),
    )
    path = archive_benchmark_report(report, tmp_path / "report.json", corpus_id="sanitized-v1", artifact_type="video")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["corpus_id"] == "sanitized-v1"
    assert payload["artifact_type"] == "video"
    assert payload["report_schema_version"] == "1"
