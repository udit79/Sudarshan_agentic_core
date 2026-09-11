"""Deterministic policy checks for LinkedIn comments and replies."""

from __future__ import annotations

from typing import Any, Mapping


def validate_comment_text(text: str, *, min_chars: int = 20, max_chars: int = 800) -> tuple[str, ...]:
    return _validate(text, min_chars=min_chars, max_chars=max_chars, label="comment")


def validate_reply_text(text: str, *, min_chars: int = 10, max_chars: int = 500) -> tuple[str, ...]:
    return _validate(text, min_chars=min_chars, max_chars=max_chars, label="reply")


def _validate(text: str, *, min_chars: int, max_chars: int, label: str) -> tuple[str, ...]:
    if not isinstance(text, str) or not text.strip():
        return (f"{label}_empty",)
    errors: list[str] = []
    size = len(text.strip())
    if size < min_chars:
        errors.append(f"{label}_too_short")
    if size > max_chars:
        errors.append(f"{label}_too_long")
    if "http://" in text.lower() or "https://" in text.lower():
        errors.append(f"{label}_contains_link")
    if text.count("!") > 2:
        errors.append(f"{label}_excessive_exclamation")
    return tuple(errors)


def resolve_top_level_parent(comment: Mapping[str, Any]) -> str | None:
    """Return the top-level parent identifier without trusting display text."""

    if not isinstance(comment, Mapping):
        return None
    if comment.get("is_top_level") is True:
        return _first(comment, "comment_urn", "urn", "id")
    return _first(comment, "root_comment_urn", "rootCommentUrn", "parent_comment_urn", "parentCommentUrn")


def _first(value: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


__all__ = ["resolve_top_level_parent", "validate_comment_text", "validate_reply_text"]
