from __future__ import annotations

import pytest

from ingestion_pipelines import (
    IngestionBudget,
    IngestionBudgetController,
    IngestionBudgetExceededError,
    IngestionStageCache,
    IngestionUsageRecorder,
    build_ingestion_stage_fingerprint,
    run_optional_stage_with_retry,
)


def _scope(case_id: str = "case-1") -> dict[str, str]:
    return {"user_id": "user-1", "case_id": case_id, "task_id": "task-1"}


def test_ingestion_budget_charges_stage_tokens_and_fanout() -> None:
    controller = IngestionBudgetController()
    controller.register(
        "ing-1",
        IngestionBudget(
            token_budget=100,
            parser_units=1,
            ocr_calls=2,
            summary_tokens=60,
            embedding_tokens=40,
            max_fan_out=3,
        ),
    )

    snapshot = controller.charge("ing-1", "parser", fan_out=1)
    assert snapshot.stage_units["parser"] == 1
    controller.charge("ing-1", "summary", tokens=60, fan_out=1)

    with pytest.raises(IngestionBudgetExceededError, match="summary token budget"):
        controller.charge("ing-1", "summary", tokens=1)
    with pytest.raises(IngestionBudgetExceededError, match="fan-out"):
        controller.charge("ing-1", "ocr", units=1, fan_out=2)


def test_stage_fingerprint_changes_for_parser_policy_or_scope() -> None:
    values = dict(
        source_hash="sha256:" + "a" * 64,
        stage="parser",
        stage_version="pdf@1",
        configuration_hash="config-a",
        model_policy="local-first",
        scope=_scope(),
    )
    original = build_ingestion_stage_fingerprint(**values)
    assert build_ingestion_stage_fingerprint(**{**values, "stage_version": "pdf@2"}) != original
    assert build_ingestion_stage_fingerprint(**{**values, "model_policy": "remote-fallback"}) != original
    assert build_ingestion_stage_fingerprint(**{**values, "scope": _scope("case-2")}) != original


def test_stage_cache_is_scoped_and_expires() -> None:
    cache = IngestionStageCache(":memory:")
    scope = _scope()
    fingerprint = build_ingestion_stage_fingerprint(
        source_hash="sha256:" + "b" * 64,
        stage="ocr",
        stage_version="ocr@1",
        configuration_hash="config-a",
        model_policy={"provider": "local"},
        scope=scope,
    )
    entry = cache.put(
        fingerprint=fingerprint,
        source_hash="sha256:" + "b" * 64,
        stage="ocr",
        stage_version="ocr@1",
        scope=scope,
        classification_level="RESTRICTED",
        payload={"evidence_ids": ["e-1"], "confidence": 0.9},
        ttl_seconds=10,
    )

    hit = cache.get(fingerprint, scope=scope, classification_level="RESTRICTED", now=1)
    assert hit is not None
    assert hit.payload["evidence_ids"] == ["e-1"]
    assert cache.get(fingerprint, scope=_scope("case-2"), classification_level="RESTRICTED") is None
    assert cache.get(fingerprint, scope=scope, classification_level="SECRET") is None
    assert cache.get(
        fingerprint,
        scope=scope,
        classification_level="RESTRICTED",
        now=entry.created_at + 11,
    ) is None
    cache.close()


def test_usage_recorder_separates_estimates_from_actual_provider_usage() -> None:
    recorder = IngestionUsageRecorder()
    recorder.record_estimate("ing-usage", stage="vision", tokens=4096)
    recorder.record(
        "ing-usage",
        stage="vision",
        provider="openai",
        model="gpt-4o-mini",
        input_tokens=1200,
        output_tokens=180,
    )

    snapshot = recorder.snapshot("ing-usage")
    assert snapshot["estimated_tokens"] == 4096
    assert snapshot["actual_tokens"] == 1380
    assert snapshot["by_stage"]["vision"]["calls"] == 2
    assert snapshot["usage_is_estimate"] is True


def test_optional_stage_retry_is_bounded_and_reports_attempts() -> None:
    attempts: list[int] = []
    retries: list[int] = []
    controller = IngestionBudgetController()
    controller.register("retry-ingestion", IngestionBudget(vision_calls=3))

    def operation(attempt: int) -> str:
        attempts.append(attempt)
        controller.charge("retry-ingestion", "vision")
        if attempt < 3:
            raise TimeoutError("provider timed out")
        return "ready"

    result = run_optional_stage_with_retry(
        operation,
        max_attempts=3,
        backoff_seconds=0,
        on_retry=lambda attempt, _error: retries.append(attempt),
    )

    assert result == "ready"
    assert attempts == [1, 2, 3]
    assert retries == [1, 2]
    assert controller.snapshot("retry-ingestion").stage_units["vision"] == 3


def test_optional_stage_does_not_retry_non_transient_errors() -> None:
    attempts: list[int] = []

    def operation(attempt: int) -> str:
        attempts.append(attempt)
        raise ValueError("invalid request")

    with pytest.raises(ValueError, match="invalid request"):
        run_optional_stage_with_retry(operation, max_attempts=4, backoff_seconds=0)
    assert attempts == [1]
