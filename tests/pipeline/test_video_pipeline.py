"""Tests for the native video pipeline."""

import pytest
import threading
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

from pipelines.video.native_generator import (
    VideoScene, 
    scenes_from_script, 
    scenes_from_package,
    NativeVideoGenerator,
    NativeVideoResult
)


class _QuotaImageGenerator:
    configured = True

    def generate(self, prompt, output_path, *, cancel_event=None):
        del prompt, output_path, cancel_event
        raise RuntimeError("insufficient_quota: exceeded your current quota")


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
def test_native_video_generator_fallback(mock_run, mock_ffmpeg, tmp_path):
    # Mock ffmpeg binary
    mock_ffmpeg.return_value = "ffmpeg"
    
    # Mock subprocess runs to just return success without generating files
    mock_run.return_value = MagicMock(returncode=0, stdout='{"format": {"duration": "10"}}')
    
    # Needs to patch out the actual file checks since we are mocking subprocess
    with patch("pathlib.Path.exists", return_value=True):
        generator = NativeVideoGenerator(output_dir=tmp_path / "videos")
        scenes = [
            VideoScene(scene_id="1", narration="test", duration_seconds=5)
        ]
        
        # Test basic title card fallback execution path
        result = generator.generate(subject="test", scenes=scenes)
        assert result.status == "succeeded"
        assert result.scene_count == 1


@patch("pipelines.video.native_generator._ffmpeg_binary")
@patch("pipelines.video.native_generator.subprocess.run")
def test_video_image_quota_uses_title_card_and_reports_degradation(mock_run, mock_ffmpeg, tmp_path):
    mock_ffmpeg.return_value = "ffmpeg"
    mock_run.return_value = MagicMock(returncode=0, stdout='{"format": {"duration": "10"}}')

    with patch("pathlib.Path.exists", return_value=True):
        generator = NativeVideoGenerator(
            output_dir=tmp_path / "videos",
            image_generator=_QuotaImageGenerator(),
        )
        result = generator.generate(
            subject="Quota fallback",
            scenes=[VideoScene(scene_id="quota-scene", visual_description="A map")],
        )

    assert result.status == "succeeded"
    assert result.metadata["degraded"] is True
    assert result.metadata["degradation_reasons"][0]["image_failure_class"] == "quota_exhausted"
    assert result.metadata["degradation_reasons"][0]["image_fallback"] == "title_card"


def test_video_scene_fingerprint_is_stable_and_changes_with_scene_inputs() -> None:
    scene = VideoScene(scene_id="scene-1", narration="Verified", duration_seconds=5)
    first = NativeVideoGenerator.scene_fingerprint("subject", scene, renderer_version="renderer@1")
    second = NativeVideoGenerator.scene_fingerprint("subject", scene, renderer_version="renderer@1")
    changed = NativeVideoGenerator.scene_fingerprint(
        "subject", VideoScene(scene_id="scene-1", narration="Verified", duration_seconds=6), renderer_version="renderer@1"
    )
    assert first == second
    assert first != changed


def test_native_video_generator_resumes_successful_scenes_and_bounds_parallelism(tmp_path) -> None:
    active = 0
    peak = 0
    calls: list[str] = []
    lock = threading.Lock()
    generator = NativeVideoGenerator(output_dir=tmp_path / "videos", max_parallel_scenes=2)

    def fake_scene(scene, work_dir, index, ffmpeg, subject, package_root, cancel_event):
        nonlocal active, peak
        del work_dir, ffmpeg, subject, cancel_event
        with lock:
            active += 1
            peak = max(peak, active)
            calls.append(scene.scene_id)
        time.sleep(0.03)
        output = Path(package_root) / "segments" / f"scene_{index:03d}.mp4"
        output.write_bytes(scene.scene_id.encode("utf-8"))
        scene.video_path = str(output)
        with lock:
            active -= 1
        return str(output)

    def fake_concat(segment_paths, output_path, work_dir, ffmpeg, cancel_event):
        del work_dir, ffmpeg, cancel_event
        Path(output_path).write_bytes("|".join(segment_paths).encode("utf-8"))

    generator._generate_scene = fake_scene
    generator._concatenate = fake_concat
    generator._probe_duration = lambda _path: 10.0

    scenes = [VideoScene(scene_id=f"scene-{index}", narration=f"scene {index}") for index in range(4)]
    first = generator.generate(subject="Synthetic video", scenes=scenes, artifact_name="resume-test")
    assert first.status == "succeeded"
    assert peak <= 2
    assert sorted(calls) == [f"scene-{index}" for index in range(4)]
    first_call_count = len(calls)

    second = generator.generate(
        subject="Synthetic video",
        scenes=[VideoScene(scene_id=f"scene-{index}", narration=f"scene {index}") for index in range(4)],
        artifact_name="resume-test",
    )
    assert second.status == "succeeded"
    assert len(calls) == first_call_count
    assert second.metadata["cache_hits"] == 4
    assert second.metadata["failed_scene_ids"] == []
