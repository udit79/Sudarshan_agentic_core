"""Opt-in, bounded voice preferences for LinkedIn drafting.

Voice profiles are preferences, not facts.  They are intentionally small so
they can be supplied as context without leaking a user's full memory graph.
"""

from __future__ import annotations

from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator


class VoiceProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    version: str = "1.0"
    tone: str = Field(default="clear and direct", max_length=240)
    preferred_phrases: list[str] = Field(default_factory=list, max_length=12)
    avoid_phrases: list[str] = Field(default_factory=list, max_length=12)
    max_hashtags: int = Field(default=5, ge=0, le=8)
    source_references: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("preferred_phrases", "avoid_phrases", "source_references")
    @classmethod
    def clean_items(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in values if item.strip()))


def profile_from_metadata(metadata: Mapping[str, Any], *, user_id: str) -> VoiceProfile | None:
    """Parse only an explicit voice profile; never infer one from free text."""

    raw = metadata.get("voice_profile")
    if not isinstance(raw, Mapping):
        return None
    payload = dict(raw)
    payload.setdefault("profile_id", f"voice:{user_id}")
    payload.setdefault("user_id", user_id)
    try:
        return VoiceProfile.model_validate(payload)
    except Exception:
        return None


def voice_context(profile: VoiceProfile | None) -> str:
    if profile is None:
        return ""
    preferred = ", ".join(profile.preferred_phrases) or "none supplied"
    avoided = ", ".join(profile.avoid_phrases) or "none supplied"
    return (
        f"Voice preferences (use only as style guidance): tone={profile.tone}; "
        f"preferred={preferred}; avoid={avoided}; max_hashtags={profile.max_hashtags}."
    )


__all__ = ["VoiceProfile", "profile_from_metadata", "voice_context"]
