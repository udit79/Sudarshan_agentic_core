"""Video package contracts shared by the planner, renderer, and frontend.

The frontend/backend may send a complete transcript and storyboard. The native
path persists these fields alongside generated media; the legacy compatibility
adapter can compile them into its provider options when explicitly enabled.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


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
