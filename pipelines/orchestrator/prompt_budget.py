"""Sanitized prompt/context measurements for offline budget audits."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping

from pipelines.orchestrator.spend_guard import approximate_token_count


@dataclass(frozen=True, slots=True)
class PromptMeasurement:
    """A length-only measurement; content is intentionally not retained."""

    name: str
    characters: int
    estimated_tokens: int

    def as_dict(self) -> dict[str, int | str]:
        return {
            "name": self.name,
            "characters": self.characters,
            "estimated_tokens": self.estimated_tokens,
        }


def _safe_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, default=str)


def measure_prompt_fields(values: Mapping[str, Any]) -> list[PromptMeasurement]:
    """Measure named prompt fields without returning their values."""

    return [
        PromptMeasurement(
            name=str(name),
            characters=len(text := _safe_text(value)),
            estimated_tokens=approximate_token_count(text),
        )
        for name, value in sorted(values.items(), key=lambda item: str(item[0]))
    ]


def measure_context_edges(
    stage_inputs: Mapping[str, Mapping[str, Any]],
) -> list[PromptMeasurement]:
    """Measure the serialized context supplied to each pipeline stage."""

    return [
        PromptMeasurement(
            name=str(stage),
            characters=len(text := _safe_text(values)),
            estimated_tokens=approximate_token_count(text),
        )
        for stage, values in sorted(stage_inputs.items(), key=lambda item: str(item[0]))
    ]


__all__ = ["PromptMeasurement", "measure_context_edges", "measure_prompt_fields"]
