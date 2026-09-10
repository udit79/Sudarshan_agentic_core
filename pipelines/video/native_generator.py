"""Native video generation — reverse-engineered from MoneyPrinterTurbo.

This module runs entirely in-process.  It does NOT call an external FastAPI
worker. Video assembly uses ``imageio-ffmpeg`` (already in project
dependencies). Scene images and narration are generated through OpenAI, then
FFmpeg writes a durable media package and final MP4 locally.

The pipeline follows the MoneyPrinterTurbo architecture:
    1. Script analysis → scene segmentation
    2. Per-scene image generation via OpenAI Images
    3. TTS narration per scene via OpenAI
    4. Per-scene MP4 composition with optional on-screen text overlays
    5. FFmpeg concatenation → final MP4 artifact plus manifest
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import base64
import time
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from pipelines.video.contracts import VideoRunManifest, VideoSceneManifest


_ARTIFACT_DIR = Path("artifacts") / "videos"


class NativeVideoError(RuntimeError):
    """Raised when native video generation fails."""


class NativeVideoCancelled(NativeVideoError):
    """Raised when a native media operation observes a cancellation signal."""


@dataclass
class VideoScene:
    """One segment of the assembled video."""

    scene_id: str
    narration: str = ""
    visual_description: str = ""
    duration_seconds: int = 5
    on_screen_text: str = ""
    image_path: str | None = None
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
        model: str | None = None,
        voice: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.model = model or os.getenv("OPENAI_TTS_MODEL", "tts-1")
        self.voice = voice or os.getenv("OPENAI_TTS_VOICE", "alloy")
        self.timeout_seconds = timeout_seconds or float(os.getenv("OPENAI_TTS_TIMEOUT_SECONDS", "60"))

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def generate(self, text: str, output_path: str, *, cancel_event: Event | None = None) -> str:
        """Generate an MP3 audio file from text.  Returns the output path."""

        if not self.configured:
            raise NativeVideoError("OPENAI_API_KEY is required for TTS narration")
        if cancel_event is not None and cancel_event.is_set():
            raise NativeVideoCancelled("video generation cancelled before TTS")

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
            with urlopen(request, timeout=self.timeout_seconds) as response:
                audio_data = response.read()
        except (HTTPError, URLError, TimeoutError) as exc:
            raise NativeVideoError(f"OpenAI TTS request failed: {exc}") from exc

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(audio_data)
        return output_path


class OpenAIImageAdapter:
    """Generate durable scene images through OpenAI's Images API."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        client: Any = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.model = model or os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
        self._client = client
        self.timeout_seconds = timeout_seconds or float(os.getenv("OPENAI_IMAGE_TIMEOUT_SECONDS", "90"))

    @property
    def configured(self) -> bool:
        return bool(self.api_key) or self._client is not None

    @property
    def client(self) -> Any:
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(api_key=self.api_key, timeout=self.timeout_seconds)
        return self._client

    def generate(self, prompt: str, output_path: str, *, cancel_event: Event | None = None) -> str:
        if not self.configured:
            raise NativeVideoError("OPENAI_API_KEY is required for scene image generation")
        if cancel_event is not None and cancel_event.is_set():
            raise NativeVideoCancelled("video generation cancelled before image generation")
        response = self.client.images.generate(
            model=self.model,
            prompt=(
                "Create a restrained, factual, government-quality visual for a case briefing. "
                "Do not add logos, seals, invented people, statistics, labels, or readable text. "
                f"Visual brief: {prompt[:2000]}"
            ),
            size="1536x1024",
            quality="high",
            output_format="png",
        )
        image = response.data[0]
        encoded = getattr(image, "b64_json", None)
        if encoded:
            data = base64.b64decode(encoded)
        else:
            url = getattr(image, "url", None)
            if not url:
                raise NativeVideoError("OpenAI Images returned neither image data nor a URL")
            with urlopen(url, timeout=self.timeout_seconds) as response_stream:
                data = response_stream.read()
        if cancel_event is not None and cancel_event.is_set():
            raise NativeVideoCancelled("video generation cancelled after image generation")
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(data)
        return output_path


class NativeVideoGenerator:
    """Assemble a video from scenes using OpenAI media and local FFmpeg.

    This is the in-process video implementation. The ``stock`` argument is
    intentionally absent: the supported media provider is OpenAI, while all
    composition and package persistence remain local.
    """

    def __init__(
        self,
        *,
        tts: OpenAITTSAdapter | None = None,
        image_generator: OpenAIImageAdapter | None = None,
        output_dir: str | Path | None = None,
        width: int = 1920,
        height: int = 1080,
        fps: int = 24,
        max_parallel_scenes: int | None = None,
        renderer_version: str | None = None,
    ) -> None:
        self.tts = tts or OpenAITTSAdapter()
        self.image_generator = image_generator or OpenAIImageAdapter()
        self.output_dir = Path(output_dir or os.getenv("SUDARSHAN_VIDEO_ARTIFACT_DIR", str(_ARTIFACT_DIR)))
        self.width = width
        self.height = height
        self.fps = fps
        self.max_parallel_scenes = max_parallel_scenes or int(os.getenv("SUDARSHAN_VIDEO_MAX_PARALLEL_SCENES", "4"))
        if self.max_parallel_scenes < 1 or self.max_parallel_scenes > 16:
            raise ValueError("max_parallel_scenes must be between 1 and 16")
        self.renderer_version = renderer_version or os.getenv("SUDARSHAN_VIDEO_RENDERER_VERSION", "native-video@2")

    def generate(
        self,
        *,
        subject: str,
        scenes: Sequence[VideoScene],
        artifact_name: str | None = None,
        package_dir: str | Path | None = None,
        cancel_event: Event | None = None,
        authorization_scope: Mapping[str, Any] | None = None,
    ) -> NativeVideoResult:
        """Generate a complete video from scenes.

        If OpenAI media is configured, narration audio and scene images are
        generated per scene. Without an image response, a local title card is
        used so the package remains renderable and inspectable.
        """

        if not scenes:
            return NativeVideoResult(
                status="failed",
                error="No scenes provided for video generation",
            )

        artifact_name = artifact_name or f"video-{uuid4().hex[:12]}"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        package_root = Path(package_dir) if package_dir else self.output_dir / artifact_name
        package_root.mkdir(parents=True, exist_ok=True)
        (package_root / "images").mkdir(exist_ok=True)
        (package_root / "audio").mkdir(exist_ok=True)
        (package_root / "segments").mkdir(exist_ok=True)

        try:
            ffmpeg = _ffmpeg_binary()
        except NativeVideoError as exc:
            return NativeVideoResult(status="failed", error=str(exc))

        manifest_path = package_root / "video-manifest.json"
        manifest = self._load_or_create_manifest(manifest_path, artifact_name, subject, scenes, authorization_scope)
        manifest.status = "rendering"
        self._persist_manifest(manifest_path, manifest)
        with tempfile.TemporaryDirectory(prefix="sudarshan-video-") as work_dir:
            work = Path(work_dir)
            segment_paths, failed_scene_ids, cache_hits = self._render_scene_batch(
                scenes,
                manifest,
                manifest_path,
                work,
                ffmpeg,
                subject,
                package_root,
                cancel_event,
                authorization_scope,
            )

            if not segment_paths:
                manifest.status = "cancelled" if cancel_event is not None and cancel_event.is_set() else "failed"
                manifest.failed_scene_ids = failed_scene_ids
                self._persist_manifest(manifest_path, manifest)
                return NativeVideoResult(
                    status="failed",
                    error="No video segments could be generated",
                    scene_count=len(scenes),
                    metadata={"manifest_path": str(manifest_path), "failed_scene_ids": failed_scene_ids},
                )

            # Concatenate all segments.
            # Keep the final render inside the same durable package as its
            # source script, storyboard, scene media, and manifest.
            output_path = str(package_root / "final.mp4")
            manifest.status = "composing"
            manifest.segment_order = [scene.scene_id for scene in scenes if scene.video_path and Path(scene.video_path).exists()]
            self._persist_manifest(manifest_path, manifest)
            try:
                self._concatenate(segment_paths, output_path, work, ffmpeg, cancel_event)
            except Exception as exc:
                manifest.status = "failed"
                manifest.failed_scene_ids = failed_scene_ids
                self._persist_manifest(manifest_path, manifest)
                return NativeVideoResult(
                    status="failed",
                    error=f"FFmpeg concatenation failed: {exc}",
                    scene_count=len(scenes),
                    metadata={"manifest_path": str(manifest_path), "failed_scene_ids": failed_scene_ids},
                )

            duration = self._probe_duration(output_path)
            manifest.status = "partial" if failed_scene_ids else "succeeded"
            manifest.output_video = output_path
            manifest.failed_scene_ids = failed_scene_ids
            self._persist_manifest(manifest_path, manifest)

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
                    "package_dir": str(package_root),
                    "manifest_path": str(manifest_path),
                    "cache_hits": cache_hits,
                    "failed_scene_ids": failed_scene_ids,
                    "degraded": bool(failed_scene_ids),
                    "scenes": [
                        {
                            "scene_id": scene.scene_id,
                            "narration": scene.narration,
                            "visual_description": scene.visual_description,
                            "duration_seconds": scene.duration_seconds,
                            "on_screen_text": scene.on_screen_text,
                            "image_path": scene.image_path,
                            "audio_path": scene.audio_path,
                            "video_path": scene.video_path,
                        }
                        for scene in scenes
                    ],
                },
            )

    def _render_scene_batch(
        self,
        scenes: Sequence[VideoScene],
        manifest: VideoRunManifest,
        manifest_path: Path,
        work: Path,
        ffmpeg: str,
        subject: str,
        package_root: Path,
        cancel_event: Event | None,
        authorization_scope: Mapping[str, Any] | None,
    ) -> tuple[list[str], list[str], int]:
        """Render missing scenes concurrently and preserve storyboard order."""

        entries = {entry.scene_id: entry for entry in manifest.scenes}
        segment_by_scene: dict[str, str] = {}
        failed_scene_ids: list[str] = []
        cache_hits = 0
        futures = {}

        with ThreadPoolExecutor(max_workers=min(self.max_parallel_scenes, len(scenes)), thread_name_prefix="sudarshan-video-scene") as pool:
            for index, scene in enumerate(scenes):
                self._check_cancelled(cancel_event)
                fingerprint = self.scene_fingerprint(
                    subject,
                    scene,
                    renderer_version=self.renderer_version,
                    authorization_scope=authorization_scope,
                )
                entry = entries.get(scene.scene_id)
                if entry is not None and entry.fingerprint == fingerprint and entry.status == "succeeded" and entry.video_path and Path(entry.video_path).is_file():
                    scene.video_path = entry.video_path
                    scene.image_path = entry.image_path
                    scene.audio_path = entry.audio_path
                    segment_by_scene[scene.scene_id] = entry.video_path
                    cache_hits += 1
                    continue
                entry = VideoSceneManifest(
                    scene_id=scene.scene_id,
                    fingerprint=fingerprint,
                    status="running",
                    attempt=(entry.attempt + 1 if entry is not None else 1),
                    duration_seconds=scene.duration_seconds,
                )
                entries[scene.scene_id] = entry
                manifest.scenes = [entries[item.scene_id] for item in scenes]
                self._persist_manifest(manifest_path, manifest)
                futures[pool.submit(self._generate_scene, scene, work, index, ffmpeg, subject, package_root, cancel_event)] = (scene, entry)

            for future in as_completed(futures):
                scene, entry = futures[future]
                try:
                    segment = future.result()
                    if not segment:
                        raise NativeVideoError("scene renderer returned no segment")
                    entry.status = "succeeded"
                    entry.video_path = segment
                    entry.image_path = scene.image_path
                    entry.audio_path = scene.audio_path
                    entry.error = None
                    segment_by_scene[scene.scene_id] = segment
                except NativeVideoCancelled:
                    entry.status = "cancelled"
                    entry.error = "scene generation cancelled"
                    self._persist_manifest(manifest_path, manifest)
                    raise
                except Exception as exc:
                    entry.status = "failed"
                    entry.error = str(exc)[:1000]
                    failed_scene_ids.append(scene.scene_id)
                finally:
                    manifest.scenes = [entries[item.scene_id] for item in scenes]
                    self._persist_manifest(manifest_path, manifest)

        ordered_paths = [segment_by_scene[scene.scene_id] for scene in scenes if scene.scene_id in segment_by_scene]
        return ordered_paths, failed_scene_ids, cache_hits

    @staticmethod
    def scene_fingerprint(
        subject: str,
        scene: VideoScene,
        *,
        renderer_version: str | None = None,
        authorization_scope: Mapping[str, Any] | None = None,
    ) -> str:
        """Hash only scene inputs and renderer/provider versions, never raw cache output."""

        payload = {
            "subject": subject,
            "scene_id": scene.scene_id,
            "narration": scene.narration,
            "visual_description": scene.visual_description,
            "duration_seconds": scene.duration_seconds,
            "on_screen_text": scene.on_screen_text,
            "renderer_version": renderer_version or os.getenv("SUDARSHAN_VIDEO_RENDERER_VERSION", "native-video@2"),
            "tts_model": os.getenv("OPENAI_TTS_MODEL", "tts-1"),
            "tts_voice": os.getenv("OPENAI_TTS_VOICE", "alloy"),
            "image_model": os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1"),
            "authorization_scope": dict(authorization_scope or {}),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _load_or_create_manifest(
        self,
        path: Path,
        run_id: str,
        subject: str,
        scenes: Sequence[VideoScene],
        authorization_scope: Mapping[str, Any] | None,
    ) -> VideoRunManifest:
        if path.is_file():
            try:
                loaded = VideoRunManifest.model_validate_json(path.read_text(encoding="utf-8"))
                if loaded.run_id == run_id and loaded.subject == subject and loaded.renderer_version == self.renderer_version:
                    return loaded
            except Exception:
                pass
        return VideoRunManifest(
            run_id=run_id,
            subject=subject,
            renderer_version=self.renderer_version,
            scenes=[
                VideoSceneManifest(
                    scene_id=scene.scene_id,
                    fingerprint=self.scene_fingerprint(
                        subject,
                        scene,
                        renderer_version=self.renderer_version,
                        authorization_scope=authorization_scope,
                    ),
                    duration_seconds=scene.duration_seconds,
                )
                for scene in scenes
            ],
        )

    @staticmethod
    def _persist_manifest(path: Path, manifest: VideoRunManifest) -> None:
        manifest.updated_at = datetime.now(timezone.utc).isoformat()
        temporary = path.with_suffix(".tmp")
        temporary.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(path)

    def _generate_scene(
        self,
        scene: VideoScene,
        work_dir: Path,
        index: int,
        ffmpeg: str,
        subject: str,
        package_root: Path,
        cancel_event: Event | None = None,
    ) -> str | None:
        """Generate one video segment for a scene."""

        prefix = f"scene_{index:03d}"
        audio_path: str | None = None
        video_source: str | None = None

        # 1. Generate durable TTS audio if narration exists.
        self._check_cancelled(cancel_event)
        if scene.narration.strip() and self.tts.configured:
            audio_path = str(package_root / "audio" / f"{prefix}.mp3")
            try:
                self.tts.generate(scene.narration, audio_path, cancel_event=cancel_event)
            except NativeVideoCancelled:
                raise
            except NativeVideoError:
                audio_path = None
        scene.audio_path = audio_path

        # 2. Generate a durable OpenAI image for this scene.
        if scene.visual_description.strip() and self.image_generator.configured:
            image_path = str(package_root / "images" / f"{prefix}.png")
            try:
                scene.image_path = self.image_generator.generate(
                    scene.visual_description, image_path, cancel_event=cancel_event,
                )
                video_source = str(work_dir / f"{prefix}_image.mp4")
                self._generate_image_video(scene.image_path, video_source, scene, ffmpeg, cancel_event)
            except NativeVideoCancelled:
                raise
            except Exception:
                scene.image_path = None
                video_source = None

        # 3. Generate a local title card if image generation is unavailable.
        if not video_source:
            video_source = str(work_dir / f"{prefix}_card.mp4")
            self._generate_title_card(scene, video_source, ffmpeg, cancel_event)

        # 4. Add on-screen text overlay if provided.
        segment_path = str(package_root / "segments" / f"{prefix}.mp4")
        self._compose_segment(video_source, audio_path, segment_path, scene, ffmpeg, cancel_event)

        scene.video_path = segment_path if Path(segment_path).exists() else None
        return scene.video_path

    @staticmethod
    def _check_cancelled(cancel_event: Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise NativeVideoCancelled("video generation cancelled cooperatively")

    @staticmethod
    def _run_process(
        command: list[str],
        *,
        timeout_seconds: float,
        cancel_event: Event | None = None,
    ) -> subprocess.CompletedProcess[Any]:
        """Run FFmpeg with a hard process deadline and cooperative cancel."""

        if cancel_event is None:
            return subprocess.run(command, capture_output=True, timeout=timeout_seconds, check=True)

        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        started = time.monotonic()
        try:
            while process.poll() is None:
                if cancel_event.is_set():
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
                    raise NativeVideoCancelled("video process cancelled cooperatively")
                if time.monotonic() - started >= timeout_seconds:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
                    raise subprocess.TimeoutExpired(command, timeout_seconds)
                time.sleep(0.05)
            stdout, stderr = process.communicate()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=2)
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command, output=stdout, stderr=stderr)
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)

    def _generate_image_video(
        self,
        image_path: str,
        output_path: str,
        scene: VideoScene,
        ffmpeg: str,
        cancel_event: Event | None = None,
    ) -> None:
        duration = max(1, scene.duration_seconds)
        vf = (
            f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,"
            f"pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2"
        )
        cmd = [
            ffmpeg, "-y", "-loop", "1", "-i", image_path, "-t", str(duration),
            "-vf", vf, "-r", str(self.fps), "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", "-an", output_path,
        ]
        self._run_process(cmd, timeout_seconds=120, cancel_event=cancel_event)

    def _generate_title_card(
        self,
        scene: VideoScene,
        output_path: str,
        ffmpeg: str,
        cancel_event: Event | None = None,
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
        self._run_process(cmd, timeout_seconds=30, cancel_event=cancel_event)

    def _compose_segment(
        self,
        video_path: str,
        audio_path: str | None,
        output_path: str,
        scene: VideoScene,
        ffmpeg: str,
        cancel_event: Event | None = None,
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
        self._run_process(cmd, timeout_seconds=120, cancel_event=cancel_event)

    def _concatenate(
        self,
        segment_paths: list[str],
        output_path: str,
        work_dir: Path,
        ffmpeg: str,
        cancel_event: Event | None = None,
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
        self._run_process(cmd, timeout_seconds=300, cancel_event=cancel_event)

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
            image_path=scene_data.get("image_path"),
            audio_path=scene_data.get("audio_path"),
            video_path=scene_data.get("video_path"),
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
