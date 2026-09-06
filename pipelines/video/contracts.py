"""Provider-neutral video package contracts.

The frontend/backend may send a complete transcript and storyboard without
leaking MoneyPrinterTurbo-specific fields into the public request contract.
The adapter compiles this package into the provider's supported options.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class VideoScene(BaseModel):
    scene_id: str = Field(min_length=1, max_length=120)
    narration: str = Field(default="", max_length=4000)
    visual_description: str = Field(default="", max_length=2000)
    duration_seconds: int = Field(default=5, ge=1, le=600)
    on_screen_text: str = Field(default="", max_length=1000)
    material_references: list[str] = Field(default_factory=list, max_length=20)


class VideoPackage(BaseModel):
    """A complete, provider-neutral video preparation package."""

    subject: str = Field(min_length=1, max_length=500)
    transcript: str = Field(default="", max_length=100_000)
    script: str = Field(default="", max_length=20_000)
    storyboard: list[VideoScene] = Field(default_factory=list, max_length=100)
    video_terms: list[str] = Field(default_factory=list, max_length=100)
    audio_reference: str | None = Field(default=None, max_length=1000)
    video_source: str = Field(default="pexels", max_length=64)
    provider_options: dict[str, Any] = Field(default_factory=dict)

    def provider_payload(self) -> dict[str, Any]:
        """Compile supported package fields into MoneyPrinterTurbo options."""

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
        payload.update(self.provider_options)
        return payload
