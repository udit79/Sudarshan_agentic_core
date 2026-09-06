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
from pathlib import Path
import subprocess
import tempfile

import cv2
import imageio_ffmpeg

from ingestion_pipelines.config import load_env
from ingestion_pipelines.extract_image import extract_text_from_image

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}


def _format_timestamp(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _extract_audio_events(video_path: str, temp_dir: str) -> list[tuple[float, str]]:
    """Extracts audio track from video and transcribes with Whisper timestamps."""
    load_env()
    openai_key = os.environ.get("OPENAI_API_KEY")
    if not openai_key or openai_key.startswith("replace-"):
        print("   [Video Audio] OPENAI_API_KEY not configured, skipping Whisper audio track...", flush=True)
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
    from openai import OpenAI
    client = OpenAI(api_key=openai_key)

    events: list[tuple[float, str]] = []
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
                    events.append((start_time, f"[Audio]: {text}"))
        else:
            full_text = (transcription.text or "").strip()
            if full_text:
                events.append((0.0, f"[Audio]: {full_text}"))
    except Exception as err:
        print(f"   [Video Audio] Whisper transcription failed or skipped: {err}", flush=True)

    return events


def _extract_visual_frame_events(video_path: str, temp_dir: str, sample_interval_sec: float = 5.0) -> list[tuple[float, str]]:
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

    events: list[tuple[float, str]] = []
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
            extracted_text = extract_text_from_image(temp_frame_file).strip()
            # De-duplicate consecutive identical slides/frames
            if extracted_text and extracted_text not in seen_texts:
                seen_texts.add(extracted_text)
                events.append((t_sec, f"[Visual]: {extracted_text}"))
        except Exception as err:
            pass

    cap.release()
    return events


def extract_text_from_video(file_path: str) -> str:
    """Extracts synchronized audio transcription and on-screen visual text."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Source video not found: {file_path}")

    print(f"   [Video Processing] Analyzing '{path.name}' (Audio + Frames)...", flush=True)

    with tempfile.TemporaryDirectory() as temp_dir:
        audio_events = _extract_audio_events(str(path), temp_dir)
        visual_events = _extract_visual_frame_events(str(path), temp_dir)

    all_events = audio_events + visual_events
    all_events.sort(key=lambda x: x[0])

    header = f"=== VIDEO INTELLIGENCE TRANSCRIPT ===\nSource File: {path.name}"
    if not all_events:
        return f"{header}\n(No audible speech or on-screen text detected)"

    timeline_lines: list[str] = [header, ""]
    for t_sec, content in all_events:
        ts_str = f"[{_format_timestamp(t_sec)}]"
        timeline_lines.append(f"{ts_str} {content}")

    return "\n".join(timeline_lines).strip()
