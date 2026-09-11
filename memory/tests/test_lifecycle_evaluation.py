from datetime import timedelta

from memory import AccessContext, KnowledgeUnit, MemoryManager, MemoryObservation, Source, SourceType, evaluate_memory
from memory.model import utc_now


class _Backend:
    def remember(self, **kwargs):
        return {"status": "accepted"}

    def recall(self, **kwargs):
        return []


def test_memory_lifecycle_records_safe_events_and_expires_due_memory():
    manager = MemoryManager(_Backend())
    context = AccessContext(user_id="u-1", case_id="c-1")
    receipt = manager.remember(
        KnowledgeUnit(
            unit_id="unit-1",
            content="temporary fact",
            source=Source("source-1", SourceType.TEXT, "case://source-1"),
        ),
        context,
        expires_at=utc_now() + timedelta(seconds=1),
        importance=0.8,
        confidence=0.9,
    )
    assert receipt.memory.importance == 0.8
    assert receipt.memory.confidence == 0.9
    assert manager.event_log.list(memory_id=receipt.memory.id)[0].safe_metadata["memory_type"] == "fact"

    expired = manager.expire_due(now=utc_now() + timedelta(seconds=2))
    assert [item.id for item in expired] == [receipt.memory.id]
    assert manager.store.get_memory(receipt.memory.id).lifecycle.value == "expired"
    assert manager.event_log.list(memory_id=receipt.memory.id)[-1].event_type == "expired"


def test_memory_evaluation_reports_recall_cost_and_latency():
    report = evaluate_memory([
        MemoryObservation("q1", ("m1", "m2"), ("m1",), 1.0, estimated_tokens=10, actual_tokens=8, latency_ms=10),
        MemoryObservation("q2", ("m3",), ("m3",), 0.8, estimated_tokens=20, actual_tokens=18, latency_ms=30),
    ])
    assert report.query_count == 2
    assert report.recall_at_k == 0.75
    assert report.estimated_tokens == 30
    assert report.p95_latency_ms == 29.0
