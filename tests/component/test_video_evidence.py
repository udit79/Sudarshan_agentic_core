from threading import Event

import pytest

from ingestion_pipelines.contracts import EvidenceBlock, VideoIngestionPolicy
from ingestion_pipelines.extract_video import (
    VideoEvent,
    VideoIngestionCancelled,
    extract_video_evidence,
    render_video_timeline,
)


def test_video_evidence_has_stable_scene_parents_and_time_ranges(tmp_path, monkeypatch):
    source = tmp_path / "brief.mp4"
    source.write_bytes(b"synthetic-video")

    monkeypatch.setattr(
        "ingestion_pipelines.extract_video._collect_video_events",
        lambda _path: (
            [
                VideoEvent(1.0, 2.5, "audio_transcript", "verified audio"),
                VideoEvent(6.0, 7.0, "video_ocr", "verified screen text"),
            ],
            10.0,
        ),
    )

    first = extract_video_evidence(
        str(source),
        document_id="doc-video-1",
        source_reference="brief.mp4",
        source_hash="sha256:" + "a" * 64,
    )
    second = extract_video_evidence(
        str(source),
        document_id="doc-video-1",
        source_reference="brief.mp4",
        source_hash="sha256:" + "a" * 64,
    )

    assert all(isinstance(block, EvidenceBlock) for block in first)
    assert [block.evidence_id for block in first] == [block.evidence_id for block in second]
    scenes = [block for block in first if block.modality == "video_scene"]
    events = [block for block in first if block.modality != "video_scene"]
    assert len(scenes) == 2
    assert len(events) == 2
    assert events[0].parent_id == scenes[0].evidence_id
    assert events[1].parent_id == scenes[1].evidence_id
    assert events[0].location.start_seconds == 1.0
    assert events[0].location.end_seconds == 2.5

    timeline = render_video_timeline(first, source_reference="brief.mp4")
    assert "[00:01] [Audio]: verified audio" in timeline
    assert "[00:06] [Visual]: verified screen text" in timeline


def test_video_evidence_legacy_ingestion_keeps_typed_blocks(tmp_path, monkeypatch):
    source = tmp_path / "brief.mp4"
    source.write_bytes(b"synthetic-video")
    monkeypatch.setattr(
        "ingestion_pipelines.extract_video._collect_video_events",
        lambda _path: ([VideoEvent(0.0, 1.0, "audio_transcript", "hello")], 1.0),
    )

    from ingestion_pipelines import ingest_file

    document = ingest_file(
        str(source),
        user_id="operator-1",
        case_id="case-1",
        task_id="task-video",
        source_reference="brief.mp4",
    )

    assert document.doc_type == "video"
    assert document.evidence_blocks
    assert "[00:00] [Audio]: hello" in document.raw_text
    assert document.evidence_blocks[1].parent_id == document.evidence_blocks[0].evidence_id


def test_video_provider_fallback_is_recorded_on_scene_evidence(tmp_path, monkeypatch):
    source = tmp_path / "brief.mp4"
    source.write_bytes(b"synthetic-video")

    def collect(_path, *, stage_charger=None, fallbacks=None):
        assert stage_charger is not None
        fallbacks.append("audio_provider_unavailable")
        return [], 2.0

    monkeypatch.setattr("ingestion_pipelines.extract_video._collect_video_events", collect)
    evidence = extract_video_evidence(
        str(source),
        document_id="doc-video-fallback",
        source_reference="brief.mp4",
        source_hash="sha256:" + "c" * 64,
        stage_charger=lambda *_args: None,
    )

    scenes = [block for block in evidence if block.modality == "video_scene"]
    assert scenes[0].metadata["fallbacks"] == ["audio_provider_unavailable"]


def test_video_ingestion_policy_is_recorded_and_caps_duration(tmp_path, monkeypatch):
    source = tmp_path / "brief.mp4"
    source.write_bytes(b"synthetic-video")
    policy = VideoIngestionPolicy(max_duration_seconds=5, max_visual_samples=2)

    def collect(_path, *, stage_charger=None, fallbacks=None, policy=None, cancel_event=None):
        assert policy.max_duration_seconds == 5
        return [VideoEvent(8.0, 9.0, "video_ocr", "outside cap")], 10.0

    monkeypatch.setattr("ingestion_pipelines.extract_video._collect_video_events", collect)
    evidence = extract_video_evidence(
        str(source),
        document_id="doc-video-policy",
        source_reference="brief.mp4",
        source_hash="sha256:" + "d" * 64,
        policy=policy,
    )

    scenes = [block for block in evidence if block.modality == "video_scene"]
    events = [block for block in evidence if block.modality != "video_scene"]
    assert scenes[0].location.end_seconds == 5.0
    assert not events
    assert scenes[0].metadata["ingestion_policy"]["max_visual_samples"] == 2


def test_video_ingestion_cancellation_is_cooperative(tmp_path):
    source = tmp_path / "brief.mp4"
    source.write_bytes(b"synthetic-video")
    cancel_event = Event()
    cancel_event.set()

    with pytest.raises(VideoIngestionCancelled):
        extract_video_evidence(
            str(source),
            document_id="doc-video-cancel",
            source_reference="brief.mp4",
            source_hash="sha256:" + "e" * 64,
            cancel_event=cancel_event,
        )
