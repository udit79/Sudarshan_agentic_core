"""Safe, correlated runtime telemetry for the operator dashboard.

Observability is deliberately separate from model/memory logging.  This store
accepts only allow-listed identifiers, lifecycle states, usage counters,
quality references, cache outcomes, and wait reasons.  It never persists
prompts, raw memory, model output, input payloads, or secrets.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
import sqlite3
from threading import Lock
from typing import Any, Literal, Mapping, Protocol
from urllib.request import Request, urlopen
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from pipelines.orchestrator.contracts import TelemetrySummary, TelemetryUsage
from pipelines.orchestrator.progress import ProgressEvent, ProgressSink
from pipelines.common.ntro_policy import require_classification_access, require_classification
from api.control_plane import ControlPlane


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
    classification_level: str = "RESTRICTED"
    owner_id: str | None = Field(default=None, max_length=160)
    case_id: str | None = Field(default=None, max_length=160)
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
        classification_level=require_classification(str(payload.get("classification_level", "RESTRICTED"))),
        owner_id=_text(payload.get("owner_id"), 160),
        case_id=_text(payload.get("case_id"), 160),
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
                    event_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL DEFAULT '',
                    event_hash TEXT NOT NULL DEFAULT ''
                )"""
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(observability_events)")}
            if "previous_hash" not in columns:
                connection.execute("ALTER TABLE observability_events ADD COLUMN previous_hash TEXT NOT NULL DEFAULT ''")
            if "event_hash" not in columns:
                connection.execute("ALTER TABLE observability_events ADD COLUMN event_hash TEXT NOT NULL DEFAULT ''")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS observability_anchors (
                    run_id TEXT PRIMARY KEY,
                    anchor_hash TEXT NOT NULL DEFAULT ''
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
            previous_row = connection.execute(
                "SELECT event_hash FROM observability_events WHERE run_id = ? ORDER BY sequence DESC LIMIT 1",
                (event.run_id,),
            ).fetchone()
            previous_hash = str(previous_row[0]) if previous_row and previous_row[0] else ""
            if not previous_hash:
                anchor = connection.execute(
                    "SELECT anchor_hash FROM observability_anchors WHERE run_id = ?", (event.run_id,)
                ).fetchone()
                previous_hash = str(anchor[0]) if anchor else ""
            event_hash = hashlib.sha256(f"{previous_hash}:{payload}".encode("utf-8")).hexdigest()
            connection.execute(
                "INSERT INTO observability_events(run_id, event_json, previous_hash, event_hash) VALUES (?, ?, ?, ?)",
                (event.run_id, payload, previous_hash, event_hash),
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

    def events(
        self,
        run_id: str,
        *,
        limit: int = 500,
        access_level: str = "RESTRICTED",
        operator_id: str | None = None,
    ) -> tuple[ObservabilityEvent, ...]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT event_json FROM observability_events WHERE run_id = ? ORDER BY sequence DESC LIMIT ?",
                (str(run_id), max(1, min(int(limit), 5000))),
            ).fetchall()
        events = tuple(ObservabilityEvent.model_validate(json.loads(row[0])) for row in reversed(rows))
        for event in events:
            require_classification_access(access_level, event.classification_level)
            if operator_id is not None and event.owner_id is not None and event.owner_id != operator_id:
                raise PermissionError("operator is not authorized for this telemetry scope")
        return events

    def summary(
        self,
        run_id: str,
        *,
        access_level: str = "RESTRICTED",
        operator_id: str | None = None,
    ) -> TelemetrySummary:
        events = self.events(run_id, access_level=access_level, operator_id=operator_id)
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

    def safe_dashboard(
        self,
        run_id: str,
        *,
        access_level: str = "RESTRICTED",
        operator_id: str | None = None,
    ) -> dict[str, Any]:
        """Return the allow-listed projection used by dashboards and APIs."""

        events = self.events(run_id, access_level=access_level, operator_id=operator_id)
        return {
            "run_id": str(run_id),
            "summary": self.summary(
                run_id, access_level=access_level, operator_id=operator_id
            ).model_dump(mode="json"),
            "events": [event.model_dump(mode="json") for event in events],
        }

    def verify_integrity(self, run_id: str | None = None) -> bool:
        with self._lock, self._connect() as connection:
            runs = [str(run_id)] if run_id is not None else [
                str(row[0]) for row in connection.execute("SELECT DISTINCT run_id FROM observability_events")
            ]
            for current_run in runs:
                anchor_row = connection.execute(
                    "SELECT anchor_hash FROM observability_anchors WHERE run_id = ?", (current_run,)
                ).fetchone()
                previous = str(anchor_row[0]) if anchor_row else ""
                rows = connection.execute(
                    "SELECT event_json, previous_hash, event_hash FROM observability_events WHERE run_id = ? ORDER BY sequence",
                    (current_run,),
                ).fetchall()
                for payload, previous_hash, event_hash in rows:
                    expected = hashlib.sha256(f"{previous}:{payload}".encode("utf-8")).hexdigest()
                    if str(previous_hash) != previous or str(event_hash) != expected:
                        return False
                    previous = expected
        return True

    def purge_expired(self, *, retention_seconds: int, dry_run: bool = True) -> tuple[str, ...]:
        if retention_seconds < 1:
            raise ValueError("retention_seconds must be positive")
        cutoff = datetime.now(timezone.utc).timestamp() - retention_seconds
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT sequence, run_id, event_json, event_hash FROM observability_events ORDER BY sequence"
            ).fetchall()
            expired: list[tuple[int, str, str]] = []
            for sequence, current_run, payload, event_hash in rows:
                try:
                    timestamp = datetime.fromisoformat(json.loads(payload)["timestamp"]).timestamp()
                except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                    continue
                if timestamp < cutoff:
                    expired.append((int(sequence), str(current_run), str(event_hash)))
            event_ids = tuple(str(sequence) for sequence, _, _ in expired)
            if dry_run or not expired:
                return event_ids
            last_by_run: dict[str, str] = {}
            for _, current_run, event_hash in expired:
                last_by_run[current_run] = event_hash
            for current_run, anchor_hash in last_by_run.items():
                connection.execute(
                    "INSERT INTO observability_anchors(run_id, anchor_hash) VALUES (?, ?) "
                    "ON CONFLICT(run_id) DO UPDATE SET anchor_hash = excluded.anchor_hash",
                    (current_run, anchor_hash),
                )
            connection.executemany(
                "DELETE FROM observability_events WHERE sequence = ?",
                [(sequence,) for sequence, _, _ in expired],
            )
            return event_ids


def _summary_from_events(events: tuple[ObservabilityEvent, ...]) -> TelemetrySummary:
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


def _progress_observability_event(event: ProgressEvent) -> ObservabilityEvent:
    return ObservabilityEvent(
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
    )


class RedisObservabilityStore:
    """Shared safe dashboard projection backed by the control plane."""

    def __init__(self, control_plane: ControlPlane) -> None:
        self.control_plane = control_plane

    def record(self, event: ObservabilityEvent) -> ObservabilityEvent:
        self.control_plane.observability_record(event.run_id, event.model_dump(mode="json"))
        return event

    def record_runtime_event(self, name: str, payload: Mapping[str, Any]) -> ObservabilityEvent | None:
        event = runtime_event(name, payload)
        return self.record(event) if event is not None else None

    def record_progress(self, event: ProgressEvent) -> ObservabilityEvent:
        return self.record(_progress_observability_event(event))

    def events(
        self,
        run_id: str,
        *,
        limit: int = 500,
        access_level: str = "RESTRICTED",
        operator_id: str | None = None,
    ) -> tuple[ObservabilityEvent, ...]:
        events = tuple(
            ObservabilityEvent.model_validate(item)
            for item in self.control_plane.observability_events(run_id, limit=limit)
        )
        for event in events:
            require_classification_access(access_level, event.classification_level)
            if operator_id is not None and event.owner_id is not None and event.owner_id != operator_id:
                raise PermissionError("operator is not authorized for this telemetry scope")
        return events

    def summary(
        self,
        run_id: str,
        *,
        access_level: str = "RESTRICTED",
        operator_id: str | None = None,
    ) -> TelemetrySummary:
        return _summary_from_events(
            self.events(run_id, access_level=access_level, operator_id=operator_id)
        )

    def safe_dashboard(
        self,
        run_id: str,
        *,
        access_level: str = "RESTRICTED",
        operator_id: str | None = None,
    ) -> dict[str, Any]:
        events = self.events(run_id, access_level=access_level, operator_id=operator_id)
        return {
            "run_id": str(run_id),
            "summary": _summary_from_events(events).model_dump(mode="json"),
            "events": [event.model_dump(mode="json") for event in events],
        }


class ObservabilityExporter(Protocol):
    """Exporter for the already-redacted event contract."""

    def export(self, event: ObservabilityEvent) -> None:
        ...


class JsonHttpObservabilityExporter:
    """Best-effort HTTP collector for safe observability events.

    It is intentionally dependency-free and optional. A collector outage must
    not interrupt queue processing or artifact generation.
    """

    def __init__(self, endpoint: str, *, timeout_seconds: float = 2.0, bearer_token: str | None = None) -> None:
        endpoint = str(endpoint).strip()
        if not endpoint:
            raise ValueError("observability exporter endpoint must be non-empty")
        if timeout_seconds <= 0:
            raise ValueError("observability exporter timeout must be positive")
        self.endpoint = endpoint
        self.timeout_seconds = float(timeout_seconds)
        self.bearer_token = bearer_token.strip() if bearer_token else None
        self.failed_exports = 0

    def export(self, event: ObservabilityEvent) -> None:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "sudarshan-observability/1",
        }
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        request = Request(
            self.endpoint,
            data=json.dumps({"events": [event.model_dump(mode="json")]}, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310 - operator-configured endpoint
                response.read(1)
        except Exception:
            self.failed_exports += 1


class CompositeObservabilityStore:
    """Keep a tamper-evident local audit and a shared dashboard projection."""

    def __init__(
        self,
        local: SQLiteObservabilityStore,
        shared: RedisObservabilityStore | None = None,
        exporter: ObservabilityExporter | None = None,
    ) -> None:
        self.local = local
        self.shared = shared
        self.exporter = exporter

    def record(self, event: ObservabilityEvent) -> ObservabilityEvent:
        self.local.record(event)
        if self.shared is not None:
            self.shared.record(event)
        if self.exporter is not None:
            self.exporter.export(event)
        return event

    def record_runtime_event(self, name: str, payload: Mapping[str, Any]) -> ObservabilityEvent | None:
        event = runtime_event(name, payload)
        return self.record(event) if event is not None else None

    def record_progress(self, event: ProgressEvent) -> ObservabilityEvent:
        return self.record(_progress_observability_event(event))

    def events(self, run_id: str, **kwargs: Any) -> tuple[ObservabilityEvent, ...]:
        if self.shared is not None:
            return self.shared.events(run_id, **kwargs)
        return self.local.events(run_id, **kwargs)

    def summary(self, run_id: str, **kwargs: Any) -> TelemetrySummary:
        if self.shared is not None:
            return self.shared.summary(run_id, **kwargs)
        return self.local.summary(run_id, **kwargs)

    def safe_dashboard(self, run_id: str, **kwargs: Any) -> dict[str, Any]:
        if self.shared is not None:
            return self.shared.safe_dashboard(run_id, **kwargs)
        return self.local.safe_dashboard(run_id, **kwargs)

    def purge_expired(self, **kwargs: Any) -> tuple[str, ...]:
        return self.local.purge_expired(**kwargs)

    def verify_integrity(self, run_id: str | None = None) -> bool:
        return self.local.verify_integrity(run_id)


class ObservableProgressSink:
    """Forward progress normally while recording its safe telemetry twin."""

    def __init__(self, sink: ProgressSink, observability: Any) -> None:
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
    "CompositeObservabilityStore",
    "JsonHttpObservabilityExporter",
    "ObservabilityExporter",
    "RedisObservabilityStore",
    "SQLiteObservabilityStore",
    "runtime_event",
]
