import pytest
from uuid import uuid4

from pipelines.orchestrator.contracts import UsageRecord, RunPolicy
from pipelines.orchestrator.budget import BudgetController
from pipelines.orchestrator.observability import ObservabilityEvent, _summary_from_events, TelemetryUsage

def test_usage_reconciliation_categories():
    controller = BudgetController()
    run_id = f"run-{uuid4().hex}"
    controller.register_run(run_id, RunPolicy())

    res1 = controller.reserve(run_id, model_tokens=2000)
    controller.commit(res1.reservation_id, UsageRecord(
        usage_id="usage-1", run_id=run_id, provider="openai", model="gpt-4",
        input_tokens=1000, output_tokens=500, attempt_id="attempt-1",
        is_estimate=True, provider_request_id=None
    ))

    res2 = controller.reserve(run_id, model_tokens=2000)
    controller.commit(res2.reservation_id, UsageRecord(
        usage_id="usage-2", run_id=run_id, provider="openai", model="gpt-4",
        input_tokens=1000, output_tokens=500, attempt_id="attempt-1",
        is_estimate=False, provider_request_id="req-123", billing_status="unreconciled"
    ))

    res3 = controller.reserve(run_id, model_tokens=3000)
    controller.commit(res3.reservation_id, UsageRecord(
        usage_id="usage-3", run_id=run_id, provider="openai", model="gpt-4",
        input_tokens=2000, output_tokens=500, attempt_id="attempt-2",
        is_estimate=False, provider_request_id="req-456", billing_status="matched"
    ))

    report = controller.usage(run_id)["reconciliation"]
    
    assert report["logical_run"]["tokens"] == 1500 + 1500 + 2500
    assert report["logical_run"]["attempt_count"] == 2
    
    assert report["estimated"]["tokens"] == 1500
    assert report["estimated"]["record_count"] == 1
    
    assert report["provider_observed"]["tokens"] == 4000
    assert report["provider_observed"]["record_count"] == 2
    
    assert report["billing_reconciled"]["tokens"] == 2500
    assert report["billing_reconciled"]["status"] == "partial"
    
    assert len(report["attempts"]) == 2
    assert any(a["attempt_id"] == "attempt-1" and a["tokens"] == 3000 for a in report["attempts"])

def test_deduplicate_events_in_observability():
    run_id = f"run-{uuid4().hex}"
    
    usage1 = TelemetryUsage(input_tokens=10, output_tokens=20)
    usage2 = TelemetryUsage(input_tokens=5, output_tokens=5)
    
    events = (
        ObservabilityEvent(run_id=run_id, event_type="progress", usage_id="u-1", usage=usage1),
        ObservabilityEvent(run_id=run_id, event_type="progress", usage_id="u-1", usage=usage1),
        ObservabilityEvent(run_id=run_id, event_type="progress", usage_id="u-2", usage=usage2),
    )
    
    summary = _summary_from_events(events)
    assert summary.input_tokens == 15
    assert summary.output_tokens == 25
