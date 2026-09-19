"""Frontend-safe progress events for long-running pipeline runs."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
import os
import sqlite3
from threading import Lock
from typing import Any, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from api.control_plane import ControlPlane
from pipelines.orchestrator.contracts import QualityStatus, TelemetryUsage


ProgressStatus = Literal[
    "queued",
    "running",
    "waiting_for_approval",
    "waiting_for_input",
    "pending",
    "succeeded",
    "partial",
    "failed",
    "completed",
    "cancelled",
]


class ProgressEvent(BaseModel):
    """Stable, non-sensitive event contract sent to the frontend."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: f"evt-{uuid4()}")
    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    sequence: int | None = Field(default=None, ge=1)
    pipeline: str | None = None
    stage: str = Field(min_length=1)
    status: ProgressStatus
    progress: int = Field(default=0, ge=0, le=100)
    message: str = Field(default="", max_length=2000)
    requires_action: bool = False
    artifact_id: str | None = None
    error_code: str | None = None
    wait_reason: str = Field(default="", max_length=500)
    quality_status: QualityStatus = "pending"
    quality_report_id: str | None = None
    child_count: int = Field(default=0, ge=0)
    child_id: str | None = None
    skill_call_id: str | None = None
    provider: str | None = None
    model: str | None = None
    usage: TelemetryUsage | None = None
    cache_status: Literal["hit", "miss", "wait", "write", "not_applicable"] | None = None
    source_sequence: int | None = None
    node_id: str | None = None
    parent_node_id: str | None = None
    attempt_id: str | None = None
    lane_id: str | None = None
    fallback: bool = False
    provider_request_id: str | None = None
    usage_id: str | None = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ProgressSink(Protocol):
    """Application transport seam; implement with SSE, WebSocket, or a broker."""

    def publish(self, event: ProgressEvent) -> None:
        ...

    def events(self, run_id: str, *, after_sequence: int = 0) -> tuple[ProgressEvent, ...]:
        ...


class InMemoryProgressSink:
    """Thread-safe sink for tests and a single-process development server."""

    def __init__(self) -> None:
        self._events: dict[str, list[ProgressEvent]] = defaultdict(list)
        self._lock = Lock()

    def publish(self, event: ProgressEvent) -> None:
        with self._lock:
            sequence = len(self._events[event.run_id]) + 1
            self._events[event.run_id].append(event.model_copy(update={"sequence": sequence}))

    def events(self, run_id: str, *, after_sequence: int = 0) -> tuple[ProgressEvent, ...]:
        with self._lock:
            return tuple(
                event
                for event in self._events.get(run_id, ())
                if (event.sequence or 0) > after_sequence
            )

    def clear(self, run_id: str) -> None:
        with self._lock:
            self._events.pop(run_id, None)


class SQLiteProgressSink:
    """Durable frontend-safe progress events for a service deployment."""

    def __init__(self, db_path: str | None = None) -> None:
        configured = db_path or os.getenv(
            "SUDARSHAN_PROGRESS_DB_PATH", "artifacts/.state/progress_events.db"
        )
        self._db_path = configured
        os.makedirs(os.path.dirname(os.path.abspath(configured)), exist_ok=True)
        self._lock = Lock()
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS progress_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    event_json TEXT NOT NULL
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_progress_run ON progress_events(run_id, sequence)"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path, check_same_thread=False)

    def publish(self, event: ProgressEvent) -> None:
        payload = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO progress_events(run_id, event_json) VALUES (?, ?)",
                (event.run_id, payload),
            )
            sequence = int(cursor.lastrowid)
            persisted = event.model_copy(update={"sequence": sequence})
            conn.execute(
                "UPDATE progress_events SET event_json = ? WHERE sequence = ?",
                (json.dumps(persisted.model_dump(mode="json"), ensure_ascii=False), sequence),
            )

    def events(self, run_id: str, *, after_sequence: int = 0) -> tuple[ProgressEvent, ...]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT event_json FROM progress_events WHERE run_id = ? AND sequence > ? ORDER BY sequence",
                (run_id, after_sequence),
            ).fetchall()
        return tuple(ProgressEvent.model_validate(json.loads(row[0])) for row in rows)

    def clear(self, run_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM progress_events WHERE run_id = ?", (run_id,))


class RedisProgressSink:
    """Shared progress projection backed by the control-plane Redis adapter."""

    def __init__(self, control_plane: ControlPlane) -> None:
        self.control_plane = control_plane

    def publish(self, event: ProgressEvent) -> None:
        self.control_plane.publish_progress(
            event.run_id,
            event.model_dump(mode="json"),
        )

    def events(self, run_id: str, *, after_sequence: int = 0) -> tuple[ProgressEvent, ...]:
        return tuple(
            ProgressEvent.model_validate(payload)
            for payload in self.control_plane.progress_events(
                run_id,
                after_sequence=after_sequence,
            )
        )

    def clear(self, run_id: str) -> None:
        # Progress is an append-only operational record; retention is managed
        # by the Redis stream cap rather than destructive per-run deletes.
        del run_id


class ProgressReporter:
    """Bind a sink to one run and publish monotonic lifecycle notifications."""

    def __init__(self, sink: ProgressSink, *, run_id: str, task_id: str) -> None:
        self.sink = sink
        self.run_id = run_id
        self.task_id = task_id

    def emit(
        self,
        *,
        stage: str,
        status: ProgressStatus,
        progress: int,
        message: str,
        pipeline: str | None = None,
        requires_action: bool = False,
        artifact_id: str | None = None,
        error_code: str | None = None,
        wait_reason: str = "",
        quality_status: QualityStatus = "pending",
        quality_report_id: str | None = None,
        child_count: int = 0,
        child_id: str | None = None,
        skill_call_id: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        usage: TelemetryUsage | None = None,
        cache_status: Literal["hit", "miss", "wait", "write", "not_applicable"] | None = None,
        source_sequence: int | None = None,
        node_id: str | None = None,
        parent_node_id: str | None = None,
        attempt_id: str | None = None,
        lane_id: str | None = None,
        fallback: bool = False,
        provider_request_id: str | None = None,
        usage_id: str | None = None,
    ) -> ProgressEvent:
        event = ProgressEvent(
            run_id=self.run_id,
            task_id=self.task_id,
            pipeline=pipeline,
            stage=stage,
            status=status,
            progress=progress,
            message=message,
            requires_action=requires_action,
            artifact_id=artifact_id,
            error_code=error_code,
            wait_reason=wait_reason,
            quality_status=quality_status,
            quality_report_id=quality_report_id,
            child_count=child_count,
            child_id=child_id,
            skill_call_id=skill_call_id,
            provider=provider,
            model=model,
            usage=usage,
            cache_status=cache_status,
            source_sequence=source_sequence,
            node_id=node_id,
            parent_node_id=parent_node_id,
            attempt_id=attempt_id,
            lane_id=lane_id,
            fallback=fallback,
            provider_request_id=provider_request_id,
            usage_id=usage_id,
        )
        self.sink.publish(event)
        return event


def event_dict(event: ProgressEvent) -> dict[str, Any]:
    """Serialize an event for JSON/SSE responses."""

    return event.model_dump(mode="json")
