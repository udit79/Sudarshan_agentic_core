from __future__ import annotations

from crewai import BaseLLM

from pipelines.ppt.agents import build_agents
from pipelines.ppt.tasks import build_staged_tasks, build_tasks


def identity_callback(output):
    return output


class CallbackOnlyWriter:
    def callback(self, _step):
        return identity_callback


class OfflineLLM(BaseLLM):
    """Construction-only double; these tests never execute a model call."""

    def call(self, messages, tools=None, callbacks=None, available_functions=None, from_task=None, from_agent=None, response_model=None):
        return ""


def offline_llm() -> OfflineLLM:
    return OfflineLLM(model="offline/test-double", provider="offline")


def test_staged_ppt_tasks_are_the_default(monkeypatch) -> None:
    monkeypatch.delenv("SUDARSHAN_PPT_FLOW", raising=False)
    agents = build_agents([], llm=offline_llm())
    tasks = build_tasks(agents, CallbackOnlyWriter())
    assert list(tasks) == ["grounding", "plan", "visual_routing", "output", "quality"]


def test_staged_ppt_tasks_have_typed_plan_and_visual_routing(monkeypatch) -> None:
    monkeypatch.setenv("SUDARSHAN_PPT_FLOW", "staged")
    agents = build_agents([], llm=offline_llm())
    tasks = build_tasks(agents, CallbackOnlyWriter())
    assert list(tasks) == ["grounding", "plan", "visual_routing", "output", "quality"]
    assert tasks["plan"].output_pydantic.__name__ == "DeckPlan"
    assert tasks["visual_routing"].output_pydantic.__name__ == "DeckPlan"


def test_ppt_output_task_does_not_invent_unvalidated_template_ids(monkeypatch) -> None:
    monkeypatch.setenv("SUDARSHAN_PPT_FLOW", "staged")
    agents = build_agents([], llm=offline_llm())
    tasks = build_tasks(agents, CallbackOnlyWriter())

    assert "native-default" in tasks["output"].description
    assert "validated template contract" in tasks["output"].description
