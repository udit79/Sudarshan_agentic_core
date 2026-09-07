"""Stable contracts shared by application-specific pipelines.

These contracts deliberately depend on Sudarshan's memory policy rather than
on CrewAI. This keeps the pipeline boundary usable by the DeepSeek harness,
HTTP handlers, tests, and future orchestration implementations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

from memory.scope_policy import AccessContext
from pipelines.common.ntro_policy import require_classification, validate_distribution


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
    operation: Literal["create", "revise"] = "create"
    parent_run_id: str | None = None
    parent_artifact_id: str | None = None
    revision_instruction: str | None = None
    revision_scope: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    requested_pipelines: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("query", "user_id", "case_id", "task_id", "classification_level", "distribution"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        object.__setattr__(self, "classification_level", require_classification(self.classification_level))
        object.__setattr__(self, "distribution", validate_distribution(self.distribution))
        if self.top_k < 1:
            raise ValueError("top_k must be positive")
        if self.token_budget < 256:
            raise ValueError("token_budget must be at least 256")
        raw_pipelines = self.requested_pipelines
        if isinstance(raw_pipelines, str):
            raw_pipelines = (raw_pipelines,)
        if not isinstance(raw_pipelines, (list, tuple)):
            raise ValueError("requested_pipelines must be a list of pipeline names")
        pipelines = tuple(
            str(item).strip().lower()[:64]
            for item in raw_pipelines
            if str(item).strip()
        )
        if len(pipelines) > 8:
            raise ValueError("requested_pipelines cannot contain more than 8 pipelines")
        if len(set(pipelines)) != len(pipelines):
            raise ValueError("requested_pipelines cannot contain duplicates")
        object.__setattr__(self, "requested_pipelines", pipelines)
        if self.operation not in ("create", "revise"):
            raise ValueError("operation must be 'create' or 'revise'")
        if self.operation == "revise":
            if not (self.parent_run_id or self.parent_artifact_id):
                raise ValueError("revision requests require parent_run_id or parent_artifact_id")
            if not self.revision_instruction or not self.revision_instruction.strip():
                raise ValueError("revision requests require revision_instruction")
            object.__setattr__(self, "revision_instruction", self.revision_instruction.strip()[:4000])
        elif any((self.parent_run_id, self.parent_artifact_id, self.revision_instruction, self.revision_scope)):
            raise ValueError("revision fields require operation='revise'")
        raw_scope = self.revision_scope
        if isinstance(raw_scope, str):
            raw_scope = (raw_scope,)
        if not isinstance(raw_scope, (list, tuple)):
            raise ValueError("revision_scope must be a list of field names")
        scope = tuple(str(item).strip()[:120] for item in raw_scope if str(item).strip())
        if len(scope) > 20:
            raise ValueError("revision_scope cannot contain more than 20 fields")
        object.__setattr__(self, "revision_scope", scope)
        if not isinstance(self.metadata, Mapping):
            raise ValueError("metadata must be an object")
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
            "requested_pipelines": list(self.requested_pipelines),
            "operation": self.operation,
            "parent_run_id": self.parent_run_id,
            "parent_artifact_id": self.parent_artifact_id,
            "revision_instruction": self.revision_instruction,
            "revision_scope": list(self.revision_scope),
            "request_understanding": self.metadata.get("request_understanding", {}),
            "prompt_plan": self.metadata.get("prompt_plan", {}),
            "collaboration_plan": self.metadata.get("collaboration_plan", {}),
            "upstream_pipeline_results": self.metadata.get("upstream_pipeline_results", {}),
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
