"""Small offline evaluation contract for memory retrieval quality and cost."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class MemoryObservation:
    query_id: str
    relevant_memory_ids: tuple[str, ...]
    returned_memory_ids: tuple[str, ...]
    faithfulness: float
    estimated_tokens: int = 0
    actual_tokens: int = 0
    latency_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class MemoryEvaluationReport:
    query_count: int
    recall_at_k: float
    faithfulness: float
    estimated_tokens: int
    actual_tokens: int
    p50_latency_ms: float
    p95_latency_ms: float


def evaluate_memory(observations: Iterable[MemoryObservation]) -> MemoryEvaluationReport:
    items = list(observations)
    if not items:
        raise ValueError("at least one memory observation is required")
    recall = sum(
        len(set(item.relevant_memory_ids).intersection(item.returned_memory_ids))
        / max(1, len(set(item.relevant_memory_ids)))
        for item in items
    ) / len(items)
    latencies = sorted(float(item.latency_ms) for item in items)
    return MemoryEvaluationReport(
        query_count=len(items),
        recall_at_k=recall,
        faithfulness=sum(max(0.0, min(1.0, item.faithfulness)) for item in items) / len(items),
        estimated_tokens=sum(max(0, item.estimated_tokens) for item in items),
        actual_tokens=sum(max(0, item.actual_tokens) for item in items),
        p50_latency_ms=_percentile(latencies, 50),
        p95_latency_ms=_percentile(latencies, 95),
    )


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    position = (len(values) - 1) * percentile / 100
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


__all__ = ["MemoryEvaluationReport", "MemoryObservation", "evaluate_memory"]
