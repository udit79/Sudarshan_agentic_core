"""Transport-neutral types for the central pipeline router."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Mapping, Protocol

from pipelines.common.contracts import AdvisoryRequest, PipelineResponse

PipelineName = Literal[
    "advisory",
    "linkedin_post",
    "executive_summary",
    "infographic",
    "ppt",
    "video",
]


class PipelineRunner(Protocol):
    def __call__(self, request: AdvisoryRequest) -> PipelineResponse:
        ...


class PipelineResumer(Protocol):
    def __call__(self, request: AdvisoryRequest, decision: Mapping[str, Any]) -> PipelineResponse:
        ...


@dataclass(frozen=True, slots=True)
class PipelineAdapter:
    """One registered pipeline and its optional external-approval resume seam."""

    name: str
    run: PipelineRunner
    resume: PipelineResumer | None = None


@dataclass(frozen=True, slots=True)
class OrchestrationResult:
    """Backend-facing result after a graph invocation or interruption."""

    status: Literal["succeeded", "failed", "pending"]
    run_id: str
    task_id: str
    pipeline: str | None
    response: PipelineResponse | None = None
    interrupt: Mapping[str, Any] | None = None
    state: Mapping[str, Any] = field(default_factory=dict)

    @property
    def requires_action(self) -> bool:
        return self.interrupt is not None


def response_to_dict(response: PipelineResponse | None) -> dict[str, Any] | None:
    if response is None:
        return None
    return {
        "status": response.status,
        "pipeline": response.pipeline,
        "task_id": response.task_id,
        "run_id": response.run_id,
        "output": _jsonable(response.output),
        "artifact": _jsonable(response.artifact),
        "failure": response.failure,
        "attempts": response.attempts,
        "metadata": _jsonable(response.metadata),
    }


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="json"))
    if hasattr(value, "__dict__"):
        return _jsonable(vars(value))
    return str(value)
