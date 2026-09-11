"""Small, safe correlation contracts shared by transport adapters."""

from __future__ import annotations

from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field


class HarnessCorrelation(BaseModel):
    """Correlation IDs shared by native Harness and MCP clients."""

    model_config = ConfigDict(extra="forbid")

    session_id: str | None = Field(default=None, max_length=200)
    message_id: str | None = Field(default=None, max_length=200)
    tool_call_id: str | None = Field(default=None, max_length=200)

    @classmethod
    def from_metadata(cls, metadata: Mapping[str, Any]) -> "HarnessCorrelation | None":
        raw = metadata.get("harness_correlation") or metadata.get("harness")
        if raw is None:
            raw = {
                "session_id": metadata.get("harness_session_id"),
                "message_id": metadata.get("harness_message_id"),
                "tool_call_id": metadata.get("harness_tool_call_id"),
            }
        if not isinstance(raw, Mapping):
            raise ValueError("harness correlation must be an object")
        correlation = cls.model_validate({
            "session_id": raw.get("session_id"),
            "message_id": raw.get("message_id"),
            "tool_call_id": raw.get("tool_call_id"),
        })
        return correlation if any(correlation.model_dump().values()) else None


__all__ = ["HarnessCorrelation"]
