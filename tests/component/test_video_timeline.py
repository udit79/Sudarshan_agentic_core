from pipelines.video.native_generator import VideoScene
from pipelines.video.timeline import build_video_timeline


def test_video_timeline_tracks_scene_assets_and_fallbacks(tmp_path):
    image = tmp_path / "scene.png"
    image.write_bytes(b"image")
    timeline = build_video_timeline(
        "run-1",
        "Brief",
        [
            VideoScene(
                scene_id="scene-1",
                duration_seconds=4,
                image_path=str(image),
                material_references=["source://map-1"],
            ),
            VideoScene(scene_id="scene-2", duration_seconds=3, image_fallback="title_card"),
        ],
        renderer_version="video@1",
        status="partial",
    )
    assert timeline.clips[1].start_seconds == 4
    assert timeline.clips[1].end_seconds == 7
    assert timeline.assets[0].status == "verified"
    assert any(asset.status == "fallback" for asset in timeline.assets)
    assert any(asset.kind == "material" for asset in timeline.assets)
