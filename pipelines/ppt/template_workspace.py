"""Versioned local PPT template/layout contracts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LayoutContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layout_id: str = Field(min_length=1, max_length=100)
    master_id: str = Field(min_length=1, max_length=100)
    purpose: Literal["title", "narrative", "flowchart", "timeline", "matrix", "closing"]
    required_regions: list[str] = Field(min_length=1, max_length=16)


class PptTemplateContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=40)
    master_id: str = Field(min_length=1, max_length=100)
    design_tokens: dict[str, str] = Field(min_length=1, max_length=32)
    layouts: list[LayoutContract] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def validate_layouts(self) -> "PptTemplateContract":
        if any(layout.master_id != self.master_id for layout in self.layouts):
            raise ValueError("every layout must reference the template master")
        if len({layout.layout_id for layout in self.layouts}) != len(self.layouts):
            raise ValueError("template layout IDs must be unique")
        for name, value in self.design_tokens.items():
            if name.endswith(("color", "background", "foreground", "accent")) and not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                raise ValueError(f"design token {name} must be a six-digit hex color")
        return self


def write_template_workspace(contract: PptTemplateContract, output_root: str | Path) -> Path:
    """Persist one JSON-only template workspace for a bounded exporter."""

    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{contract.template_id}@{contract.version}.json"
    path.write_text(json.dumps(contract.model_dump(mode="json"), indent=2, sort_keys=True), encoding="utf-8")
    return path


__all__ = ["LayoutContract", "PptTemplateContract", "write_template_workspace"]
