"""Budgeted, provenance-preserving memory context assembly."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Iterable, Mapping

from memory.model import ScopeType


@dataclass(frozen=True, slots=True)
class RetrievedMemory:
    content: str
    scope_type: ScopeType | None = None
    scope_id: str | None = None
    source_reference: str | None = None
    score: float | None = None
    provenance: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.scope_type is not None:
            object.__setattr__(self, "scope_type", ScopeType(self.scope_type))
        object.__setattr__(self, "provenance", dict(self.provenance or {}))


@dataclass(frozen=True, slots=True)
class BuiltContext:
    text: str
    items: tuple[RetrievedMemory, ...]
    estimated_tokens: int


class ContextBuilder:
    """Keep the smallest useful context while retaining why it was selected."""

    def __init__(self, chars_per_token: int = 4) -> None:
        if chars_per_token < 1:
            raise ValueError("chars_per_token must be positive")
        self.chars_per_token = chars_per_token

    def build(self, results: Iterable[RetrievedMemory], token_budget: int = 2000) -> BuiltContext:
        if token_budget < 1:
            raise ValueError("token_budget must be positive")
        limit = token_budget * self.chars_per_token
        selected: list[RetrievedMemory] = []
        formatted: list[str] = []
        seen: set[str] = set()
        used = 0
        for result in results:
            content = " ".join(result.content.split())
            if not content or content.casefold() in seen:
                continue
            line = self._format(result, content)
            if selected and used + len(line) > limit:
                break
            if not selected and len(line) > limit:
                # Provenance is retained on the result object, but optional
                # display metadata is dropped when the budget is too small.
                compact_prefix = self._compact_prefix(result)
                content = content[:max(0, limit - len(compact_prefix))]
                result = RetrievedMemory(content=content, scope_type=result.scope_type,
                                         scope_id=result.scope_id,
                                         source_reference=result.source_reference,
                                         score=result.score, provenance=result.provenance)
                line = (compact_prefix + content)[:limit]
            selected.append(result)
            formatted.append(line)
            seen.add(content.casefold())
            used += len(line)
        text = "\n\n".join(formatted)
        return BuiltContext(text=text, items=tuple(selected),
                            estimated_tokens=(len(text) + self.chars_per_token - 1) // self.chars_per_token)

    @staticmethod
    def _compact_prefix(result: RetrievedMemory) -> str:
        scope = result.scope_type.value if result.scope_type else "unknown"
        scope_id = f":{result.scope_id}" if result.scope_id else ""
        return f"[{scope}{scope_id}] "

    @staticmethod
    def _format(result: RetrievedMemory, content: str) -> str:
        scope = result.scope_type.value if result.scope_type else "unknown"
        scope_id = f":{result.scope_id}" if result.scope_id else ""
        origin = f"; source={result.source_reference}" if result.source_reference else ""
        reason = f"; score={result.score:.4f}" if result.score is not None else ""
        provenance = ""
        if result.provenance:
            encoded = json.dumps(dict(result.provenance), sort_keys=True, default=str)
            provenance = f"; provenance={encoded[:500]}"
        return f"[{scope}{scope_id}{origin}{reason}{provenance}] {content}"
