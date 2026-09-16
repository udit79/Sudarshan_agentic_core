"""Deterministic humanizer checks for LinkedIn drafts.

This is intentionally a transparent lint pass rather than a claim that a
classifier can detect every machine-written sentence.  The result is a
review signal that can be logged, tested, and shown to an operator.
"""

from __future__ import annotations

import re
from typing import Mapping, Any

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


def audit_linkedin_text(text: str, *, voice_profile: Mapping[str, Any] | None = None) -> HumanizerReport:
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
                rule_id="HUM-AI-001",
                evidence=phrase,
            ))
            suggestions.append("Rewrite the sentence as a direct, human-facing statement.")

    for index, phrase in enumerate(_GENERIC_PHRASES, start=1):
        if phrase in lowered:
            issues.append(HumanizerIssue(
                issue_id=f"generic-{index}",
                category="generic_phrase",
                message=f"Replace generic opening or transition: '{phrase}'.",
                severity="warn",
                rule_id="HUM-GEN-001",
                evidence=phrase,
            ))
            suggestions.append("Open with a concrete case detail or observed outcome.")

    for index, phrase in enumerate(_OVERCLAIM_PHRASES, start=1):
        if re.search(rf"\b{re.escape(phrase)}\b", lowered):
            issues.append(HumanizerIssue(
                issue_id=f"overclaim-{index}",
                category="overclaim",
                message=f"Check whether the absolute or promotional wording '{phrase}' is supported.",
                severity="warn",
                rule_id="HUM-CLAIM-001",
                evidence=phrase,
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
            rule_id="HUM-REP-001",
            evidence=repeated,
        ))
        suggestions.append("Remove accidental repetition and vary repeated transitions.")

    emoji_count = sum(1 for char in text if ord(char) > 0x1F000)
    if emoji_count > 4:
        issues.append(HumanizerIssue(
            issue_id="emoji-density",
            category="emoji_density",
            message="The draft uses more than four emoji characters.",
            severity="warn",
            rule_id="HUM-EMOJI-001",
        ))
        suggestions.append("Keep emoji sparse and purposeful for a professional audience.")

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text.strip()) if part.strip()]
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part.strip()]
    sentence_lengths = [len(re.findall(r"[A-Za-z][A-Za-z'-]+", item)) for item in sentences]
    if len(sentence_lengths) >= 4 and max(sentence_lengths) - min(sentence_lengths) <= 4:
        issues.append(HumanizerIssue(
            issue_id="rhythm-flat",
            category="rhythm",
            message="Sentence lengths are unusually uniform; vary the cadence once without adding filler.",
            severity="info",
            rule_id="HUM-RHY-001",
        ))
        suggestions.append("Keep the meaning fixed, but vary one sentence length for a more natural cadence.")

    density_terms = ("however", "therefore", "additionally", "moreover", "furthermore", "ultimately")
    density_hits = sum(lowered.count(term) for term in density_terms)
    if density_hits >= 4:
        issues.append(HumanizerIssue(
            issue_id="transition-density",
            category="density",
            message="The draft relies heavily on formal transition words.",
            severity="warn",
            rule_id="HUM-DENS-001",
        ))
        suggestions.append("Replace one transition with a concrete observation or a direct sentence.")

    if any(len(re.findall(r"[A-Za-z][A-Za-z'-]+", paragraph)) > 120 for paragraph in paragraphs):
        issues.append(HumanizerIssue(
            issue_id="paragraph-density",
            category="density",
            message="One paragraph is dense enough to reduce scanability on LinkedIn.",
            severity="warn",
            rule_id="HUM-DENS-002",
        ))
        suggestions.append("Split the dense paragraph at a meaningful change in evidence or decision.")

    triad_match = re.search(r"\b([A-Za-z][^,.;]{2,40}),\s*([A-Za-z][^,.;]{2,40}),\s*(?:and\s+)?([A-Za-z][^,.;]{2,40})\b", text)
    if triad_match:
        issues.append(HumanizerIssue(
            issue_id="triad-check",
            category="triad",
            message="A three-part list was detected; verify that each item is distinct and evidence-grounded.",
            severity="info",
            rule_id="HUM-TRIAD-001",
            evidence=triad_match.group(0)[:160],
        ))

    hedge_hits = sum(len(re.findall(rf"\b{re.escape(term)}\b", lowered)) for term in ("arguably", "perhaps", "possibly", "might", "may"))
    if hedge_hits >= 4:
        issues.append(HumanizerIssue(
            issue_id="overcorrection-hedging",
            category="overcorrection",
            message="Repeated hedging may make a supported claim sound evasive.",
            severity="warn",
            rule_id="HUM-OVER-001",
        ))
        suggestions.append("Keep uncertainty markers where evidence requires them, but remove redundant hedges.")

    if len(paragraphs) >= 3 and any(re.search(r"\b(?:but|and)\s+(?:here's|this|that)\b", item, re.I) for item in paragraphs):
        issues.append(HumanizerIssue(
            issue_id="reveal-bridge",
            category="reveal_bridge",
            message="A reveal transition may be obscuring the evidence or decision that follows.",
            severity="info",
            rule_id="HUM-REVEAL-001",
        ))

    if re.search(r"(?:^|\n)\s*(?:no\s+[^.]{1,60}\.){2,}\s*(?:just|only)\b", text, re.I):
        issues.append(HumanizerIssue(
            issue_id="fragment-stack",
            category="fragment_stack",
            message="Several short fragments form a slogan-like stack.",
            severity="warn",
            rule_id="HUM-FRAG-001",
        ))
        suggestions.append("Combine the fragments into one precise claim and preserve the supporting detail.")

    if len(text) > 240 and not re.search(r"\d", text) and not re.search(r"\b[A-Z][a-z]{2,}\b", text):
        issues.append(HumanizerIssue(
            issue_id="missing-concrete-detail",
            category="concrete_detail",
            message="Long drafts should include at least one concrete, case-grounded detail.",
            severity="info",
            rule_id="HUM-CONCRETE-001",
        ))
        suggestions.append("Add a verifiable detail, example, date, or bounded observation if one is available.")

    if voice_profile:
        avoid = tuple(str(item).casefold() for item in voice_profile.get("avoid_phrases", ()) if str(item).strip())
        for index, phrase in enumerate(avoid, start=1):
            if phrase in lowered:
                issues.append(HumanizerIssue(
                    issue_id=f"voice-avoid-{index}",
                    category="voice",
                    message=f"The draft uses a phrase excluded by the selected voice profile: '{phrase}'.",
                    severity="warn",
                    rule_id="HUM-VOICE-001",
                    evidence=phrase,
                ))

    # Every finding has a stable, privacy-safe location even when the rule did
    # not carry an exact phrase (for example a rhythm or density rule).
    located: list[HumanizerIssue] = []
    for issue in issues:
        location = issue.location
        if not location:
            evidence = issue.evidence or ""
            offset = lowered.find(evidence.casefold()) if evidence else 0
            paragraph_index = text[:max(offset, 0)].count("\n\n") + 1
            location = f"paragraph:{paragraph_index}"
        rule_id = issue.rule_id or f"HUM-{issue.category.upper()[:8]}-001"
        issue_id = issue.issue_id or f"{issue.category}-{len(located) + 1}"
        located.append(issue.model_copy(update={
            "location": location,
            "rule_id": rule_id,
            "issue_id": issue_id,
        }))
    issues = located

    block_count = sum(issue.severity == "block" for issue in issues)
    score = max(0.0, 1.0 - min(1.0, (len(issues) * 0.12) + (block_count * 0.35)))
    score = round(score, 3)
    has_blocking = any(issue.severity == "block" for issue in issues)
    approved = (not has_blocking) and (score >= 0.70)
    return HumanizerReport(
        approved=approved,
        score=score,
        checks=[
            "ai_meta_language", "generic_phrases", "overclaim_language", "adjacent_repetition",
            "emoji_density", "rhythm", "transition_density", "reveal_bridge", "fragment_stack",
            "concrete_detail", "voice_profile",
        ],
        issues=issues,
        revision_suggestions=list(dict.fromkeys(suggestions)),
        diff_summary=[f"{issue.rule_id}: {issue.category}" for issue in issues if issue.rule_id],
    )


__all__ = ["audit_linkedin_text"]
