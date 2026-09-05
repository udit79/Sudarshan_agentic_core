"""Stable contracts shared by application-specific pipelines.

These contracts deliberately depend on Sudarshan's memory policy rather than
on CrewAI. This keeps the pipeline boundary usable by the DeepSeek harness,
HTTP handlers, tests, and future orchestration implementations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

from memory.scope_policy import AccessContext


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True, slots=True)
class AdvisoryRequest:
    """Input for one NTRO advisory operation.

    The task ID is mandatory because every CrewAI run must be auditable in
    task-scoped memory. ``query`` describes the operation, not merely a raw
    search string, so recall can remain task-oriented.
    """

    query: str
    user_id: str
    case_id: str
    task_id: str
    classification_level: str = "RESTRICTED"
    distribution: str = "Authorized NTRO personnel"
    top_k: int = 12
    token_budget: int = 6000
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("query", "user_id", "case_id", "task_id", "classification_level", "distribution"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if self.top_k < 1:
            raise ValueError("top_k must be positive")
        if self.token_budget < 256:
            raise ValueError("token_budget must be at least 256")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def access_context(self) -> AccessContext:
        return AccessContext(user_id=self.user_id, case_id=self.case_id, task_id=self.task_id)

    def as_inputs(self) -> dict[str, Any]:
        """Return safe, non-secret values for CrewAI interpolation."""

        return {
            "query": self.query,
            "user_id": self.user_id,
            "case_id": self.case_id,
            "task_id": self.task_id,
            "classification_level": self.classification_level,
            "distribution": self.distribution,
            "request_understanding": self.metadata.get("request_understanding", {}),
            "prompt_plan": self.metadata.get("prompt_plan", {}),
        }


@dataclass(frozen=True, slots=True)
class PipelineResponse:
    """Transport-neutral result returned to the harness/application."""

    status: Literal["succeeded", "failed", "pending"]
    pipeline: str
    task_id: str
    run_id: str
    output: Any = None
    artifact: Any = None
    failure: str | None = None
    attempts: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", dict(self.metadata))
        if self.status == "succeeded" and self.output is None:
            raise ValueError("successful pipeline responses require output")
        if self.status == "failed" and not self.failure:
            raise ValueError("failed pipeline responses require failure")
