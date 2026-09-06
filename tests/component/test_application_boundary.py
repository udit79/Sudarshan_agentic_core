from __future__ import annotations

from pipelines.video.contracts import VideoPackage


def test_harness_exposes_lifecycle_tools() -> None:
    from integrations.deepseek_harness.mcp_server import mcp

    tools = mcp._tool_manager.list_tools()
    names = {tool.name for tool in tools}

    assert {
        "run_sudarshan",
        "resume_sudarshan",
        "cancel_sudarshan",
        "get_sudarshan_status",
    } <= names


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
