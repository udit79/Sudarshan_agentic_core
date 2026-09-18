"""Conservative provider-spend guard for retry admission.

The guard operates on provider usage receipts after an attempt and controls
whether another attempt may be admitted. It cannot undo tokens already spent
by a provider, and it does not pretend to be a provider-side total-token cap.
That stronger guarantee requires provider-specific request limits and prompt
size controls at the model adapter boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(slots=True)
class ProviderSpendGuard:
    """Track observed tokens and fail closed before unsafe retries."""

    max_tokens: int | None = None
    max_attempts: int = 1
    used_tokens: int = 0
    attempts: int = 0
    exceeded: bool = False

    def admit_attempt(self) -> bool:
        """Return whether another provider attempt may start."""

        if self.max_tokens is None:
            self.attempts += 1
            return True
        if self.exceeded or self.used_tokens >= self.max_tokens or self.attempts >= self.max_attempts:
            return False
        self.attempts += 1
        return True

    def record(self, tokens: int) -> bool:
        """Record an observed receipt and return whether the cap was exceeded."""

        self.used_tokens += max(0, int(tokens))
        if self.max_tokens is not None and self.used_tokens > self.max_tokens:
            self.exceeded = True
        return self.exceeded

    @property
    def remaining_tokens(self) -> int | None:
        if self.max_tokens is None:
            return None
        return max(0, self.max_tokens - self.used_tokens)


def usage_tokens(record: dict[str, object]) -> int:
    """Read only normalized counters from a sanitized usage record."""

    return sum(max(0, int(record.get(name, 0) or 0)) for name in (
        "input_tokens", "output_tokens", "reasoning_tokens"
    ))


def approximate_token_count(value: str) -> int:
    """Return a conservative character-based estimate for prompt sizing."""

    return max(0, math.ceil(len(value) / 4))


def bound_text(value: str, max_tokens: int) -> str:
    """Bound dynamic text while preserving both its beginning and ending."""

    if max_tokens < 1:
        return ""
    max_chars = max(4, max_tokens * 4)
    if len(value) <= max_chars:
        return value
    marker = "\n...[bounded for provider budget]...\n"
    available = max(0, max_chars - len(marker))
    left = available // 2
    right = available - left
    return f"{value[:left]}{marker}{value[-right:] if right else ''}"


def output_tokens_per_call(max_tokens: int, *, call_count: int = 5) -> int:
    """Allocate a conservative completion cap across current text agents."""

    return max(1, int(max_tokens) // max(1, int(call_count)))


__all__ = [
    "ProviderSpendGuard",
    "approximate_token_count",
    "bound_text",
    "output_tokens_per_call",
    "usage_tokens",
]
