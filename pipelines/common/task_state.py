"""Serializable execution state for deterministic CrewAI Flows."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TaskEventStatus = Literal["started", "succeeded", "failed", "rejected", "retrying"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskEvent(BaseModel):
    """One auditable pipeline or agent lifecycle event."""

    model_config = ConfigDict(extra="forbid")

    step: str = Field(min_length=1)
    status: TaskEventStatus
    timestamp: str = Field(default_factory=utc_now_iso)
    summary: str = ""
    error: str | None = None
    attempt: int = Field(default=1, ge=1)


class TaskState(BaseModel):
    """Flow state; the CrewAI-generated state ID is the run identity."""

    model_config = ConfigDict(extra="ignore")

    query: str = ""
    pipeline_name: str = ""
    pipeline_options: dict[str, Any] = Field(default_factory=dict)
    run_id: str = ""
    user_id: str = ""
    case_id: str = ""
    task_id: str = ""
    classification_level: str = "RESTRICTED"
    distribution: str = "Authorized NTRO personnel"
    top_k: int = Field(default=12, ge=1)
    token_budget: int = Field(default=6000, ge=256)
    operation: Literal["create", "revise"] = "create"
    constraints: dict[str, Any] = Field(default_factory=dict)
    parent_run_id: str | None = None
    parent_artifact_id: str | None = None
    revision_instruction: str | None = None
    revision_scope: list[str] = Field(default_factory=list)
    memory_context: str = ""
    memory_records: list[dict[str, Any]] = Field(default_factory=list)
    request_understanding: dict[str, Any] = Field(default_factory=dict)
    prompt_plan: dict[str, Any] = Field(default_factory=dict)
    events: list[TaskEvent] = Field(default_factory=list)
    attempt: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=2, ge=1)
    status: Literal["created", "running", "succeeded", "failed", "incomplete"] = "created"
    advisory: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    quality_review: dict[str, Any] | None = None
    approval_status: Literal["not_requested", "pending", "approved", "rejected", "revision_requested"] = "not_requested"
    approval_feedback: str | None = None
    artifact: dict[str, Any] | None = None
    failure: str | None = None
    # Sanitized provider counters only; prompts and model output never enter
    # this state field.
    usage_records: list[dict[str, Any]] = Field(default_factory=list)

    def record(self, step: str, status: TaskEventStatus, *,
               summary: str = "", error: str | None = None) -> None:
        self.events.append(TaskEvent(step=step, status=status, summary=summary[:2000],
                                     error=error[:2000] if error else None,
                                     attempt=max(1, self.attempt)))
