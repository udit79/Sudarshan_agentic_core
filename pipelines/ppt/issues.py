"""Central registry for stable PPT validation issue codes."""

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict


class PPTIssue(BaseModel):
    """Structured machine-readable issue for repair and tracking."""

    model_config = ConfigDict(extra="forbid")

    code: str
    severity: Literal["error", "warning"]
    message: str
    affected_slide_ids: list[str] = []
    expected: Any = None
    actual: Any = None
    repairable: bool = False


# Stable Issue Codes
PPT_CONSTRAINT_SLIDE_COUNT = "PPT_CONSTRAINT_SLIDE_COUNT"
PPT_CONSTRAINT_COLOR_PALETTE = "PPT_CONSTRAINT_COLOR_PALETTE"
PPT_CONSTRAINT_FONT = "PPT_CONSTRAINT_FONT"
PPT_CONSTRAINT_REQUIRED_SECTION = "PPT_CONSTRAINT_REQUIRED_SECTION"
PPT_CONSTRAINT_EDITABILITY = "PPT_CONSTRAINT_EDITABILITY"
PPT_CONSTRAINT_Z_ORDER = "PPT_CONSTRAINT_Z_ORDER"
PPT_RENDER_INVALID = "PPT_RENDER_INVALID"
PPT_MANIFEST_MISSING = "PPT_MANIFEST_MISSING"
PPT_DEPENDENCY_INVALIDATED = "PPT_DEPENDENCY_INVALIDATED"
PPT_INCREMENTAL_SCOPE_CONFLICT = "PPT_INCREMENTAL_SCOPE_CONFLICT"
