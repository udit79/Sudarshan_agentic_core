"""Safe, correlated runtime telemetry for the operator dashboard.

Observability is deliberately separate from model/memory logging.  This store
accepts only allow-listed identifiers, lifecycle states, usage counters,
quality references, cache outcomes, and wait reasons.  It never persists
prompts, raw memory, model output, input payloads, or secrets.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import sqlite3
from threading import Lock
from typing import Any, Literal, Mapping
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from pipelines.orchestrator.contracts import TelemetrySummary, TelemetryUsage
from pipelines.orchestrator.progress import ProgressEvent, ProgressSink


CacheStatus = Literal["hit", "miss", "wait", "write", "not_applicable"]


class ObservabilityEvent(BaseModel):
    """One sanitized event suitable for operator-only diagnostics."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: f"obs-{uuid4().hex}")
    run_id: str = Field(min_length=1)
    task_id: str = Field(default="", max_length=200)
    event_type: str = Field(min_length=1, max_length=100)
    stage: str = Field(default="", max_length=100)
    status: str = Field(default="", max_length=50)
    skill_id: str | None = Field(default=None, max_length=160)
    node_id: str | None = Field(default=None, max_length=160)
    child_id: str | None = Field(default=None, max_length=160)
    skill_call_id: str | None = Field(default=None, max_length=200)
    artifact_ids: list[str] = Field(default_factory=list, max_length=32)
    quality_report_id: str | None = Field(default=None, max_length=200)
    quality_status: str | None = Field(default=None, max_length=40)
    cache_status: CacheStatus | None = None
    wait_reason: str = Field(default="", max_length=500)
    error_code: str | None = Field(default=None, max_length=100)
    usage: TelemetryUsage | None = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def _text(value: Any, limit: int = 200) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value[:limit] or None


def _artifact_ids(value: Any) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = []
    return [str(item)[:200] for item in values if str(item).strip()][:32]


def _usage(value: Any) -> TelemetryUsage | None:
    if not isinstance(value, Mapping):
        return None
    try:
        return TelemetryUsage(
            provider=_text(value.get("provider"), 100),
            model=_text(value.get("model"), 160),
            input_tokens=max(0, int(value.get("input_tokens", 0) or 0)),
            output_tokens=max(0, int(value.get("output_tokens", 0) or 0)),
            reasoning_tokens=max(0, int(value.get("reasoning_tokens", 0) or 0)),
            tool_calls=max(0, int(value.get("tool_calls", 0) or 0)),
            latency_ms=max(0, int(value.get("latency_ms", 0) or 0)),
            estimated_cost=max(0.0, float(value.get("estimated_cost", 0.0) or 0.0)),
            is_estimate=bool(value.get("is_estimate", False)),
        )
    except (TypeError, ValueError):
        return None


def runtime_event(name: str, payload: Mapping[str, Any]) -> ObservabilityEvent | None:
    """Convert a child-runtime callback into an allow-listed event."""

    run_id = _text(payload.get("parent_run_id") or payload.get("run_id"))
    if not run_id:
        return None
    cache_status: CacheStatus | None = None
    if name.endswith("cache_hit"):
        cache_status = "hit"
    elif name.endswith("cache_wait"):
        cache_status = "wait"
    elif name.endswith("cache_write_failed"):
        cache_status = "write"
    if name.endswith("waiting"):
        status = "waiting"
    elif name.endswith("cancelled"):
        status = "cancelled"
    elif name.endswith(("failed", "blocked")):
        status = "failed"
    elif name.endswith("completed"):
        status = "succeeded"
    else:
        status = "running"
    return ObservabilityEvent(
        run_id=run_id,
        task_id=_text(payload.get("task_id") or payload.get("parent_node_id"), 200) or "",
        event_type=name,
        stage=name,
        status=status,
        skill_id=_text(payload.get("skill_id"), 160),
        node_id=_text(payload.get("parent_node_id"), 160),
        child_id=_text(payload.get("child_run_id"), 160),
        skill_call_id=_text(payload.get("skill_call_id"), 200),
        artifact_ids=_artifact_ids(payload.get("artifact_ids")),
        quality_report_id=_text(payload.get("quality_report_id"), 200),
        quality_status=_text(payload.get("quality_status"), 40),
        cache_status=cache_status,
        wait_reason=("Child skill is waiting for a dependency or cache owner." if status == "waiting" else ""),
        error_code=_text(payload.get("error_code"), 100),
        usage=_usage(payload.get("usage")),
    )


class SQLiteObservabilityStore:
    """Durable local telemetry store with a safe aggregate projection."""

    def __init__(self, db_path: str | None = None) -> None:
        configured = db_path or os.getenv(
            "SUDARSHAN_OBSERVABILITY_DB_PATH", "artifacts/.state/observability.db"
        )
        self._db_path = configured
        os.makedirs(os.path.dirname(os.path.abspath(configured)), exist_ok=True)
        self._lock = Lock()
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS observability_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    event_json TEXT NOT NULL
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_observability_run ON observability_events(run_id, sequence)"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path, check_same_thread=False)

    def record(self, event: ObservabilityEvent) -> ObservabilityEvent:
        payload = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO observability_events(run_id, event_json) VALUES (?, ?)",
                (event.run_id, payload),
            )
        return event

    def record_runtime_event(self, name: str, payload: Mapping[str, Any]) -> ObservabilityEvent | None:
        event = runtime_event(name, payload)
        return self.record(event) if event is not None else None

    def record_progress(self, event: ProgressEvent) -> ObservabilityEvent:
        return self.record(ObservabilityEvent(
            event_id=event.event_id,
            run_id=event.run_id,
            task_id=event.task_id,
            event_type=f"progress.{event.stage}",
            stage=event.stage,
            status=event.status,
            skill_id=event.pipeline,
            artifact_ids=_artifact_ids(event.artifact_id),
            quality_report_id=event.quality_report_id,
            quality_status=event.quality_status,
            cache_status=event.cache_status,
            wait_reason=event.wait_reason or (event.message if event.requires_action else ""),
            error_code=event.error_code,
            usage=event.usage,
        ))

    def events(self, run_id: str, *, limit: int = 500) -> tuple[ObservabilityEvent, ...]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT event_json FROM observability_events WHERE run_id = ? ORDER BY sequence DESC LIMIT ?",
                (str(run_id), max(1, min(int(limit), 5000))),
            ).fetchall()
        return tuple(ObservabilityEvent.model_validate(json.loads(row[0])) for row in reversed(rows))

    def summary(self, run_id: str) -> TelemetrySummary:
        events = self.events(run_id)
        artifact_ids: set[str] = set()
        child_ids: set[str] = set()
        quality_ids: set[str] = set()
        summary = TelemetrySummary(event_count=len(events))
        for event in events:
            artifact_ids.update(event.artifact_ids)
            if event.child_id:
                child_ids.add(event.child_id)
            if event.quality_report_id:
                quality_ids.add(event.quality_report_id)
            if event.cache_status == "hit":
                summary.cache_hits += 1
            elif event.cache_status == "miss":
                summary.cache_misses += 1
            elif event.cache_status == "wait":
                summary.cache_waits += 1
            if event.status in {"waiting", "waiting_for_input", "waiting_for_approval", "pending"} or event.wait_reason:
                summary.wait_count += 1
            if event.usage is not None:
                summary.input_tokens += event.usage.input_tokens
                summary.output_tokens += event.usage.output_tokens
                summary.reasoning_tokens += event.usage.reasoning_tokens
                summary.tool_calls += event.usage.tool_calls
                summary.latency_ms += event.usage.latency_ms
                summary.estimated_cost += event.usage.estimated_cost
                summary.usage_is_estimate = summary.usage_is_estimate or event.usage.is_estimate
            summary.last_stage = event.stage
            summary.last_status = event.status
        return summary.model_copy(update={
            "child_count": len(child_ids),
            "artifact_count": len(artifact_ids),
            "quality_report_count": len(quality_ids),
            "estimated_cost": round(summary.estimated_cost, 8),
        })


class ObservableProgressSink:
    """Forward progress normally while recording its safe telemetry twin."""

    def __init__(self, sink: ProgressSink, observability: SQLiteObservabilityStore) -> None:
        self.sink = sink
        self.observability = observability

    def publish(self, event: ProgressEvent) -> None:
        self.sink.publish(event)
        self.observability.record_progress(event)

    def events(self, run_id: str, *, after_sequence: int = 0) -> tuple[ProgressEvent, ...]:
        return self.sink.events(run_id, after_sequence=after_sequence)

    def clear(self, run_id: str) -> None:
        clear = getattr(self.sink, "clear", None)
        if callable(clear):
            clear(run_id)


__all__ = [
    "ObservableProgressSink",
    "ObservabilityEvent",
    "SQLiteObservabilityStore",
    "runtime_event",
]
