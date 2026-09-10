from __future__ import annotations

from pipelines.ppt.agents import build_agents
from pipelines.ppt.tasks import build_staged_tasks, build_tasks


def identity_callback(output):
    return output


class CallbackOnlyWriter:
    def callback(self, _step):
        return identity_callback


def test_legacy_ppt_tasks_remain_the_default(monkeypatch) -> None:
    monkeypatch.delenv("SUDARSHAN_PPT_FLOW", raising=False)
    agents = build_agents([])
    tasks = build_tasks(agents, CallbackOnlyWriter())
    assert list(tasks) == ["analysis", "output", "quality"]


def test_staged_ppt_tasks_have_typed_plan_and_visual_routing(monkeypatch) -> None:
    monkeypatch.setenv("SUDARSHAN_PPT_FLOW", "staged")
    agents = build_agents([])
    tasks = build_tasks(agents, CallbackOnlyWriter())
    assert list(tasks) == ["grounding", "plan", "visual_routing", "output", "quality"]
    assert tasks["plan"].output_pydantic.__name__ == "DeckPlan"
    assert tasks["visual_routing"].output_pydantic.__name__ == "DeckPlan"
