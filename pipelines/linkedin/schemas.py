"""Validated output for the frontend-facing LinkedIn generator.

The LinkedIn pipeline returns a draft contract, not a publish command.  Claim
bindings and the humanizer report make the quality boundary inspectable by the
frontend and by the run-log projection.
"""

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


class LinkedInClaimBinding(BaseModel):
    """Trace one public-facing claim back to permitted evidence."""

    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(min_length=1)
    claim: str = Field(min_length=1, max_length=1000)
    role: Literal["fact", "interpretation", "call_to_action"] = "fact"
    evidence_ids: list[str] = Field(default_factory=list)
    source_references: list[str] = Field(default_factory=list)


class HumanizerIssue(BaseModel):
    """One deterministic style or release-safety finding."""

    model_config = ConfigDict(extra="forbid")

    issue_id: str = Field(min_length=1)
    category: Literal[
        "ai_tell",
        "repetition",
        "generic_phrase",
        "overclaim",
        "emoji_density",
        "fragment_stack",
        "rhythm",
        "density",
        "reveal_bridge",
        "triad",
        "overcorrection",
        "concrete_detail",
        "voice",
        "thread_context",
        "other",
    ]
    message: str = Field(min_length=1)
    severity: Literal["info", "warn", "block"] = "warn"
    rule_id: str | None = None
    location: str | None = None
    evidence: str | None = None


class HumanizerReport(BaseModel):
    """Machine-readable humanizer result attached to every draft."""

    model_config = ConfigDict(extra="forbid")

    approved: bool = True
    score: float = Field(default=1.0, ge=0.0, le=1.0)
    checks: list[str] = Field(default_factory=list)
    issues: list[HumanizerIssue] = Field(default_factory=list)
    revision_suggestions: list[str] = Field(default_factory=list)
    version: str = "2.0"
    diff_summary: list[str] = Field(default_factory=list)


class LinkedInVisualChildRef(BaseModel):
    """Typed status for an optional specialist visual child skill."""

    model_config = ConfigDict(extra="forbid")

    skill_id: str = "visual.flowchart"
    status: Literal["not_requested", "eligible", "succeeded", "failed"] = "not_requested"
    artifact_ids: list[str] = Field(default_factory=list)
    quality_report_id: str | None = None
    failure_code: str | None = None


class LinkedInPostOutput(BaseModel):
    """A validated draft; the frontend remains responsible for approval/upload."""

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
    claim_bindings: list[LinkedInClaimBinding] = Field(default_factory=list)
    humanizer_report: HumanizerReport = Field(default_factory=HumanizerReport)
    approval_required: Literal["publish"] = "publish"
    publish_status: Literal["draft_only", "approved_for_publish"] = "draft_only"
    visual_child: LinkedInVisualChildRef = Field(default_factory=LinkedInVisualChildRef)

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

    @model_validator(mode="after")
    def enforce_draft_boundary(self) -> "LinkedInPostOutput":
        if self.publish_status != "draft_only":
            raise ValueError("LinkedIn generation cannot approve or publish external content")
        return self
