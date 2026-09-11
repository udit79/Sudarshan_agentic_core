"""Offline renderer promotion metrics for video capability changes."""

from __future__ import annotations

from statistics import mean
from typing import Any, Iterable, Mapping

from pydantic import BaseModel, ConfigDict, Field


class VideoBenchmarkObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    renderer_id: str = Field(min_length=1)
    quality_status: str = "partial"
    duration_seconds: float = Field(default=0.0, ge=0.0)
    latency_seconds: float = Field(default=0.0, ge=0.0)
    cache_hits: int = Field(default=0, ge=0)
    failed_scene_count: int = Field(default=0, ge=0)
    estimated_cost: float | None = Field(default=None, ge=0.0)


class VideoBenchmarkReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observations: list[VideoBenchmarkObservation] = Field(default_factory=list)
    by_renderer: dict[str, dict[str, Any]] = Field(default_factory=dict)
    promoted_renderer: str | None = None
    promotion_reasons: list[str] = Field(default_factory=list)


def benchmark_video_observations(
    observations: Iterable[VideoBenchmarkObservation | Mapping[str, Any]],
    *,
    minimum_pass_rate: float = 0.9,
) -> VideoBenchmarkReport:
    """Summarize matched runs without inventing visual-preference scores."""

    rows = [item if isinstance(item, VideoBenchmarkObservation) else VideoBenchmarkObservation.model_validate(item) for item in observations]
    grouped: dict[str, list[VideoBenchmarkObservation]] = {}
    for row in rows:
        grouped.setdefault(row.renderer_id, []).append(row)
    summary: dict[str, dict[str, Any]] = {}
    for renderer, items in grouped.items():
        pass_rate = sum(item.quality_status == "passed" for item in items) / len(items)
        summary[renderer] = {
            "runs": len(items),
            "pass_rate": pass_rate,
            "mean_latency_seconds": mean(item.latency_seconds for item in items),
            "mean_cache_hits": mean(item.cache_hits for item in items),
            "mean_failed_scene_count": mean(item.failed_scene_count for item in items),
            "mean_estimated_cost": mean(item.estimated_cost for item in items if item.estimated_cost is not None) if any(item.estimated_cost is not None for item in items) else None,
        }
    eligible = [
        (renderer, metrics)
        for renderer, metrics in summary.items()
        if metrics["pass_rate"] >= minimum_pass_rate
    ]
    promoted = None
    reasons: list[str] = []
    if eligible:
        promoted = min(eligible, key=lambda item: (item[1]["mean_latency_seconds"], item[1]["mean_estimated_cost"] or 0.0))[0]
        reasons.append(f"{promoted} met the minimum pass-rate threshold")
    else:
        reasons.append("no renderer met the minimum pass-rate threshold")
    return VideoBenchmarkReport(
        observations=rows,
        by_renderer=summary,
        promoted_renderer=promoted,
        promotion_reasons=reasons,
    )


__all__ = ["VideoBenchmarkObservation", "VideoBenchmarkReport", "benchmark_video_observations"]
