"""Controlled CrewAI tools and callbacks for Sudarshan memory.

Agents never receive a Cognee client. They receive a narrow recall tool bound
to the current ``AccessContext``. Task writes are performed by callbacks and
the Flow, keeping memory ownership in ``MemoryManager``.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Protocol

from crewai import TaskOutput
from crewai.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from memory import AccessContext, KnowledgeUnit, MemoryType, ScopeType, Source, SourceType


_ACTIVE_TASK_WRITER: ContextVar["TaskMemoryWriter | None"] = ContextVar(
    "active_task_writer", default=None
)


class MemoryManagerLike(Protocol):
    """Narrow memory boundary required by orchestration and pipeline code.

    The concrete :class:`memory.MemoryManager` implements this protocol. Keeping
    the pipeline boundary structural also lets component tests provide a small,
    deterministic memory double without pretending it is a Cognee-backed manager.
    """

    def recall(self, *args: Any, **kwargs: Any) -> Any:
        ...

    def remember(self, *args: Any, **kwargs: Any) -> Any:
        ...


class RecallMemoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2000, description="The operation-focused memory question")


@dataclass(frozen=True, slots=True)
class MemoryRuntime:
    manager: MemoryManagerLike
    context: AccessContext
    task_id: str
    case_id: str
    run_id: str
    attempt_id: str | None = None
    lease_token: str | None = None
    attempt: int = 1
    top_k: int = 12
    token_budget: int = 6000
    pipeline_name: str = "ntro_advisory"
    query: str = ""
    prompt_plan: dict[str, Any] = field(default_factory=dict)
    compact_task_context: bool = False


class RecallSudarshanMemoryTool(BaseTool):
    """Recall memory only within the current user/case/task access boundary."""

    name: str = "recall_sudarshan_memory"
    description: str = (
        "Recall relevant case, user, and current-task memory for the advisory. "
        "Results include bounded context and provenance; never access Cognee directly."
    )
    args_schema: type[BaseModel] = RecallMemoryInput
    _runtime: MemoryRuntime = PrivateAttr()

    def __init__(self, runtime: MemoryRuntime, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._runtime = runtime

    def _run(self, query: str) -> str:
        response = self._runtime.manager.recall(
            query=query,
            context=self._runtime.context,
            top_k=self._runtime.top_k,
            token_budget=self._runtime.token_budget,
            session_id=self._runtime.run_id,
        )
        return response.context.text or "No relevant memory was found in the permitted scopes."


class TaskMemoryWriter:
    """Write auditable task events through MemoryManager, never through Cognee."""

    def __init__(
        self,
        runtime: MemoryRuntime,
        on_error: Callable[[str], None] | None = None,
        on_event: Callable[[str, str], None] | None = None,
        on_usage: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.runtime = runtime
        self._sequence = 0
        self._on_error = on_error
        self._on_event = on_event
        self._on_usage = on_usage

    def record_usage(self, step: str, usage: dict[str, Any]) -> None:
        """Publish sanitized stage usage without persisting raw task output."""

        if self._on_usage:
            try:
                self._on_usage(step, dict(usage))
            except Exception:
                return

    def write(self, step: str, status: str, content: str, *, metadata: dict[str, Any] | None = None) -> None:
        self._sequence += 1
        event_id = f"{self.runtime.task_id}:{self.runtime.run_id}:{self.runtime.attempt}:{self._sequence}"
        unit = KnowledgeUnit(
            unit_id=event_id,
            content=f"[{step}] {status}\n{content[:10000]}",
            source=Source(
                source_id=self.runtime.run_id,
                source_type=SourceType.TEXT,
                source_reference=f"pipeline://{self.runtime.pipeline_name}/{self.runtime.run_id}/{step}",
            ),
            metadata={"pipeline": self.runtime.pipeline_name, "step": step, "status": status, **(metadata or {})},
            provenance={"task_id": self.runtime.task_id, "case_id": self.runtime.case_id, "run_id": self.runtime.run_id},
        )
        try:
            self.runtime.manager.remember(
                unit,
                self.runtime.context,
                scope_type=ScopeType.TASK,
                memory_type=MemoryType.EVENT,
            )
        except Exception as exc:
            message = f"task memory write failed for {step}: {exc}"
            if self._on_error:
                self._on_error(message)
            raise
        if self._on_event:
            try:
                self._on_event(step, status)
            except Exception:
                # Progress delivery must never turn a successful agent step
                # into a failed pipeline run.
                return

    def callback(self, step: str) -> Callable[[TaskOutput], TaskOutput]:
        """Return a module-level callback so CrewAI can checkpoint task config."""

        callbacks: dict[str, Callable[[TaskOutput], TaskOutput]] = {
            "intelligence_analyst": intelligence_analyst_callback,
            "provenance_reviewer": provenance_reviewer_callback,
            "advisory_writer": advisory_writer_callback,
            "quality_critic": quality_critic_callback,
            "linkedin_case_analyst": linkedin_case_analyst_callback,
            "linkedin_evidence_review": linkedin_evidence_review_callback,
            "linkedin_post_writer": linkedin_post_writer_callback,
            "linkedin_humanizer": linkedin_humanizer_callback,
            "linkedin_quality_critic": linkedin_quality_critic_callback,
            "executive_case_analyst": executive_case_analyst_callback,
            "executive_evidence_review": executive_evidence_review_callback,
            "executive_summary_writer": executive_summary_writer_callback,
            "executive_quality_critic": executive_quality_critic_callback,
            "infographic_case_analyst": infographic_case_analyst_callback,
            "infographic_evidence_review": infographic_evidence_review_callback,
            "infographic_syntax_writer": infographic_syntax_writer_callback,
            "infographic_quality_critic": infographic_quality_critic_callback,
            "ppt_content_analyst": ppt_content_analyst_callback,
            "ppt_grounding": ppt_grounding_callback,
            "ppt_deck_planner": ppt_deck_planner_callback,
            "ppt_visual_router": ppt_visual_router_callback,
            "ppt_slide_content": ppt_slide_content_callback,
            "ppt_staged_quality_critic": ppt_staged_quality_critic_callback,
            "ppt_presentation_writer": ppt_presentation_writer_callback,
            "ppt_quality_critic": ppt_quality_critic_callback,
        }
        try:
            return callbacks[step]
        except KeyError as exc:
            raise ValueError(f"unsupported task callback step: {step}") from exc

    @contextmanager
    def activate(self) -> Iterator[None]:
        token = _ACTIVE_TASK_WRITER.set(self)
        try:
            yield
        finally:
            _ACTIVE_TASK_WRITER.reset(token)


def _record_task_output(step: str, output: TaskOutput) -> TaskOutput:
    writer = _ACTIVE_TASK_WRITER.get()
    if writer is None:
        raise RuntimeError("task memory callback invoked without an active pipeline run")
    from pipelines.common.usage_capture import capture_task_usage

    writer.record_usage(step, capture_task_usage(output, stage=step))
    structured = getattr(output, "pydantic", None)
    if writer.runtime.compact_task_context and structured is not None and hasattr(structured, "model_dump_json"):
        compacted = structured.model_dump_json()
        output.raw = compacted
        if hasattr(output, "json_dict"):
            output.json_dict = structured.model_dump(mode="json")
    if structured is not None and hasattr(structured, "model_dump_json"):
        content = structured.model_dump_json()
    else:
        content = getattr(output, "raw", str(output))
    writer.write(step, "succeeded", content)
    return output


def intelligence_analyst_callback(output: TaskOutput) -> TaskOutput:
    return _record_task_output("intelligence_analyst", output)


def provenance_reviewer_callback(output: TaskOutput) -> TaskOutput:
    return _record_task_output("provenance_reviewer", output)


def advisory_writer_callback(output: TaskOutput) -> TaskOutput:
    return _record_task_output("advisory_writer", output)


def quality_critic_callback(output: TaskOutput) -> TaskOutput:
    return _record_task_output("quality_critic", output)


def linkedin_case_analyst_callback(output: TaskOutput) -> TaskOutput:
    return _record_task_output("linkedin_case_analyst", output)


def linkedin_evidence_review_callback(output: TaskOutput) -> TaskOutput:
    return _record_task_output("linkedin_evidence_review", output)


def linkedin_post_writer_callback(output: TaskOutput) -> TaskOutput:
    return _record_task_output("linkedin_post_writer", output)


def linkedin_humanizer_callback(output: TaskOutput) -> TaskOutput:
    return _record_task_output("linkedin_humanizer", output)


def linkedin_quality_critic_callback(output: TaskOutput) -> TaskOutput:
    return _record_task_output("linkedin_quality_critic", output)


def executive_case_analyst_callback(output: TaskOutput) -> TaskOutput:
    return _record_task_output("executive_case_analyst", output)


def executive_evidence_review_callback(output: TaskOutput) -> TaskOutput:
    return _record_task_output("executive_evidence_review", output)


def executive_summary_writer_callback(output: TaskOutput) -> TaskOutput:
    return _record_task_output("executive_summary_writer", output)


def executive_quality_critic_callback(output: TaskOutput) -> TaskOutput:
    return _record_task_output("executive_quality_critic", output)


def infographic_case_analyst_callback(output: TaskOutput) -> TaskOutput:
    return _record_task_output("infographic_case_analyst", output)


def infographic_evidence_review_callback(output: TaskOutput) -> TaskOutput:
    return _record_task_output("infographic_evidence_review", output)


def infographic_syntax_writer_callback(output: TaskOutput) -> TaskOutput:
    writer = _ACTIVE_TASK_WRITER.get()
    structured = getattr(output, "pydantic", None)
    if writer is not None and structured is not None:
        from pipelines.infographic.normalization import normalize_infographic_output

        repaired = normalize_infographic_output(
            structured,
            query=writer.runtime.query,
        )
        output.pydantic = repaired
        output.json_dict = repaired.model_dump(mode="json")
        output.raw = repaired.model_dump_json()
    return _record_task_output("infographic_syntax_writer", output)


def infographic_quality_critic_callback(output: TaskOutput) -> TaskOutput:
    return _record_task_output("infographic_quality_critic", output)


def ppt_content_analyst_callback(output: TaskOutput) -> TaskOutput:
    return _record_task_output("ppt_content_analyst", output)


def ppt_grounding_callback(output: TaskOutput) -> TaskOutput:
    return _record_task_output("ppt_grounding", output)


def ppt_deck_planner_callback(output: TaskOutput) -> TaskOutput:
    return _record_task_output("ppt_deck_planner", output)


def ppt_visual_router_callback(output: TaskOutput) -> TaskOutput:
    return _record_task_output("ppt_visual_router", output)


def ppt_slide_content_callback(output: TaskOutput) -> TaskOutput:
    return _record_task_output("ppt_slide_content", output)


def ppt_staged_quality_critic_callback(output: TaskOutput) -> TaskOutput:
    return _record_task_output("ppt_staged_quality_critic", output)


def ppt_presentation_writer_callback(output: TaskOutput) -> TaskOutput:
    return _record_task_output("ppt_presentation_writer", output)


def ppt_quality_critic_callback(output: TaskOutput) -> TaskOutput:
    return _record_task_output("ppt_quality_critic", output)


def memory_tools(runtime: MemoryRuntime) -> list[BaseTool]:
    """Return the only memory capability available to CrewAI agents."""

    return [RecallSudarshanMemoryTool(runtime)]
