"""Video Intelligence extractor implementing the "VIDEO = AUDIO + FRAMES" design.

Channels:
1. Audio -> Text: Extracts audio track via imageio-ffmpeg, transcribes speech
   with timestamps using OpenAI Whisper (whisper-1).
2. Visual -> Text: Samples keyframes periodically via OpenCV, runs each frame
   through our existing Vision OCR (extract_text_from_image).
3. Merged Timeline: Assembles a synchronized chronological intelligence log.
"""

from __future__ import annotations

import os
import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
import subprocess
import tempfile
from typing import Callable

import cv2
import imageio_ffmpeg

from ingestion_pipelines.config import load_env
from ingestion_pipelines.contracts import EvidenceBlock, EvidenceLocation
from ingestion_pipelines.extract_image import extract_text_from_image

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
VIDEO_EXTRACTOR_VERSION = "video-temporal@1.0.0"


@dataclass(frozen=True, slots=True)
class VideoEvent:
    """One timestamped parser observation before contract normalization."""

    start_seconds: float
    end_seconds: float
    channel: str
    content: str


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _evidence_id(source_hash: str, kind: str, index: int) -> str:
    digest = hashlib.sha256(f"{source_hash}|{kind}|{index}".encode("utf-8")).hexdigest()[:20]
    return f"video-{kind}-{digest}"


def _format_timestamp(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _extract_audio_events(
    video_path: str,
    temp_dir: str,
    *,
    stage_charger: Callable[[str, int, int, int], object] | None = None,
    fallbacks: list[str] | None = None,
) -> list[VideoEvent]:
    """Extracts audio track from video and transcribes with Whisper timestamps."""
    load_env()
    openai_key = os.environ.get("OPENAI_API_KEY")
    if not openai_key or openai_key.startswith("replace-"):
        print("   [Video Audio] OPENAI_API_KEY not configured, skipping Whisper audio track...", flush=True)
        if fallbacks is not None:
            fallbacks.append("audio_provider_unavailable")
        return []

    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    audio_path = os.path.join(temp_dir, "extracted_audio.mp3")

    # Extract audio track to mp3
    cmd = [
        ffmpeg_exe,
        "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "libmp3lame",
        "-ar", "16000",
        "-ac", "1",
        audio_path,
    ]
    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if res.returncode != 0 or not os.path.exists(audio_path) or os.path.getsize(audio_path) == 0:
        print("   [Video Audio] No audio track detected in video file.", flush=True)
        return []

    print("   [Video Audio] Transcribing speech track via OpenAI Whisper...", flush=True)
    if stage_charger is not None:
        stage_charger("summary", 1, 4096, 0)
    from openai import OpenAI
    client = OpenAI(api_key=openai_key)

    events: list[VideoEvent] = []
    try:
        with open(audio_path, "rb") as f:
            transcription = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="verbose_json",
            )
        # verbose_json provides segments with start, end, text
        segments = getattr(transcription, "segments", None)
        if segments:
            for seg in segments:
                start_time = float(seg.get("start", 0.0) if isinstance(seg, dict) else getattr(seg, "start", 0.0))
                text = (seg.get("text", "") if isinstance(seg, dict) else getattr(seg, "text", "")).strip()
                if text:
                    end_time = max(start_time, float(seg.get("end", start_time) if isinstance(seg, dict) else getattr(seg, "end", start_time)))
                    events.append(VideoEvent(start_time, end_time, "audio_transcript", text))
        else:
            full_text = (transcription.text or "").strip()
            if full_text:
                events.append(VideoEvent(0.0, 0.0, "audio_transcript", full_text))
    except Exception as err:
        print(f"   [Video Audio] Whisper transcription failed or skipped: {err}", flush=True)
        if fallbacks is not None:
            fallbacks.append("audio_provider_error")

    return events


def _extract_visual_frame_events(
    video_path: str,
    temp_dir: str,
    sample_interval_sec: float = 5.0,
    *,
    stage_charger: Callable[[str, int, int, int], object] | None = None,
    fallbacks: list[str] | None = None,
    usage_recorder: Callable[[str, str, str, int, int, bool], object] | None = None,
) -> list[VideoEvent]:
    """Samples keyframes and runs them through our vision extractor."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"   [Video Visual] Unable to open video: {video_path}", flush=True)
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_sec = total_frames / fps if fps > 0 else 0.0

    # Determine timestamps to sample (e.g. every sample_interval_sec, max 12 frames)
    if duration_sec <= 0:
        cap.release()
        return []

    sample_times = [i * sample_interval_sec for i in range(int(duration_sec // sample_interval_sec) + 1)]
    if len(sample_times) > 12:
        # Scale interval if video is very long
        step = len(sample_times) / 10
        sample_times = [sample_times[int(i * step)] for i in range(10)]

    print(f"   [Video Visual] Sampling {len(sample_times)} keyframes across {duration_sec:.1f}s...", flush=True)

    events: list[VideoEvent] = []
    seen_texts: set[str] = set()

    for t_sec in sample_times:
        frame_idx = int(t_sec * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret or frame is None:
            continue

        temp_frame_file = os.path.join(temp_dir, f"frame_{int(t_sec):04d}.jpg")
        cv2.imwrite(temp_frame_file, frame)

        try:
            extracted_text = extract_text_from_image(
                temp_frame_file,
                stage_charger=stage_charger,
                usage_recorder=usage_recorder,
            ).strip()
            # De-duplicate consecutive identical slides/frames
            if extracted_text and extracted_text not in seen_texts:
                seen_texts.add(extracted_text)
                events.append(
                    VideoEvent(
                        t_sec,
                        min(duration_sec, t_sec + sample_interval_sec),
                        "video_ocr",
                        extracted_text,
                    )
                )
        except Exception as err:
            if fallbacks is not None:
                fallbacks.append("vision_provider_error")
            pass

    cap.release()
    return events


def _video_duration_seconds(video_path: str) -> float:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return 0.0
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return total_frames / fps if fps > 0 else 0.0


def _collect_video_events(
    path: Path,
    *,
    stage_charger: Callable[[str, int, int, int], object] | None = None,
    fallbacks: list[str] | None = None,
    usage_recorder: Callable[[str, str, str, int, int, bool], object] | None = None,
) -> tuple[list[VideoEvent], float]:
    with tempfile.TemporaryDirectory() as temp_dir:
        audio_events = _extract_audio_events(
            str(path), temp_dir, stage_charger=stage_charger, fallbacks=fallbacks
        )
        visual_events = _extract_visual_frame_events(
            str(path),
            temp_dir,
            stage_charger=stage_charger,
            fallbacks=fallbacks,
            usage_recorder=usage_recorder,
        )
    events = audio_events + visual_events
    events.sort(key=lambda event: (event.start_seconds, event.channel, event.content))
    duration = _video_duration_seconds(str(path))
    if events:
        duration = max(duration, max(event.end_seconds for event in events))
    return events, duration


def extract_video_evidence(
    file_path: str,
    *,
    document_id: str,
    source_reference: str | None = None,
    source_hash: str | None = None,
    stage_charger: Callable[[str, int, int, int], object] | None = None,
    usage_recorder: Callable[[str, str, str, int, int, bool], object] | None = None,
) -> list[EvidenceBlock]:
    """Compile timestamped video observations into source-linked evidence.

    The legacy transcript is derived from these same blocks, preventing the
    compatibility path and the typed path from silently disagreeing.
    """

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Source video not found: {file_path}")

    print(f"   [Video Processing] Analyzing '{path.name}' (Audio + Frames)...", flush=True)
    resolved_hash = source_hash or _sha256_file(path)
    resolved_reference = source_reference or path.name
    fallbacks: list[str] = []
    if stage_charger is None:
        events, duration = _collect_video_events(path)
    else:
        collect_kwargs = {"stage_charger": stage_charger, "fallbacks": fallbacks}
        if usage_recorder is not None:
            collect_kwargs["usage_recorder"] = usage_recorder
        events, duration = _collect_video_events(path, **collect_kwargs)
    scene_window = max(5.0, duration / 12) if duration > 0 else 5.0
    scene_count = max(1, int(math.ceil(duration / scene_window))) if duration > 0 else 1

    blocks: list[EvidenceBlock] = []
    for scene_index in range(scene_count):
        start = scene_index * scene_window
        end = min(duration, (scene_index + 1) * scene_window) if duration > 0 else 0.0
        scene_id = _evidence_id(resolved_hash, "scene", scene_index)
        blocks.append(
            EvidenceBlock(
                evidence_id=scene_id,
                document_id=document_id,
                modality="video_scene",
                content=(
                    f"Scene {scene_index + 1}: {_format_timestamp(start)}"
                    f"–{_format_timestamp(end)}"
                ),
                location=EvidenceLocation(start_seconds=start, end_seconds=end),
                confidence=0.6,
                source_hash=resolved_hash,
                extractor_version=VIDEO_EXTRACTOR_VERSION,
                provenance={
                    "source_reference": resolved_reference,
                    "parser_step": "temporal-scene-window",
                },
                metadata={
                    "scene_index": scene_index,
                    "duration_seconds": duration,
                    "fallbacks": sorted(set(fallbacks)),
                },
            )
        )

    for index, event in enumerate(events):
        scene_index = min(int(event.start_seconds // scene_window), scene_count - 1)
        blocks.append(
            EvidenceBlock(
                evidence_id=_evidence_id(resolved_hash, event.channel, index),
                document_id=document_id,
                parent_id=_evidence_id(resolved_hash, "scene", scene_index),
                modality=event.channel,
                content=event.content,
                location=EvidenceLocation(
                    start_seconds=event.start_seconds,
                    end_seconds=event.end_seconds,
                ),
                confidence=0.9 if event.channel == "audio_transcript" else 0.65,
                source_hash=resolved_hash,
                extractor_version=VIDEO_EXTRACTOR_VERSION,
                model_version="whisper-1" if event.channel == "audio_transcript" else None,
                provenance={
                    "source_reference": resolved_reference,
                    "parser_step": event.channel,
                },
                metadata={
                    "scene_index": scene_index,
                    "timestamped": True,
                },
            )
        )
    return blocks


def render_video_timeline(
    evidence_blocks: list[EvidenceBlock],
    *,
    source_reference: str,
) -> str:
    """Render the legacy transcript view from typed evidence blocks."""

    header = f"=== VIDEO INTELLIGENCE TRANSCRIPT ===\nSource File: {source_reference}"
    event_blocks = [block for block in evidence_blocks if block.modality != "video_scene"]
    if not event_blocks:
        return f"{header}\n(No audible speech or on-screen text detected)"

    timeline_lines: list[str] = [header, ""]
    for block in sorted(
        event_blocks,
        key=lambda item: (item.location.start_seconds or 0.0, item.evidence_id),
    ):
        label = "Audio" if block.modality == "audio_transcript" else "Visual"
        timestamp = _format_timestamp(block.location.start_seconds or 0.0)
        timeline_lines.append(f"[{timestamp}] [{label}]: {block.content}")
    return "\n".join(timeline_lines).strip()


def extract_text_from_video(file_path: str) -> str:
    """Compatibility transcript derived from the typed video evidence."""

    path = Path(file_path)
    evidence = extract_video_evidence(file_path, document_id="compatibility-video")
    return render_video_timeline(evidence, source_reference=path.name)
