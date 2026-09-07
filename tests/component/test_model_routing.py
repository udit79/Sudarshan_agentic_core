from __future__ import annotations

from crewai import TaskOutput
from memory import AccessContext, MemoryManager
from pipelines.common.model_routing import resolve_model
from pipelines.common.memory_tools import MemoryRuntime, TaskMemoryWriter
from pipelines.video.contracts import VideoPackage
from pipelines.video.crew import VideoCrewResult, VideoPlanningCrew, VideoQualityReview
from pipelines.video.planner import CrewAIVideoPlanner, VideoPlanningError


def test_model_routing_uses_strong_and_fast_tiers(monkeypatch):
    monkeypatch.delenv("VIDEO_SCRIPT_MODEL", raising=False)
    monkeypatch.setenv("CREWAI_MODEL", "openai/strong-test")
    monkeypatch.setenv("CREWAI_FAST_MODEL", "openai/fast-test")

    assert resolve_model("video_script") == "openai/strong-test"
    assert resolve_model("video_evidence") == "openai/fast-test"
    assert resolve_model("video_quality") == "openai/strong-test"


def test_crewai_video_planner_accepts_reviewed_package():
    package = VideoPackage(
        subject="Case briefing",
        title="Case briefing",
        script="Verified facts.",
        storyboard=[
            {
                "scene_id": "scene-1",
                "narration": "Verified facts.",
                "visual_description": "A restrained briefing room.",
                "duration_seconds": 5,
            }
        ],
    )

    class FakeCrew:
        def run(self, **kwargs):
            assert kwargs["subject"] == "Case briefing"
            return VideoCrewResult(
                package=package,
                quality=VideoQualityReview(approved=True),
            )

    planner = CrewAIVideoPlanner(crew_factory=lambda **kwargs: FakeCrew())
    result = planner.plan(
        subject="Case briefing",
        query="Create a briefing",
        memory_context="Verified facts only.",
    )

    assert result.subject == "Case briefing"
    assert result.storyboard[0].scene_id == "scene-1"


def test_crewai_video_planner_rejects_failed_quality_gate():
    package = VideoPackage(subject="Case briefing", script="Verified facts.")

    class FakeCrew:
        def run(self, **kwargs):
            return VideoCrewResult(
                package=package,
                quality=VideoQualityReview(approved=False, issues=["missing visual brief"]),
            )

    planner = CrewAIVideoPlanner(crew_factory=lambda **kwargs: FakeCrew())
    try:
        planner.plan(
            subject="Case briefing",
            query="Create a briefing",
            memory_context="Verified facts only.",
        )
    except VideoPlanningError as exc:
        assert "missing visual brief" in str(exc)
    else:
        raise AssertionError("quality rejection was not enforced")


def test_crewai_video_planner_retries_quality_rejection_with_feedback():
    package = VideoPackage(subject="Case briefing", script="Verified facts.")
    attempts: list[dict] = []

    class FakeCrew:
        def run(self, **kwargs):
            attempts.append(kwargs)
            if len(attempts) == 1:
                return VideoCrewResult(
                    package=package,
                    quality=VideoQualityReview(
                        approved=False,
                        required_revisions=["add a visual brief"],
                    ),
                )
            return VideoCrewResult(
                package=package,
                quality=VideoQualityReview(approved=True),
            )

    planner = CrewAIVideoPlanner(
        crew_factory=lambda **kwargs: FakeCrew(),
        max_attempts=2,
    )
    result = planner.plan(
        subject="Case briefing",
        query="Create a briefing",
        memory_context="Verified facts only.",
    )

    assert result.subject == "Case briefing"
    assert len(attempts) == 2
    assert attempts[1]["prompt_plan"]["quality_feedback"] == ["add a visual brief"]


def test_video_planning_crew_activates_task_writer(monkeypatch, recording_backend):
    import pipelines.video.crew as video_crew

    class FakeCrew:
        def __init__(self, *, tasks, **_kwargs):
            self.tasks = tasks

        def kickoff(self, *, inputs):
            assert inputs["subject"] == "Case briefing"
            for task in self.tasks:
                task.callback(
                    TaskOutput(
                        description="video task",
                        expected_output="JSON",
                        raw="{}",
                        agent="test-agent",
                    )
                )
            self.tasks[2].output = TaskOutput(
                description="storyboard",
                expected_output="VideoPackage",
                raw="{}",
                agent="test-agent",
                pydantic=VideoPackage(subject="Case briefing", script="Verified facts."),
            )
            self.tasks[3].output = TaskOutput(
                description="quality",
                expected_output="VideoQualityReview",
                raw="{}",
                agent="test-agent",
                pydantic=VideoQualityReview(approved=True),
            )

    class FakeAgent:
        def __init__(self, **_kwargs):
            pass

    class FakeTask:
        def __init__(self, **kwargs):
            self.callback = kwargs.get("callback")
            self.output = None

    monkeypatch.setattr(video_crew, "Crew", FakeCrew)
    monkeypatch.setattr(video_crew, "Agent", FakeAgent)
    monkeypatch.setattr(video_crew, "Task", FakeTask)
    writer = TaskMemoryWriter(
        MemoryRuntime(
            manager=MemoryManager(recording_backend),
            context=AccessContext(user_id="user-1", case_id="case-1", task_id="task-1"),
            task_id="task-1",
            case_id="case-1",
            run_id="run-1",
            pipeline_name="video",
        )
    )

    result = VideoPlanningCrew().run(
        subject="Case briefing",
        query="Create a briefing",
        memory_context="Verified facts only.",
        task_writer=writer,
    )

    assert result.quality.approved is True
    assert [write["metadata"]["step"] for write in recording_backend.writes] == [
        "video_evidence",
        "video_script",
        "video_storyboard",
        "video_quality",
    ]
