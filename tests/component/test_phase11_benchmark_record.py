from __future__ import annotations

from pipelines.orchestrator.benchmark_record import build_benchmark_record


def test_benchmark_record_keeps_wall_and_provider_latency_separate() -> None:
    record = build_benchmark_record(
        case="G01",
        pipeline="executive_summary",
        run_id="run-g01-measured",
        admission_ms=114,
        status={
            "status": "failed",
            "started_at": "2026-09-18T10:00:00+00:00",
            "finished_at": "2026-09-18T10:01:09.177000+00:00",
            "queued_at": "2026-09-18T09:59:59.900000+00:00",
            "attempts": 2,
            "response": {
                "status": "failed",
                "quality_status": "failed",
                "artifacts": [],
                "metadata": {"quality_review": {"issues": ["unsupported claim"]}},
            },
        },
        telemetry={
            "input_tokens": 29430,
            "output_tokens": 5900,
            "reasoning_tokens": 0,
            "estimated_cost": 0.0,
            "usage_is_estimate": True,
            "cache_hits": 0,
            "cache_misses": 0,
        },
        events=[
            {"usage": {"latency_scope": "crew_wall_time", "latency_ms": 69177}},
        ],
    )

    assert record.admission_ms == 114
    assert record.wall_ms == 69177
    assert record.queue_ms == 100
    assert record.provider_ms is None
    assert record.tokens.provider == 35330
    assert record.tokens.estimated is None
    assert record.quality_status == "failed"
    assert record.attempts == 2
    assert record.cache.hit is None
    assert "provider_ms unavailable" in record.measurement_notes[0]


def test_benchmark_record_preserves_success_artifact_identity_only() -> None:
    record = build_benchmark_record(
        case="G02",
        pipeline="presentation",
        run_id="run-g02-success",
        status={
            "status": "succeeded",
            "quality_status": "passed",
            "attempts": 1,
            "response": {
                "status": "succeeded",
                "artifact": {
                    "artifact_id": "artifact-g02",
                    "sha256": "a" * 64,
                    "path": "C:\\private\\raw\\presentation.pptx",
                },
            },
        },
        telemetry={"input_tokens": 10, "output_tokens": 5, "usage_is_estimate": False},
        events=[],
    )

    assert [item.model_dump() for item in record.artifacts] == [
        {"artifact_id": "artifact-g02", "sha256": "a" * 64}
    ]
    assert "private" not in record.model_dump_json()
    assert record.quality_status == "passed"


def test_benchmark_record_does_not_turn_missing_measurements_into_zero() -> None:
    record = build_benchmark_record(
        case="G03",
        pipeline="advisory",
        run_id="run-g03-unmeasured",
        status={"status": "failed", "response": {"status": "failed"}},
        telemetry={"estimated_cost": None, "usage_is_estimate": False},
    )

    assert record.wall_ms is None
    assert record.queue_ms is None
    assert record.provider_ms is None
    assert record.tokens.provider is None
    assert record.cache.hit is None
    assert record.cache.misses is None
    assert any("unavailable" in note for note in record.measurement_notes)
