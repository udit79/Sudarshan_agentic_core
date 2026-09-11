"""Provider-neutral timeline and scene asset ledger for video skills."""

from __future__ import annotations

from pathlib import Path
import hashlib
from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field


class TimelineAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str = Field(min_length=1)
    scene_id: str = Field(min_length=1)
    kind: Literal["image", "audio", "video", "material"]
    source_reference: str = Field(min_length=1)
    path: str | None = None
    status: Literal["planned", "verified", "fallback", "missing"] = "planned"
    fallback_reason: str | None = None
    provider: str = "local"
    checksum: str | None = None
    license_scope: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)


class TimelineClip(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: str = Field(min_length=1)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    asset_ids: list[str] = Field(default_factory=list)
    narration: str = ""
    on_screen_text: str = ""

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


class VideoTimeline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    renderer_version: str = Field(min_length=1)
    status: Literal["planned", "verified", "partial", "failed"] = "planned"
    clips: list[TimelineClip] = Field(default_factory=list, max_length=100)
    assets: list[TimelineAsset] = Field(default_factory=list, max_length=500)


def build_video_timeline(
    run_id: str,
    subject: str,
    scenes: Sequence[Any],
    *,
    renderer_version: str,
    status: str = "planned",
) -> VideoTimeline:
    """Build a deterministic ledger from scene outputs and material references."""

    assets: list[TimelineAsset] = []
    clips: list[TimelineClip] = []
    cursor = 0.0
    for scene in scenes:
        scene_id = str(scene.scene_id)
        asset_ids: list[str] = []
        for kind, path, fallback in (
            ("image", getattr(scene, "image_path", None), getattr(scene, "image_fallback", None)),
            ("audio", getattr(scene, "audio_path", None), getattr(scene, "audio_fallback", None)),
            ("video", getattr(scene, "video_path", None), None),
        ):
            if path or fallback:
                asset_id = f"{scene_id}:{kind}"
                asset_ids.append(asset_id)
                assets.append(TimelineAsset(
                    asset_id=asset_id,
                    scene_id=scene_id,
                    kind=kind,
                    source_reference=str(path or f"fallback://{scene_id}/{kind}"),
                    path=str(path) if path else None,
                    status=("verified" if path and Path(path).is_file() else "fallback" if fallback else "missing"),
                    fallback_reason=str(fallback) if fallback else None,
                    checksum=_file_checksum(path),
                    provider="openai" if kind == "image" and path else "local",
                ))
        material_path = getattr(scene, "material_path", None)
        if material_path:
            asset_id = f"{scene_id}:material-path"
            asset_ids.append(asset_id)
            assets.append(TimelineAsset(
                asset_id=asset_id,
                scene_id=scene_id,
                kind="material",
                source_reference=str(material_path),
                path=str(material_path),
                status="verified" if Path(material_path).is_file() else "missing",
                provider=str(getattr(scene, "material_provider", "local") or "local"),
                checksum=_file_checksum(material_path),
                license_scope=getattr(scene, "material_license_scope", None),
                provenance={"asset_id": getattr(scene, "material_asset_id", None)},
            ))
        for index, reference in enumerate(getattr(scene, "material_references", ()) or ()):
            asset_id = f"{scene_id}:material:{index}"
            asset_ids.append(asset_id)
            assets.append(TimelineAsset(
                asset_id=asset_id,
                scene_id=scene_id,
                kind="material",
                source_reference=str(reference),
            ))
        duration = max(1, int(getattr(scene, "duration_seconds", 5)))
        clips.append(TimelineClip(
            scene_id=scene_id,
            start_seconds=cursor,
            end_seconds=cursor + duration,
            asset_ids=asset_ids,
            narration=str(getattr(scene, "narration", "")),
            on_screen_text=str(getattr(scene, "on_screen_text", "")),
        ))
        cursor += duration
    normalized_status = status if status in {"planned", "verified", "partial", "failed"} else "planned"
    return VideoTimeline(
        run_id=run_id,
        subject=subject,
        renderer_version=renderer_version,
        status=normalized_status,
        clips=clips,
        assets=assets,
    )


def _file_checksum(path: str | None) -> str | None:
    if not path or not Path(path).is_file():
        return None
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return f"sha256:{digest.hexdigest()}"


__all__ = ["TimelineAsset", "TimelineClip", "VideoTimeline", "build_video_timeline"]
