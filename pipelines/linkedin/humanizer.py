"""Deterministic humanizer checks for LinkedIn drafts.

This is intentionally a transparent lint pass rather than a claim that a
classifier can detect every machine-written sentence.  The result is a
review signal that can be logged, tested, and shown to an operator.
"""

from __future__ import annotations

import re

from pipelines.linkedin.schemas import HumanizerIssue, HumanizerReport


_GENERIC_PHRASES = (
    "in today's rapidly changing world",
    "it is important to note",
    "in conclusion",
    "leverage the power of",
    "unlock the potential of",
)
_AI_TELLS = ("as an ai", "as a language model", "i cannot", "my training data")
_OVERCLAIM_PHRASES = (
    "revolutionary",
    "guaranteed",
    "always",
    "never fails",
    "unprecedented",
)


def audit_linkedin_text(text: str) -> HumanizerReport:
    """Run bounded, explainable style checks over one post body."""

    lowered = text.lower()
    issues: list[HumanizerIssue] = []
    suggestions: list[str] = []

    for index, phrase in enumerate(_AI_TELLS, start=1):
        if phrase in lowered:
            issues.append(HumanizerIssue(
                issue_id=f"ai-tell-{index}",
                category="ai_tell",
                message=f"Remove model self-reference: '{phrase}'.",
                severity="block",
            ))
            suggestions.append("Rewrite the sentence as a direct, human-facing statement.")

    for index, phrase in enumerate(_GENERIC_PHRASES, start=1):
        if phrase in lowered:
            issues.append(HumanizerIssue(
                issue_id=f"generic-{index}",
                category="generic_phrase",
                message=f"Replace generic opening or transition: '{phrase}'.",
                severity="warn",
            ))
            suggestions.append("Open with a concrete case detail or observed outcome.")

    for index, phrase in enumerate(_OVERCLAIM_PHRASES, start=1):
        if re.search(rf"\b{re.escape(phrase)}\b", lowered):
            issues.append(HumanizerIssue(
                issue_id=f"overclaim-{index}",
                category="overclaim",
                message=f"Check whether the absolute or promotional wording '{phrase}' is supported.",
                severity="warn",
            ))
            suggestions.append("Use evidence-calibrated language and state the relevant limitation.")

    words = re.findall(r"[a-zA-Z][a-zA-Z'-]+", lowered)
    repeated = next((word for left, word in zip(words, words[1:]) if left == word), None)
    if repeated:
        issues.append(HumanizerIssue(
            issue_id="repeated-word",
            category="repetition",
            message=f"Adjacent repeated word detected: '{repeated}'.",
            severity="warn",
        ))
        suggestions.append("Remove accidental repetition and vary repeated transitions.")

    emoji_count = sum(1 for char in text if ord(char) > 0x1F000)
    if emoji_count > 4:
        issues.append(HumanizerIssue(
            issue_id="emoji-density",
            category="emoji_density",
            message="The draft uses more than four emoji characters.",
            severity="warn",
        ))
        suggestions.append("Keep emoji sparse and purposeful for a professional audience.")

    block_count = sum(issue.severity == "block" for issue in issues)
    score = max(0.0, 1.0 - min(1.0, (len(issues) * 0.12) + (block_count * 0.35)))
    return HumanizerReport(
        approved=not any(issue.severity == "block" for issue in issues),
        score=round(score, 3),
        checks=["ai_meta_language", "generic_phrases", "overclaim_language", "adjacent_repetition", "emoji_density"],
        issues=issues,
        revision_suggestions=list(dict.fromkeys(suggestions)),
    )


__all__ = ["audit_linkedin_text"]
