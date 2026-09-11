"""Deterministic multimodal retrieval benchmark and promotion gate.

The benchmark compares the current flat-text compatibility path with typed,
source-mapped evidence. It intentionally accepts measured runtime signals as
inputs; it does not guess provider prices or claim that synthetic data proves
production quality.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable, Mapping

from memory import AccessContext

from .evidence_index import EvidenceIndex
from .models import IngestedDocument


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    """One query with a reviewed source-of-truth evidence set."""

    case_id: str
    query: str
    document_id: str
    relevant_evidence_ids: tuple[str, ...]
    expected_evidence_count: int = 1
    modalities: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class BenchmarkSignals:
    """Optional measured signals from an ingestion/run receipt."""

    estimated_tokens: int = 0
    actual_tokens: int = 0
    cost_usd: float = 0.0
    queue_wait_ms: float = 0.0
    cache_hits: int = 0
    cache_misses: int = 0
    repairs: int = 0
    human_correction_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class BenchmarkObservation:
    variant: str
    case_id: str
    target_document_id: str
    returned_evidence_ids: tuple[str, ...]
    returned_document_ids: tuple[str, ...]
    relevant_evidence_ids: tuple[str, ...]
    extraction_coverage: float
    evidence_faithfulness: float
    latency_ms: float
    signals: BenchmarkSignals = field(default_factory=BenchmarkSignals)


@dataclass(frozen=True, slots=True)
class BenchmarkMetrics:
    query_count: int
    extraction_coverage: float
    retrieval_recall_at_k: float
    document_recall_at_k: float
    evidence_faithfulness: float
    estimated_tokens: int
    actual_tokens: int
    cost_usd: float
    p50_latency_ms: float
    p95_latency_ms: float
    cache_hit_rate: float
    average_queue_wait_ms: float
    repair_rate: float
    human_correction_seconds: float


@dataclass(frozen=True, slots=True)
class PromotionThresholds:
    """Conservative defaults; tune only from recorded benchmark evidence."""

    min_extraction_coverage: float = 0.95
    min_retrieval_recall_at_k: float = 0.80
    min_evidence_faithfulness: float = 0.95
    max_token_multiplier: float = 1.25
    max_p95_latency_multiplier: float = 1.50
    max_repair_rate: float = 0.20


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    passed: bool
    reasons: tuple[str, ...]
    thresholds: PromotionThresholds


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    baseline: BenchmarkMetrics
    typed_evidence: BenchmarkMetrics
    observations: tuple[BenchmarkObservation, ...]
    promotion: PromotionDecision

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe report for the dashboard and release record."""

        return asdict(self)


def archive_benchmark_report(
    report: BenchmarkReport,
    path: str | Path,
    *,
    corpus_id: str,
    artifact_type: str,
) -> Path:
    """Persist a promotion report for release review."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = report.to_dict()
    payload.update({
        "corpus_id": str(corpus_id),
        "artifact_type": str(artifact_type),
        "report_schema_version": "1",
    })
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return destination


def run_multimodal_benchmark(
    index: EvidenceIndex,
    documents: Iterable[IngestedDocument],
    cases: Iterable[BenchmarkCase],
    context: AccessContext,
    *,
    top_k: int = 3,
    signals: Mapping[str, BenchmarkSignals] | None = None,
    thresholds: PromotionThresholds | None = None,
) -> BenchmarkReport:
    """Run flat-text and typed-evidence retrieval over the same cases.

    ``signals`` may be keyed by ``case_id`` for shared measurements or by
    ``{variant}:{case_id}`` for variant-specific measured telemetry.
    """

    if top_k < 1:
        raise ValueError("top_k must be positive")
    document_list = list(documents)
    case_list = list(cases)
    if not case_list:
        raise ValueError("at least one benchmark case is required")
    by_id = {document.id: document for document in document_list}
    if len(by_id) != len(document_list):
        raise ValueError("benchmark documents must have unique IDs")
    signal_map = signals or {}
    observations: list[BenchmarkObservation] = []

    for case in case_list:
        document = by_id.get(case.document_id)
        if document is None:
            raise ValueError(f"benchmark case references unknown document: {case.document_id}")
        flat_signals = _signals_for(signal_map, "flat_text", case.case_id)
        typed_signals = _signals_for(signal_map, "typed_evidence", case.case_id)

        started = perf_counter()
        flat_documents = _flat_text_search(case.query, document_list, top_k=top_k)
        flat_latency = (perf_counter() - started) * 1000
        observations.append(
            BenchmarkObservation(
                variant="flat_text",
                case_id=case.case_id,
                target_document_id=case.document_id,
                returned_evidence_ids=(),
                returned_document_ids=tuple(item.id for item in flat_documents),
                relevant_evidence_ids=case.relevant_evidence_ids,
                extraction_coverage=_coverage(document, case.expected_evidence_count),
                evidence_faithfulness=0.0,
                latency_ms=flat_latency,
                signals=flat_signals,
            )
        )

        started = perf_counter()
        typed_results = index.search(
            case.query,
            context,
            modalities=case.modalities,
            top_k=top_k,
        )
        typed_latency = (perf_counter() - started) * 1000
        typed_ids = tuple(str(item["evidence_id"]) for item in typed_results)
        typed_documents = tuple(str(item["document_id"]) for item in typed_results)
        faithful = sum(
            bool(item.get("source_hash"))
            and _has_source_location(item.get("location"))
            and str(item.get("document_id")) == case.document_id
            for item in typed_results
        )
        observations.append(
            BenchmarkObservation(
                variant="typed_evidence",
                case_id=case.case_id,
                target_document_id=case.document_id,
                returned_evidence_ids=typed_ids,
                returned_document_ids=typed_documents,
                relevant_evidence_ids=case.relevant_evidence_ids,
                extraction_coverage=_coverage(document, case.expected_evidence_count),
                evidence_faithfulness=faithful / max(1, len(typed_results)),
                latency_ms=typed_latency,
                signals=typed_signals,
            )
        )

    baseline = _metrics(observations, "flat_text")
    typed = _metrics(observations, "typed_evidence")
    promotion = evaluate_promotion(baseline, typed, thresholds or PromotionThresholds())
    return BenchmarkReport(baseline, typed, tuple(observations), promotion)


def evaluate_promotion(
    baseline: BenchmarkMetrics,
    typed_evidence: BenchmarkMetrics,
    thresholds: PromotionThresholds,
) -> PromotionDecision:
    """Apply explicit quality and regression thresholds to a report."""

    reasons: list[str] = []
    if typed_evidence.extraction_coverage < thresholds.min_extraction_coverage:
        reasons.append("extraction coverage is below the promotion threshold")
    if typed_evidence.retrieval_recall_at_k < thresholds.min_retrieval_recall_at_k:
        reasons.append("typed evidence retrieval recall is below the promotion threshold")
    if typed_evidence.evidence_faithfulness < thresholds.min_evidence_faithfulness:
        reasons.append("typed evidence results are not sufficiently source-mapped")
    if baseline.estimated_tokens > 0 and typed_evidence.estimated_tokens > baseline.estimated_tokens * thresholds.max_token_multiplier:
        reasons.append("typed evidence exceeds the allowed estimated-token multiplier")
    if baseline.p95_latency_ms > 0 and typed_evidence.p95_latency_ms > baseline.p95_latency_ms * thresholds.max_p95_latency_multiplier:
        reasons.append("typed evidence exceeds the allowed P95 latency multiplier")
    if typed_evidence.repair_rate > thresholds.max_repair_rate:
        reasons.append("repair rate is above the promotion threshold")
    return PromotionDecision(not reasons, tuple(reasons), thresholds)


def _flat_text_search(query: str, documents: list[IngestedDocument], *, top_k: int) -> list[IngestedDocument]:
    terms = {term.lower() for term in query.split() if len(term) > 1}
    ranked = []
    for document in documents:
        text = document.raw_text.lower()
        score = sum(text.count(term) for term in terms)
        if score:
            ranked.append((score, document.id, document))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in ranked[:top_k]]


def _signals_for(
    signals: Mapping[str, BenchmarkSignals],
    variant: str,
    case_id: str,
) -> BenchmarkSignals:
    return signals.get(f"{variant}:{case_id}", signals.get(case_id, BenchmarkSignals()))


def _has_source_location(location: Any) -> bool:
    return isinstance(location, Mapping) and any(value is not None for value in location.values())


def _coverage(document: IngestedDocument, expected_count: int) -> float:
    return min(1.0, len(document.evidence_blocks) / max(1, expected_count))


def _metrics(observations: list[BenchmarkObservation], variant: str) -> BenchmarkMetrics:
    selected = [item for item in observations if item.variant == variant]
    relevant = sum(len(item.relevant_evidence_ids) for item in selected)
    retrieved = sum(
        len(set(item.returned_evidence_ids).intersection(item.relevant_evidence_ids))
        for item in selected
    )
    document_hits = sum(
        item.target_document_id in item.returned_document_ids
        for item in selected
    )
    total_cache = sum(item.signals.cache_hits + item.signals.cache_misses for item in selected)
    total_repairs = sum(item.signals.repairs for item in selected)
    latencies = [item.latency_ms for item in selected]
    return BenchmarkMetrics(
        query_count=len(selected),
        extraction_coverage=_mean(item.extraction_coverage for item in selected),
        retrieval_recall_at_k=retrieved / max(1, relevant),
        document_recall_at_k=document_hits / max(1, len(selected)),
        evidence_faithfulness=_mean(item.evidence_faithfulness for item in selected),
        estimated_tokens=sum(item.signals.estimated_tokens for item in selected),
        actual_tokens=sum(item.signals.actual_tokens for item in selected),
        cost_usd=sum(item.signals.cost_usd for item in selected),
        p50_latency_ms=_percentile(latencies, 50),
        p95_latency_ms=_percentile(latencies, 95),
        cache_hit_rate=sum(item.signals.cache_hits for item in selected) / max(1, total_cache),
        average_queue_wait_ms=_mean(item.signals.queue_wait_ms for item in selected),
        repair_rate=total_repairs / max(1, len(selected)),
        human_correction_seconds=sum(item.signals.human_correction_seconds for item in selected),
    )


def _mean(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / max(1, len(values))


def _percentile(values: Iterable[float], percentile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * percentile / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


__all__ = [
    "BenchmarkCase",
    "BenchmarkMetrics",
    "BenchmarkObservation",
    "BenchmarkReport",
    "BenchmarkSignals",
    "PromotionDecision",
    "PromotionThresholds",
    "evaluate_promotion",
    "run_multimodal_benchmark",
]
