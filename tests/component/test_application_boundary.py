from __future__ import annotations

from pipelines.video.contracts import VideoPackage
from pipelines import InMemoryProgressSink, ProgressEvent
from integrations.deepseek_harness.application import SudarshanApplication


def test_harness_exposes_lifecycle_tools() -> None:
    from integrations.deepseek_harness.mcp_server import mcp

    tools = mcp._tool_manager.list_tools()
    names = {tool.name for tool in tools}

    assert {
        "run_sudarshan",
        "start_sudarshan_run",
        "list_sudarshan_skills",
        "get_sudarshan_skill",
        "invoke_sudarshan_skill",
        "start_sudarshan_skill",
        "wait_sudarshan",
        "resume_sudarshan",
        "cancel_sudarshan",
        "get_sudarshan_status",
        "get_sudarshan_artifact",
        "get_sudarshan_usage",
    } <= names


def test_harness_tool_schemas_are_external_client_compatible() -> None:
    from integrations.deepseek_harness.mcp_server import mcp

    tools = {tool.name: tool for tool in mcp._tool_manager.list_tools()}

    run_parameters = tools["start_sudarshan_run"].parameters
    assert set(run_parameters["required"]) == {"query", "user_id", "case_id", "task_id"}
    assert run_parameters["properties"]["classification_level"]["default"] == "RESTRICTED"
    assert run_parameters["properties"]["distribution"]["default"] == "Authorized NTRO personnel"

    wait_parameters = tools["wait_sudarshan"].parameters["properties"]
    assert wait_parameters["timeout_ms"]["default"] == 30_000
    assert wait_parameters["after_sequence"]["default"] == 0

    artifact_parameters = tools["get_sudarshan_artifact"].parameters
    assert artifact_parameters["required"] == ["artifact_id"]
    assert artifact_parameters["properties"]["classification_level"]["default"] == "RESTRICTED"

    skill_parameters = tools["invoke_sudarshan_skill"].parameters
    assert {
        "skill_id",
        "parent_run_id",
        "parent_node_id",
        "user_id",
        "case_id",
        "task_id",
        "query",
    } <= set(skill_parameters["required"])
    start_skill_parameters = tools["start_sudarshan_skill"].parameters
    assert set(start_skill_parameters["required"]) == {
        "skill_id", "query", "user_id", "case_id", "task_id"
    }


def test_harness_adapter_allows_only_public_application_operations() -> None:
    from integrations.deepseek_harness.adapter import SudarshanHarnessAdapter

    class FakeApplication:
        def list_pipelines(self):
            return ["presentation"]

    adapter = SudarshanHarnessAdapter(lambda: FakeApplication())

    assert adapter.call("list_pipelines") == ["presentation"]
    try:
        adapter.call("_private_operation")  # type: ignore[arg-type]
    except ValueError as exc:
        assert "unsupported Harness operation" in str(exc)
    else:
        raise AssertionError("private application operations must not cross the adapter")


def test_video_package_compiles_storyboard_into_provider_options() -> None:
    package = VideoPackage.model_validate(
        {
            "subject": "Case briefing",
            "transcript": "Unused when a storyboard script exists.",
            "storyboard": [
                {
                    "scene_id": "scene-1",
                    "narration": "Verified opening statement.",
                    "visual_description": "A restrained briefing room.",
                },
                {
                    "scene_id": "scene-2",
                    "narration": "Validated next action.",
                    "visual_description": "A document review desk.",
                },
            ],
        }
    )

    payload = package.provider_payload()

    assert payload["video_script"] == (
        "Verified opening statement.\n\nValidated next action."
    )
    assert payload["video_terms"] == [
        "A restrained briefing room.",
        "A document review desk.",
    ]
    assert payload["match_materials_to_script"] is True


def test_video_package_falls_back_to_transcript_without_storyboard() -> None:
    package = VideoPackage(subject="Case briefing", transcript="Full source transcript")

    assert package.provider_payload()["video_script"] == "Full source transcript"


def test_video_package_keeps_native_renderer_controls_outside_legacy_payload() -> None:
    package = VideoPackage(
        subject="Case briefing",
        provider_options={
            "renderer_id": "video.moneyprinter-compatible",
            "render_profile": "cheap",
            "subtitle_mode": "scene",
            "bgm_path": "artifacts/video-bgm/calm.mp3",
            "video_transition": "fade",
        },
    )

    payload = package.provider_payload()

    assert payload["video_transition"] == "fade"
    assert "renderer_id" not in payload
    assert "render_profile" not in payload
    assert "subtitle_mode" not in payload
    assert "bgm_path" not in payload


def test_application_projects_typed_events_and_run_summary() -> None:
    application = object.__new__(SudarshanApplication)
    application.progress_sink = InMemoryProgressSink()
    application._run_contexts = {}
    application.progress_sink.publish(
        ProgressEvent(
            run_id="run-summary",
            task_id="task-summary",
            stage="planning",
            status="running",
            progress=20,
            message="Planning started",
        )
    )

    events = application.events("run-summary")
    summary = application._run_summary(
        {
            "run_id": "run-summary",
            "task_id": "task-summary",
            "case_id": "case-summary",
            "pipeline": "presentation",
            "requested_pipelines": ["presentation"],
            "status": "running",
            "stage": "planning",
            "request": {
                "case_id": "case-summary",
                "task_id": "task-summary",
                "metadata": {"skill_version": "2.0.0"},
            },
            "responses": {},
        },
        events,
    )

    assert events[0]["sequence"] == 1
    assert events[0]["status"] == "running"
    assert summary.skill_id == "presentation.case-brief"
    assert summary.skill_version == "2.0.0"
    assert summary.progress == 20


def test_application_projects_safe_harness_correlation_ids() -> None:
    application = object.__new__(SudarshanApplication)
    application.progress_sink = InMemoryProgressSink()
    application._run_contexts = {}
    summary = application._run_summary(
        {
            "run_id": "run-harness",
            "task_id": "task-harness",
            "case_id": "case-harness",
            "pipeline": "presentation",
            "status": "queued",
            "request": {
                "case_id": "case-harness",
                "task_id": "task-harness",
                "metadata": {
                    "harness_correlation": {
                        "session_id": "session-1",
                        "message_id": "message-1",
                        "tool_call_id": "tool-1",
                    },
                },
            },
            "responses": {},
        },
        [],
    )

    assert summary.harness_correlation is not None
    assert summary.harness_correlation.session_id == "session-1"
    assert summary.harness_correlation.message_id == "message-1"
    assert summary.harness_correlation.tool_call_id == "tool-1"


def test_harness_correlation_does_not_expose_arbitrary_metadata() -> None:
    from pipelines.orchestrator.contracts import HarnessCorrelation

    correlation = HarnessCorrelation.from_metadata({
        "harness_session_id": "session-flat",
        "api_key": "must-not-project",
        "prompt": "must-not-project",
    })

    assert correlation is not None
    assert correlation.model_dump(mode="json") == {
        "session_id": "session-flat",
        "message_id": None,
        "tool_call_id": None,
    }


def test_health_exposes_shared_control_plane_boundary() -> None:
    application = object.__new__(SudarshanApplication)
    application.control_plane = object()
    application.control_plane_mode = "redis"
    application.list_pipelines = lambda: ["presentation"]
    application.scheduler = type("Scheduler", (), {"metrics": lambda _self: {}})()
    application.ingestion_scheduler = type("Scheduler", (), {"metrics": lambda _self: {}})()

    health = application.health()

    assert health["control_plane"] == {
        "mode": "redis",
        "shared": True,
        "ingestion_stage_budget": "shared",
        "ingestion_stage_budget_next": None,
    }
