from __future__ import annotations

from ingestion_pipelines.contracts import IngestionBudget
from ingestion_pipelines.runtime import IngestionBudgetController, IngestionBudgetExceededError, IngestionUsageRecorder


class FakeIngestionPlane:
    def __init__(self) -> None:
        self._controller = IngestionBudgetController()
        self._usage = IngestionUsageRecorder()

    @staticmethod
    def _snapshot(snapshot):
        return {
            "ingestion_id": snapshot.ingestion_id,
            "budget": snapshot.budget.model_dump(mode="json"),
            "stage_units": dict(snapshot.stage_units),
            "stage_tokens": dict(snapshot.stage_tokens),
            "fan_out_used": snapshot.fan_out_used,
            "total_tokens": snapshot.total_tokens,
        }

    def ingestion_budget_register(self, ingestion_id, budget):
        return self._snapshot(self._controller.register(ingestion_id, IngestionBudget.model_validate(budget)))

    def ingestion_budget_charge(self, ingestion_id, *, stage, units, tokens, fan_out):
        try:
            return self._snapshot(self._controller.charge(ingestion_id, stage, units=units, tokens=tokens, fan_out=fan_out))
        except IngestionBudgetExceededError as error:
            return {"error": error.code}

    def ingestion_budget_snapshot(self, ingestion_id):
        return self._snapshot(self._controller.snapshot(ingestion_id))

    def ingestion_usage_record(self, ingestion_id, record):
        self._usage.record(
            ingestion_id,
            stage=record["stage"],
            provider=record["provider"],
            model=record["model"],
            input_tokens=record["input_tokens"],
            output_tokens=record["output_tokens"],
            is_estimate=record["is_estimate"],
        )

    def ingestion_usage_snapshot(self, ingestion_id):
        return self._usage.snapshot(ingestion_id)


def test_shared_ingestion_budget_prevents_concurrent_overcommit_and_keeps_usage_labels():
    plane = FakeIngestionPlane()
    first = IngestionBudgetController(control_plane=plane)
    second = IngestionBudgetController(control_plane=plane)
    budget = IngestionBudget(token_budget=100, parser_units=1, max_fan_out=2)

    first.register("ing-1", budget)
    second.register("ing-1", budget)
    first.charge("ing-1", "parser", units=1, tokens=60, fan_out=1)
    try:
        second.charge("ing-1", "parser", units=1, tokens=60, fan_out=1)
    except IngestionBudgetExceededError as error:
        assert error.code == "STAGE_CALL_BUDGET"
    else:
        raise AssertionError("shared ingestion stage budget was overspent")

    recorder = IngestionUsageRecorder(control_plane=plane)
    recorder.record_estimate("ing-1", stage="vision", tokens=20)
    recorder.record("ing-1", stage="vision", provider="test", model="vision", output_tokens=12)
    usage = recorder.snapshot("ing-1")
    assert usage["estimated_tokens"] == 20
    assert usage["actual_tokens"] == 12
    assert usage["usage_is_estimate"] is True
