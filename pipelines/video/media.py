"""Small, provider-neutral media capabilities inspired by MoneyPrinterTurbo.

The module deliberately owns media selection and file safety only. Planning,
authorization, budgets, and delivery remain in Sudarshan's application layer.
Remote material search is opt-in; local material is the deterministic default.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Any, Iterable
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from pipelines.video.contracts import MusicTrack, SubtitleTrack, VideoScene


class MediaCapabilityError(RuntimeError):
    """Raised for a bounded, non-provider-specific media failure."""


@dataclass(frozen=True, slots=True)
class MaterialCandidate:
    asset_id: str
    path: str | None
    source_reference: str
    provider: str
    license_scope: str | None = None
    duration_seconds: float | None = None
    provenance: dict[str, Any] | None = None


def _check_cancel(cancel_event: Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise MediaCapabilityError("media operation cancelled cooperatively")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


class MaterialResolver:
    """Resolve explicit or local stock material with scoped cache reuse."""

    def __init__(self, *, material_dir: str | Path | None = None, cache_dir: str | Path | None = None) -> None:
        self.material_dir = Path(material_dir or os.getenv("SUDARSHAN_VIDEO_MATERIAL_DIR", "artifacts/video-materials"))
        self.cache_dir = Path(cache_dir or os.getenv("SUDARSHAN_VIDEO_MATERIAL_CACHE_DIR", "artifacts/.cache/video-materials"))

    def resolve(
        self,
        scene: VideoScene,
        *,
        source: str = "local",
        aspect: str | None = None,
        cancel_event: Event | None = None,
    ) -> MaterialCandidate | None:
        """Return one verified candidate; never invent a path from model text."""

        _check_cancel(cancel_event)
        for reference in scene.material_references:
            candidate = self._local_candidate(Path(reference), provider="explicit", scene_id=scene.scene_id)
            if candidate is not None:
                return candidate

        candidate = self._search_local(scene)
        if candidate is not None:
            return candidate

        if source.lower() == "pexels" and os.getenv("SUDARSHAN_VIDEO_ALLOW_REMOTE_MATERIAL", "0") == "1":
            candidate = self._search_pexels(scene, aspect=aspect, cancel_event=cancel_event)
            if candidate is not None:
                return candidate
        return None

    def _search_local(self, scene: VideoScene) -> MaterialCandidate | None:
        if not self.material_dir.is_dir():
            return None
        terms = [term.lower() for term in re.findall(r"[a-zA-Z0-9]+", scene.visual_description) if len(term) > 2]
        files = sorted(
            path for path in self.material_dir.iterdir()
            if path.is_file() and path.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm", ".png", ".jpg", ".jpeg"}
        )
        ranked = sorted(files, key=lambda path: (-sum(term in path.stem.lower() for term in terms), path.name))
        return next((self._local_candidate(path, provider="local", scene_id=scene.scene_id) for path in ranked), None)

    def _local_candidate(self, path: Path, *, provider: str, scene_id: str) -> MaterialCandidate | None:
        try:
            resolved = path.resolve()
            if not resolved.is_file() or resolved.stat().st_size <= 0:
                return None
        except OSError:
            return None
        root = self.material_dir.resolve()
        if provider != "explicit" and not _inside(resolved, root):
            return None
        if provider == "explicit" and not (_inside(resolved, root) or _inside(resolved, self.cache_dir.resolve())):
            return None
        return MaterialCandidate(
            asset_id=f"{scene_id}:material:{hashlib.sha256(str(resolved).encode()).hexdigest()[:16]}",
            path=str(resolved),
            source_reference=resolved.name,
            provider=provider,
            license_scope="operator-provided" if provider == "explicit" else "local-material-policy",
            provenance={"path_name": resolved.name},
        )

    def _search_pexels(self, scene: VideoScene, *, aspect: str | None, cancel_event: Event | None) -> MaterialCandidate | None:
        key = os.getenv("PEXELS_API_KEY", "").strip()
        if not key:
            return None
        _check_cancel(cancel_event)
        query = " ".join(re.findall(r"[a-zA-Z0-9]+", scene.visual_description))[:120]
        if not query:
            return None
        params = {"query": query, "per_page": "8"}
        if aspect in {"portrait", "landscape", "square"}:
            params["orientation"] = aspect
        request = Request(
            "https://api.pexels.com/videos/search?" + urlencode(params),
            headers={"Authorization": key, "User-Agent": "Sudarshan/2.0"},
        )
        try:
            with urlopen(request, timeout=20) as response:
                payload = json.loads(response.read(2_000_000).decode("utf-8"))
        except Exception:
            return None
        for item in payload.get("videos", []) if isinstance(payload, dict) else []:
            files = item.get("video_files", []) if isinstance(item, dict) else []
            chosen = next((file for file in files if str(file.get("link", "")).startswith("https://")), None)
            if not chosen:
                continue
            url = str(chosen["link"])
            cache_path = self._download(url, cancel_event=cancel_event)
            if cache_path is None:
                continue
            asset_id = str(item.get("id") or hashlib.sha256(url.encode()).hexdigest()[:16])
            return MaterialCandidate(
                asset_id=f"pexels:{asset_id}",
                path=str(cache_path),
                source_reference=str(item.get("url") or url).split("?", 1)[0],
                provider="pexels",
                license_scope="pexels-license",
                duration_seconds=float(item.get("duration")) if item.get("duration") else None,
                provenance={"query": query, "asset_id": asset_id},
            )
        return None

    def _download(self, url: str, *, cancel_event: Event | None) -> Path | None:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in {"pexels.com", "www.pexels.com", "videos.pexels.com", "images.pexels.com"}:
            return None
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        destination = self.cache_dir / f"material-{hashlib.sha256(url.encode()).hexdigest()}.mp4"
        if destination.is_file() and destination.stat().st_size:
            return destination
        _check_cancel(cancel_event)
        request = Request(url, headers={"User-Agent": "Sudarshan/2.0"})
        maximum = int(os.getenv("SUDARSHAN_VIDEO_MAX_MATERIAL_BYTES", str(250 * 1024 * 1024)))
        temporary = None
        try:
            with urlopen(request, timeout=60) as response:
                with tempfile.NamedTemporaryFile(dir=self.cache_dir, delete=False) as handle:
                    temporary = Path(handle.name)
                    total = 0
                    while True:
                        _check_cancel(cancel_event)
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > maximum:
                            return None
                        handle.write(chunk)
            if temporary is None or temporary.stat().st_size == 0:
                return None
            temporary.replace(destination)
            return destination
        except Exception:
            return None
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink(missing_ok=True)


def write_scene_subtitles(scenes: Iterable[VideoScene], output_path: str | Path) -> SubtitleTrack:
    """Write deterministic scene-level SRT without another model call."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cursor = 0.0
    cues: list[str] = []
    for index, scene in enumerate(scenes, start=1):
        text = (scene.subtitle_text or scene.on_screen_text or scene.narration).strip()
        if not text:
            cursor += max(1, scene.duration_seconds)
            continue
        start = cursor
        end = cursor + max(1, scene.duration_seconds)
        def stamp(value: float) -> str:
            hours, remainder = divmod(int(value * 1000), 3_600_000)
            minutes, remainder = divmod(remainder, 60_000)
            seconds, millis = divmod(remainder, 1000)
            return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"
        cues.append(f"{index}\n{stamp(start)} --> {stamp(end)}\n{text[:500]}\n")
        cursor = end
    path.write_text("\n".join(cues), encoding="utf-8")
    return SubtitleTrack(track_id=f"subtitle:{hashlib.sha256(str(path).encode()).hexdigest()[:16]}", path=str(path), cue_count=len(cues))


def select_music(path: str | None, *, music_dir: str | Path | None = None, volume: float = 0.12) -> MusicTrack | None:
    candidate = Path(path) if path else None
    root = Path(music_dir or os.getenv("SUDARSHAN_VIDEO_BGM_DIR", "artifacts/video-bgm"))
    if candidate is None:
        if not root.is_dir():
            return None
        candidate = next((item for item in sorted(root.iterdir()) if item.suffix.lower() in {".mp3", ".wav", ".m4a", ".aac"} and item.is_file()), None)
    if candidate is None:
        return None
    try:
        resolved = candidate.resolve()
        if not resolved.is_file() or resolved.stat().st_size <= 0:
            return None
        if not _inside(resolved, root.resolve()):
            return None
    except OSError:
        return None
    return MusicTrack(
        track_id=f"music:{hashlib.sha256(str(resolved).encode()).hexdigest()[:16]}",
        path=str(resolved),
        volume=volume,
        checksum=_sha256(resolved),
    )


__all__ = [
    "MaterialCandidate",
    "MaterialResolver",
    "MediaCapabilityError",
    "select_music",
    "write_scene_subtitles",
]
