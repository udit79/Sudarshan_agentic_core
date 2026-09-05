"""Validated output for the frontend-facing LinkedIn generator."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class LinkedInImageSpec(BaseModel):
    """Optional visual handoff for the frontend or an injected image service."""

    model_config = ConfigDict(extra="forbid")

    requested: bool = False
    strategy: Literal["none", "prompt", "generate", "asset"] = "none"
    image_type: Literal["auto", "illustration", "infographic", "photo", "diagram", "other"] = "auto"
    alt_text: str = ""
    generation_prompt: str = ""
    asset_uri: str | None = None

    @model_validator(mode="after")
    def validate_image_spec(self) -> "LinkedInImageSpec":
        if not self.requested and self.strategy != "none":
            raise ValueError("an unrequested image must use strategy=none")
        if self.requested and self.strategy == "none":
            raise ValueError("a requested image needs a generation strategy")
        if self.requested and not self.alt_text.strip():
            raise ValueError("requested images require alt_text")
        if self.strategy in {"prompt", "generate"} and not self.generation_prompt.strip():
            raise ValueError("image generation strategies require generation_prompt")
        if self.strategy == "asset" and not self.asset_uri:
            raise ValueError("asset strategy requires asset_uri")
        return self


class LinkedInPostOutput(BaseModel):
    """A publishable draft; the frontend remains responsible for upload."""

    model_config = ConfigDict(extra="forbid")

    post_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    post_text: str = Field(min_length=1, max_length=3000)
    audience: str = Field(min_length=1)
    call_to_action: str = Field(min_length=1)
    hashtags: list[str] = Field(default_factory=list, max_length=8)
    source_references: list[str] = Field(min_length=1)
    confidence_statement: str = Field(min_length=1)
    caveats: list[str] = Field(default_factory=list)
    image: LinkedInImageSpec = Field(default_factory=LinkedInImageSpec)

    @field_validator("post_text")
    @classmethod
    def reject_meta_language(cls, value: str) -> str:
        lowered = value.lower()
        if "as an ai" in lowered or "language model" in lowered:
            raise ValueError("LinkedIn post cannot contain model self-reference")
        return value.strip()

    @field_validator("hashtags")
    @classmethod
    def normalize_hashtags(cls, values: list[str]) -> list[str]:
        normalized = []
        for value in values:
            tag = value.strip().lstrip("#")
            if tag:
                normalized.append(f"#{tag}")
        return normalized
