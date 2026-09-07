"""Transport-neutral types for the central pipeline router."""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Any, Literal, Mapping, Protocol

from pipelines.common.contracts import AdvisoryRequest, PipelineResponse
from pipelines.common.ntro_policy import validate_ntro_response

# Plugin names are deliberately open-ended. Built-in names are documented by
# their packages; the central router must not need a code change for plugins.
PipelineName = str


class PipelineRunner(Protocol):
    def __call__(self, request: AdvisoryRequest) -> PipelineResponse:
        ...


class PipelineResumer(Protocol):
    def __call__(self, request: AdvisoryRequest, decision: Mapping[str, Any]) -> PipelineResponse:
        ...


@dataclass(frozen=True, slots=True)
class PipelineAdapter:
    """Plugin contract for one pipeline and its optional resume seam.

    A pipeline plugin owns its CrewAI flow, schemas, rendering, and memory
    write-back. The central router only depends on this transport-neutral
    contract.
    """

    name: str
    run: PipelineRunner
    resume: PipelineResumer | None = None


class PipelineRegistry(dict[str, PipelineAdapter]):
    """Explicit registry that makes third-party pipeline plugins easy to add."""

    def register(self, adapter: PipelineAdapter, *, replace: bool = False) -> "PipelineRegistry":
        if not adapter.name.strip():
            raise ValueError("pipeline adapter name must be non-empty")
        if adapter.name in self and not replace:
            raise ValueError(f"Pipeline '{adapter.name}' is already registered")
        self[adapter.name] = adapter
        return self

    def register_many(
        self,
        adapters: Mapping[str, PipelineAdapter],
        *,
        replace: bool = False,
    ) -> "PipelineRegistry":
        for name, adapter in adapters.items():
            if name != adapter.name:
                raise ValueError(f"Registry key '{name}' does not match adapter name '{adapter.name}'")
            self.register(adapter, replace=replace)
        return self


def load_pipeline_plugins(
    registry: PipelineRegistry,
    *,
    group: str = "sudarshan.pipelines",
) -> PipelineRegistry:
    """Load installed pipeline registrars from Python package entry points.

    A plugin entry point may expose ``register(registry)`` and either mutate
    the registry or return a ``PipelineAdapter``/mapping of adapters.
    Discovery is opt-in so deployments control exactly which code is loaded.
    """

    for plugin in entry_points(group=group):
        registrar = plugin.load()
        if isinstance(registrar, PipelineAdapter):
            registry.register(registrar)
            continue
        if not callable(registrar):
            raise TypeError(f"Pipeline plugin '{plugin.name}' must expose a callable registrar")
        returned = registrar(registry)
        if isinstance(returned, PipelineAdapter):
            registry.register(returned)
        elif isinstance(returned, Mapping):
            registry.register_many(returned)
    return registry

@dataclass(frozen=True, slots=True)
class OrchestrationResult:
    """Backend-facing result after a graph invocation or interruption."""

    status: Literal["succeeded", "failed", "pending", "partial", "cancelled"]
    run_id: str
    task_id: str
    pipeline: str | None
    response: PipelineResponse | None = None
    responses: Mapping[str, PipelineResponse] = field(default_factory=dict)
    pipelines: tuple[str, ...] = ()
    interrupt: Mapping[str, Any] | None = None
    state: Mapping[str, Any] = field(default_factory=dict)

    @property
    def requires_action(self) -> bool:
        return self.interrupt is not None


def response_to_dict(response: PipelineResponse | None) -> dict[str, Any] | None:
    if response is None:
        return None
    return validate_ntro_response({
        "status": response.status,
        "pipeline": response.pipeline,
        "task_id": response.task_id,
        "run_id": response.run_id,
        "output": _jsonable(response.output),
        "artifact": _jsonable(response.artifact),
        "failure": response.failure,
        "attempts": response.attempts,
        "metadata": _jsonable(response.metadata),
    })


def orchestration_result_to_dict(result: OrchestrationResult) -> dict[str, Any]:
    """Serialize a parent run, including every fan-out child result."""

    return {
        "status": result.status,
        "run_id": result.run_id,
        "task_id": result.task_id,
        "pipeline": result.pipeline,
        "pipelines": list(result.pipelines),
        "response": response_to_dict(result.response),
        "responses": {
            name: response_to_dict(response)
            for name, response in result.responses.items()
        },
        "interrupt": _jsonable(result.interrupt),
        "state": _public_state(result.state),
    }


def _public_state(state: Mapping[str, Any]) -> dict[str, Any]:
    """Project internal graph state without returning raw memory or prompts."""

    allowed = {
        "run_id",
        "task_id",
        "pipeline",
        "requested_pipelines",
        "understanding",
        "clarification_required",
        "clarification_questions",
        "response",
        "responses",
        "approval_decision",
        "error",
        "stage",
        "status",
    }
    return {key: _jsonable(state[key]) for key in allowed if key in state}


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
