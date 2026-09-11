from pipelines.video.contracts import VideoScene
from pipelines.video.media import MaterialResolver, select_music, write_scene_subtitles
from pipelines.video.quality import inspect_video
from pipelines.video.evaluation import benchmark_video_observations


def test_material_resolver_is_deterministic_and_scoped(tmp_path):
    material_dir = tmp_path / "materials"
    material_dir.mkdir()
    candidate = material_dir / "checkpoint-map.mp4"
    candidate.write_bytes(b"video")

    resolved = MaterialResolver(material_dir=material_dir).resolve(
        VideoScene(scene_id="scene-1", visual_description="checkpoint map")
    )

    assert resolved is not None
    assert resolved.provider == "local"
    assert resolved.path == str(candidate.resolve())
    assert resolved.license_scope == "local-material-policy"


def test_scene_subtitles_and_local_music_are_typed(tmp_path):
    subtitle_path = tmp_path / "subtitles.srt"
    track = write_scene_subtitles(
        [VideoScene(scene_id="one", narration="Verified narration", duration_seconds=3)],
        subtitle_path,
    )
    assert track.cue_count == 1
    assert "00:00:00,000 --> 00:00:03,000" in subtitle_path.read_text(encoding="utf-8")

    music_dir = tmp_path / "music"
    music_dir.mkdir()
    music = music_dir / "calm.mp3"
    music.write_bytes(b"audio")
    selected = select_music(None, music_dir=music_dir)
    assert selected is not None
    assert selected.checksum.startswith("sha256:")


def test_video_quality_gate_reports_missing_output(tmp_path):
    report = inspect_video(tmp_path / "missing.mp4")
    assert report.status == "failed"
    assert "output_missing_or_empty" in report.failures


def test_video_benchmark_promotes_only_quality_gated_renderer():
    report = benchmark_video_observations([
        {"renderer_id": "native", "quality_status": "passed", "latency_seconds": 3},
        {"renderer_id": "native", "quality_status": "passed", "latency_seconds": 4},
        {"renderer_id": "mpt-compatible", "quality_status": "partial", "latency_seconds": 1},
    ])
    assert report.promoted_renderer == "native"
    assert report.by_renderer["mpt-compatible"]["pass_rate"] == 0.0
