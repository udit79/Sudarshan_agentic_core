"""Video package contracts shared by the planner, renderer, and frontend.

The frontend/backend may send a complete transcript and storyboard. The native
path persists these fields alongside generated media; the legacy compatibility
adapter can compile them into its provider options when explicitly enabled.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pipelines.video.timeline import VideoTimeline


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class VideoScene(BaseModel):
    scene_id: str = Field(min_length=1, max_length=120)
    narration: str = Field(default="", max_length=4000)
    visual_description: str = Field(default="", max_length=2000)
    duration_seconds: int = Field(default=5, ge=1, le=600)
    on_screen_text: str = Field(default="", max_length=1000)
    material_references: list[str] = Field(default_factory=list, max_length=20)
    image_path: str | None = Field(default=None, max_length=2000)
    audio_path: str | None = Field(default=None, max_length=2000)
    video_path: str | None = Field(default=None, max_length=2000)

    @field_validator("scene_id", mode="before")
    @classmethod
    def coerce_scene_id(cls, v: Any) -> str:
        return str(v) if v is not None else ""


class VideoProviderOptions(BaseModel):
    video_aspect: str | None = Field(default=None, max_length=32)
    voice_name: str | None = Field(default=None, max_length=120)
    voice_rate: float | None = Field(default=None, ge=0.1, le=5.0)
    bgm_type: str | None = Field(default=None, max_length=120)
    bgm_volume: float | None = Field(default=None, ge=0.0, le=1.0)
    video_concat_mode: str | None = Field(default=None, max_length=32)
    video_transition: str | None = Field(default=None, max_length=32)


class VideoSceneManifest(BaseModel):
    """Durable state for one independently retryable scene."""

    model_config = ConfigDict(extra="forbid")

    scene_id: str = Field(min_length=1, max_length=120)
    fingerprint: str = Field(min_length=64, max_length=64)
    status: Literal["pending", "running", "succeeded", "failed", "cancelled"] = "pending"
    attempt: int = Field(default=0, ge=0)
    duration_seconds: int = Field(default=5, ge=1, le=600)
    image_path: str | None = None
    audio_path: str | None = None
    video_path: str | None = None
    error: str | None = None
    updated_at: str = Field(default_factory=_utc_now)


class VideoRunManifest(BaseModel):
    """Resumable package state for storyboard, scene media, and composition."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    subject: str = Field(min_length=1, max_length=500)
    renderer_version: str = Field(min_length=1)
    status: Literal["planning", "rendering", "composing", "succeeded", "partial", "failed", "cancelled"] = "planning"
    scenes: list[VideoSceneManifest] = Field(default_factory=list, max_length=100)
    segment_order: list[str] = Field(default_factory=list, max_length=100)
    output_video: str | None = None
    failed_scene_ids: list[str] = Field(default_factory=list, max_length=100)
    timeline: VideoTimeline | None = None
    created_at: str = Field(default_factory=_utc_now)
    updated_at: str = Field(default_factory=_utc_now)


class VideoPackage(BaseModel):
    """A complete, provider-neutral video preparation package."""

    subject: str = Field(min_length=1, max_length=500)
    title: str = Field(default="", max_length=500)
    transcript: str = Field(default="", max_length=100_000)
    script: str = Field(default="", max_length=20_000)
    storyboard: list[VideoScene] = Field(default_factory=list, max_length=100)
    video_terms: list[str] = Field(default_factory=list, max_length=100)
    audio_reference: str | None = Field(default=None, max_length=1000)
    video_source: str = Field(default="pexels", max_length=64)
    provider_options: VideoProviderOptions = Field(default_factory=VideoProviderOptions)

    def provider_payload(self) -> dict[str, Any]:
        """Compile supported package fields into legacy worker options."""

        script = self.script.strip() or "\n\n".join(
            scene.narration.strip()
            for scene in self.storyboard
            if scene.narration.strip()
        )
        if not script:
            script = self.transcript.strip()

        terms = list(self.video_terms)
        if not terms:
            terms = [
                scene.visual_description.strip()
                for scene in self.storyboard
                if scene.visual_description.strip()
            ]

        payload: dict[str, Any] = {
            "video_script": script[:20_000],
            "video_source": self.video_source,
        }
        if terms:
            payload["video_terms"] = terms
            payload["match_materials_to_script"] = bool(self.storyboard)
        if self.audio_reference:
            # The reference must point to a file already uploaded into the
            # provider task directory; arbitrary host paths are not accepted.
            payload["custom_audio_file"] = self.audio_reference
        if isinstance(self.provider_options, VideoProviderOptions):
            payload.update(self.provider_options.model_dump(exclude_none=True))
        elif isinstance(self.provider_options, dict):
            payload.update(self.provider_options)
        return payload
