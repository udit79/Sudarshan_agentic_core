from __future__ import annotations

import json

from pipelines.video.planner import OpenAIVideoPlanner


class FakeCompletions:
    def create(self, **kwargs):
        assert kwargs["response_format"] == {"type": "json_object"}
        return type(
            "Response",
            (),
            {
                "choices": [
                    type(
                        "Choice",
                        (),
                        {
                            "message": type(
                                "Message",
                                (),
                                {
                                    "content": json.dumps(
                                        {
                                            "title": "Case briefing",
                                            "script": "Verified opening.\n\nVerified close.",
                                            "storyboard": [
                                                {
                                                    "scene_id": "scene-1",
                                                    "narration": "Verified opening.",
                                                    "visual_description": "A restrained briefing room.",
                                                    "duration_seconds": 5,
                                                    "on_screen_text": "Opening",
                                                },
                                                {
                                                    "scene_id": "scene-2",
                                                    "narration": "Verified close.",
                                                    "visual_description": "A document review desk.",
                                                    "duration_seconds": 5,
                                                    "on_screen_text": "Conclusion",
                                                },
                                            ],
                                            "video_terms": ["briefing room", "document review"],
                                        }
                                    )
                                },
                            )
                        },
                    )
                ]
            },
        )


class FakeOpenAI:
    chat = type("Chat", (), {"completions": FakeCompletions()})()


def test_openai_video_planner_returns_validated_package():
    package = OpenAIVideoPlanner(client=FakeOpenAI(), model="gpt-test").plan(
        subject="Case briefing",
        query="Create a concise case video",
        memory_context="Only verified facts.",
        prompt_plan={"audience": "briefing"},
    )

    assert package.subject == "Case briefing"
    assert package.title == "Case briefing"
    assert len(package.storyboard) == 2
    assert package.storyboard[0].duration_seconds == 5
