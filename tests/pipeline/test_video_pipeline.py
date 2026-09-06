"""Tests for the native video pipeline."""

import pytest
from unittest.mock import patch, MagicMock

from pipelines.video.native_generator import (
    VideoScene, 
    scenes_from_script, 
    scenes_from_package,
    NativeVideoGenerator,
    NativeVideoResult
)


def test_scenes_from_script():
    script = "This is paragraph one.\n\nThis is paragraph two."
    scenes = scenes_from_script(script, subject="Test Subject")
    
    assert len(scenes) == 2
    assert scenes[0].narration == "This is paragraph one."
    assert scenes[0].visual_description == "Test Subject"
    assert scenes[1].narration == "This is paragraph two."


def test_scenes_from_package():
    package_data = {
        "storyboard": [
            {
                "scene_id": "scene-0",
                "narration": "Intro",
                "visual_description": "Map view",
                "duration_seconds": 4
            },
            {
                "scene_id": "scene-1",
                "narration": "Details",
                "visual_description": "Close up",
                "on_screen_text": "Important"
            }
        ]
    }
    
    scenes = scenes_from_package(package_data)
    assert len(scenes) == 2
    assert scenes[0].duration_seconds == 4
    assert scenes[1].on_screen_text == "Important"


@patch("pipelines.video.native_generator._ffmpeg_binary")
@patch("pipelines.video.native_generator.subprocess.run")
def test_native_video_generator_fallback(mock_run, mock_ffmpeg):
    # Mock ffmpeg binary
    mock_ffmpeg.return_value = "ffmpeg"
    
    # Mock subprocess runs to just return success without generating files
    mock_run.return_value = MagicMock(returncode=0, stdout='{"format": {"duration": "10"}}')
    
    # Needs to patch out the actual file checks since we are mocking subprocess
    with patch("pathlib.Path.exists", return_value=True):
        generator = NativeVideoGenerator()
        scenes = [
            VideoScene(scene_id="1", narration="test", duration_seconds=5)
        ]
        
        # Test basic title card fallback execution path
        result = generator.generate(subject="test", scenes=scenes)
        assert result.status == "succeeded"
        assert result.scene_count == 1
