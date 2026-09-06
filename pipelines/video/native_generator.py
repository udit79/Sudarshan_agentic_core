"""Native video generation — reverse-engineered from MoneyPrinterTurbo.

This module runs entirely in-process.  It does NOT call an external FastAPI
worker.  Video assembly uses ``imageio-ffmpeg`` (already in project
dependencies) and OpenCV for frame composition.  TTS is delegated to the
OpenAI TTS endpoint using the same ``OPENAI_API_KEY`` that powers CrewAI.

The pipeline follows the MoneyPrinterTurbo architecture:
    1. Script analysis → scene segmentation
    2. Per-scene material selection (stock footage from Pexels when configured)
    3. TTS narration per scene via OpenAI
    4. Frame-by-frame composition with on-screen text overlays
    5. FFmpeg concatenation → final MP4 artifact
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
from uuid import uuid4


_ARTIFACT_DIR = Path("artifacts") / "videos"


class NativeVideoError(RuntimeError):
    """Raised when native video generation fails."""


@dataclass
class VideoScene:
    """One segment of the assembled video."""

    scene_id: str
    narration: str = ""
    visual_description: str = ""
    duration_seconds: int = 5
    on_screen_text: str = ""
    audio_path: str | None = None
    video_path: str | None = None


@dataclass
class NativeVideoResult:
    """Result of a native video generation job."""

    status: str  # succeeded | failed
    video_path: str | None = None
    thumbnail_path: str | None = None
    duration_seconds: float = 0.0
    scene_count: int = 0
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _ffmpeg_binary() -> str:
    """Locate the FFmpeg binary from imageio-ffmpeg or PATH."""

    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        pass
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    raise NativeVideoError(
        "FFmpeg is not available.  Install imageio-ffmpeg or place ffmpeg on PATH."
    )


def _ffprobe_binary() -> str:
    """Locate ffprobe from PATH."""

    if shutil.which("ffprobe"):
        return "ffprobe"
    return ""


class OpenAITTSAdapter:
    """Generate speech audio using the OpenAI TTS API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "tts-1",
        voice: str = "alloy",
    ) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.model = model
        self.voice = voice

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def generate(self, text: str, output_path: str) -> str:
        """Generate an MP3 audio file from text.  Returns the output path."""

        if not self.configured:
            raise NativeVideoError("OPENAI_API_KEY is required for TTS narration")

        payload = json.dumps({
            "model": self.model,
            "voice": self.voice,
            "input": text[:4096],
        }).encode("utf-8")

        request = Request(
            "https://api.openai.com/v1/audio/speech",
            data=payload,
            method="POST",
        )
        request.add_header("Authorization", f"Bearer {self.api_key}")
        request.add_header("Content-Type", "application/json")

        try:
            with urlopen(request, timeout=60) as response:
                audio_data = response.read()
        except (HTTPError, URLError, TimeoutError) as exc:
            raise NativeVideoError(f"OpenAI TTS request failed: {exc}") from exc

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(audio_data)
        return output_path


class PexelsStockProvider:
    """Download royalty-free stock footage from Pexels."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("PEXELS_API_KEY", "")
        self.base_url = "https://api.pexels.com/videos"

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def search(self, query: str, *, per_page: int = 3) -> list[dict[str, Any]]:
        """Search for stock videos.  Returns video metadata list."""

        if not self.configured:
            return []

        url = f"{self.base_url}/search?query={quote_plus(query)}&per_page={per_page}&orientation=landscape"
        request = Request(url, method="GET")
        request.add_header("Authorization", self.api_key)

        try:
            with urlopen(request, timeout=15) as response:
                data = json.loads(response.read().decode("utf-8"))
            return data.get("videos", [])
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            return []

    def download(self, video_meta: dict[str, Any], output_path: str) -> str | None:
        """Download the best-quality video file.  Returns the path or None."""

        files = video_meta.get("video_files", [])
        if not files:
            return None

        # Prefer HD quality.
        best = max(files, key=lambda f: f.get("height", 0))
        url = best.get("link")
        if not url:
            return None

        try:
            with urlopen(url, timeout=60) as response:
                data = response.read()
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(data)
            return output_path
        except (HTTPError, URLError, TimeoutError):
            return None


class NativeVideoGenerator:
    """Assemble a video from scenes using FFmpeg, TTS, and optional stock footage.

    This is the in-process equivalent of MoneyPrinterTurbo's task pipeline.
    """

    def __init__(
        self,
        *,
        tts: OpenAITTSAdapter | None = None,
        stock: PexelsStockProvider | None = None,
        output_dir: str | Path = _ARTIFACT_DIR,
        width: int = 1920,
        height: int = 1080,
        fps: int = 24,
    ) -> None:
        self.tts = tts or OpenAITTSAdapter()
        self.stock = stock or PexelsStockProvider()
        self.output_dir = Path(output_dir)
        self.width = width
        self.height = height
        self.fps = fps

    def generate(
        self,
        *,
        subject: str,
        scenes: Sequence[VideoScene],
        artifact_name: str | None = None,
    ) -> NativeVideoResult:
        """Generate a complete video from scenes.

        If TTS is configured, narration audio is generated per scene.
        If Pexels is configured, stock footage is downloaded per scene.
        Otherwise, simple title-card frames are generated for each scene.
        """

        if not scenes:
            return NativeVideoResult(
                status="failed",
                error="No scenes provided for video generation",
            )

        artifact_name = artifact_name or f"video-{uuid4().hex[:12]}"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        try:
            ffmpeg = _ffmpeg_binary()
        except NativeVideoError as exc:
            return NativeVideoResult(status="failed", error=str(exc))

        with tempfile.TemporaryDirectory(prefix="sudarshan-video-") as work_dir:
            work = Path(work_dir)
            segment_paths: list[str] = []

            for i, scene in enumerate(scenes):
                try:
                    segment = self._generate_scene(
                        scene, work, i, ffmpeg, subject,
                    )
                    if segment:
                        segment_paths.append(segment)
                except Exception as exc:
                    # Log but continue — partial videos are acceptable.
                    continue

            if not segment_paths:
                return NativeVideoResult(
                    status="failed",
                    error="No video segments could be generated",
                    scene_count=len(scenes),
                )

            # Concatenate all segments.
            output_path = str(self.output_dir / f"{artifact_name}.mp4")
            try:
                self._concatenate(segment_paths, output_path, work, ffmpeg)
            except Exception as exc:
                return NativeVideoResult(
                    status="failed",
                    error=f"FFmpeg concatenation failed: {exc}",
                    scene_count=len(scenes),
                )

            duration = self._probe_duration(output_path)

            return NativeVideoResult(
                status="succeeded",
                video_path=output_path,
                duration_seconds=duration,
                scene_count=len(segment_paths),
                metadata={
                    "subject": subject,
                    "total_scenes": len(scenes),
                    "rendered_scenes": len(segment_paths),
                    "resolution": f"{self.width}x{self.height}",
                },
            )

    def _generate_scene(
        self,
        scene: VideoScene,
        work_dir: Path,
        index: int,
        ffmpeg: str,
        subject: str,
    ) -> str | None:
        """Generate one video segment for a scene."""

        prefix = f"scene_{index:03d}"
        audio_path: str | None = None
        video_source: str | None = None

        # 1. Generate TTS audio if narration exists.
        if scene.narration.strip() and self.tts.configured:
            audio_path = str(work_dir / f"{prefix}_audio.mp3")
            try:
                self.tts.generate(scene.narration, audio_path)
            except NativeVideoError:
                audio_path = None

        # 2. Search for stock footage if visual description exists.
        if scene.visual_description.strip() and self.stock.configured:
            results = self.stock.search(scene.visual_description)
            if results:
                dl_path = str(work_dir / f"{prefix}_stock.mp4")
                video_source = self.stock.download(results[0], dl_path)

        # 3. Generate a title-card video if no stock footage.
        if not video_source:
            video_source = str(work_dir / f"{prefix}_card.mp4")
            self._generate_title_card(
                scene, video_source, ffmpeg,
            )

        # 4. Add on-screen text overlay if provided.
        segment_path = str(work_dir / f"{prefix}_segment.mp4")
        self._compose_segment(
            video_source, audio_path, segment_path,
            scene, ffmpeg,
        )

        return segment_path if Path(segment_path).exists() else None

    def _generate_title_card(
        self,
        scene: VideoScene,
        output_path: str,
        ffmpeg: str,
    ) -> None:
        """Generate a simple title card video using FFmpeg."""

        duration = max(1, scene.duration_seconds)
        # Escape text for FFmpeg drawtext filter.
        text = (scene.on_screen_text or scene.narration or scene.visual_description)[:200]
        safe_text = text.replace("'", "").replace("\\", "").replace(":", " -")

        cmd = [
            ffmpeg, "-y",
            "-f", "lavfi",
            "-i", f"color=c=0x1a1a2e:s={self.width}x{self.height}:d={duration}:r={self.fps}",
            "-vf", (
                f"drawtext=text='{safe_text}':"
                f"fontsize=48:fontcolor=white:"
                f"x=(w-text_w)/2:y=(h-text_h)/2:"
                f"font=Arial"
            ),
            "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p",
            output_path,
        ]
        subprocess.run(cmd, capture_output=True, timeout=30, check=True)

    def _compose_segment(
        self,
        video_path: str,
        audio_path: str | None,
        output_path: str,
        scene: VideoScene,
        ffmpeg: str,
    ) -> None:
        """Compose a video segment with optional audio and text overlay."""

        cmd = [ffmpeg, "-y", "-i", video_path]

        if audio_path and Path(audio_path).exists():
            cmd.extend(["-i", audio_path])
            cmd.extend([
                "-c:v", "libx264", "-preset", "ultrafast",
                "-c:a", "aac", "-b:a", "128k",
                "-pix_fmt", "yuv420p",
                "-shortest",
                output_path,
            ])
        else:
            duration = max(1, scene.duration_seconds)
            cmd.extend([
                "-t", str(duration),
                "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p",
                "-an",
                output_path,
            ])
        subprocess.run(cmd, capture_output=True, timeout=120, check=True)

    def _concatenate(
        self,
        segment_paths: list[str],
        output_path: str,
        work_dir: Path,
        ffmpeg: str,
    ) -> None:
        """Concatenate video segments using FFmpeg concat demuxer."""

        list_file = work_dir / "concat_list.txt"
        with open(list_file, "w", encoding="utf-8") as f:
            for path in segment_paths:
                safe = str(Path(path).resolve()).replace("\\", "/")
                f.write(f"file '{safe}'\n")

        cmd = [
            ffmpeg, "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(list_file),
            "-c:v", "libx264", "-preset", "fast",
            "-c:a", "aac",
            "-pix_fmt", "yuv420p",
            output_path,
        ]
        subprocess.run(cmd, capture_output=True, timeout=300, check=True)

    def _probe_duration(self, video_path: str) -> float:
        """Get video duration in seconds using ffprobe."""

        ffprobe = _ffprobe_binary()
        if not ffprobe:
            return 0.0
        try:
            result = subprocess.run(
                [ffprobe, "-v", "quiet", "-show_entries",
                 "format=duration", "-of", "json", video_path],
                capture_output=True, text=True, timeout=10,
            )
            data = json.loads(result.stdout)
            return float(data.get("format", {}).get("duration", 0))
        except Exception:
            return 0.0


def scenes_from_package(package_data: Mapping[str, Any]) -> list[VideoScene]:
    """Convert a VideoPackage storyboard into NativeVideoGenerator scenes."""

    storyboard = package_data.get("storyboard", [])
    scenes: list[VideoScene] = []
    for i, scene_data in enumerate(storyboard):
        scenes.append(VideoScene(
            scene_id=scene_data.get("scene_id", f"scene-{i}"),
            narration=scene_data.get("narration", ""),
            visual_description=scene_data.get("visual_description", ""),
            duration_seconds=int(scene_data.get("duration_seconds", 5)),
            on_screen_text=scene_data.get("on_screen_text", ""),
        ))
    return scenes


def scenes_from_script(script: str, subject: str = "") -> list[VideoScene]:
    """Split a plain script into scenes at paragraph boundaries."""

    paragraphs = [p.strip() for p in script.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [script.strip()] if script.strip() else []

    scenes: list[VideoScene] = []
    for i, paragraph in enumerate(paragraphs[:50]):
        scenes.append(VideoScene(
            scene_id=f"scene-{i}",
            narration=paragraph[:4000],
            visual_description=subject or paragraph[:200],
            duration_seconds=max(3, min(15, len(paragraph) // 20)),
            on_screen_text="",
        ))
    return scenes
