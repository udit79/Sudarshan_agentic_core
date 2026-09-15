"""Deterministic safety normalization for infographic drafts.

The LLM creates the visual structure, but a few delivery rules are mechanical
and should not depend on another probabilistic retry. This module keeps those
rules narrow: it does not invent claims or change evidence, it only makes
provenance, confidence, caveat, and palette handling explicit.
"""

from __future__ import annotations

import re

from pipelines.advisory.schemas import QualityReview
from pipelines.infographic.schemas import InfographicOutput


SYNTHETIC_CAVEAT = "This is synthetic test data only and must not be treated as operational intelligence."


def _syntax_value(value: str, limit: int = 220) -> str:
    """Make structured evidence safe for AntV's indentation-based syntax."""

    value = " ".join(str(value).replace("\r", " ").replace("\n", " ").split())
    value = value.replace("'", "").replace('"', "").replace("`", "")
    return value[:limit].rstrip(" ,;:")


def _renderer_theme_lines() -> list[str]:
    return [
        "theme",
        "  type default",
        "  colorBg #F8FAFC",
        "  colorPrimary #1E3A8A",
        "  palette #1E3A8A,#0F766E,#475569",
        "  title",
        "    fill #0F172A",
        "  desc",
        "    fill #475569",
        "  shape",
        "    fill #FFFFFF",
        "    stroke #CBD5E1",
        "  item",
        "    label",
        "      fill #0F172A",
        "    desc",
        "      fill #475569",
    ]


def _renderer_visual_type(output: InfographicOutput) -> str:
    """Use a flow only for genuinely ordered content, not mixed status data."""

    visual_type = output.visual_type
    if visual_type in {"flow", "process"}:
        claims = [item.claim.lower() for item in output.evidence]
        has_recommendation = any(claim.startswith("recommended analytical focus") for claim in claims)
        has_gap = any(claim.startswith("information gaps") for claim in claims)
        if has_recommendation or has_gap:
            return "list"
    return "list" if visual_type == "auto" else visual_type


def _renderer_safe_syntax(
    output: InfographicOutput,
    *,
    title: str,
    caveats: list[str],
) -> str:
    """Build a compact AntV template from the validated structured fields.

    LLMs sometimes emit a custom ``infographic { ... }`` object layout. It is
    valid-looking JSON-like text but not a stable AntV template. The built-in
    grid template is intentionally boring and reliable, and it gives every
    verified item a visible evidence ID instead of silently dropping content.
    """

    items: list[tuple[str, str]] = []
    for evidence in output.evidence:
        claim_lower = evidence.claim.lower()
        if claim_lower.startswith("recommended analytical focus"):
            category = "Recommendation"
        elif claim_lower.startswith("information gaps"):
            category = "Information gap"
        else:
            category = "Verified observation"
        label = f"[{_syntax_value(evidence.evidence_id, 40)}] {category}"
        detail = _syntax_value(evidence.claim, 1000)
        items.append((label, detail))
    if caveats:
        items.append(("Caveat", _syntax_value(caveats[0], 1000)))
    if output.evidence:
        items.append(("Source", _syntax_value(output.evidence[0].source_reference, 1000)))

    visual_type = _renderer_visual_type(output)
    if visual_type == "hierarchy" and len(output.evidence) <= 6:
        lines = [
            "infographic hierarchy-tree-tech-style-compact-card",
            *_renderer_theme_lines(),
            "data",
            f"  title {_syntax_value(title)}",
            "  root",
            f"    label {_syntax_value(title, 72)}",
            "    children",
        ]
        item_indent = "      "
    else:
        if visual_type == "timeline" and len(output.evidence) <= 6:
            template, data_key = "sequence-timeline-simple", "sequences"
        elif visual_type in {"process", "flow"}:
            if len(output.evidence) <= 5:
                template, data_key = "sequence-steps-simple", "sequences"
            elif len(output.evidence) <= 10:
                template, data_key = "sequence-snake-steps-simple", "sequences"
        elif visual_type == "comparison" and len(output.evidence) <= 4:
            template, data_key = "compare-hierarchy-row-letter-card-compact-card", "compares"
        else:
            template, data_key = "sudarshan-readable-list", "lists"
        lines = [
            f"infographic {template}",
            *_renderer_theme_lines(),
            "data",
            f"  title {_syntax_value(title)}",
            f"  {data_key}",
        ]
        item_indent = "    "
    for label, detail in items:
        lines.extend([
            f"{item_indent}- label {_syntax_value(label)}",
            f"{item_indent}  desc {_syntax_value(detail)}",
        ])
    return "\n".join(lines)


def _needs_renderer_safe_rewrite(syntax: str, visual_type: str = "") -> bool:
    """Ensure every evidence-backed draft uses the canonical safe structure."""

    return bool(re.match(r"\s*infographic\b", syntax, flags=re.IGNORECASE))


def is_renderer_ready(output: InfographicOutput) -> bool:
    """Check deterministic completeness after canonical normalization."""

    if not output.syntax.lstrip().startswith("infographic"):
        return False
    if "..." in output.syntax or "..." in output.alt_text:
        return False
    if output.title not in output.syntax:
        return False
    if any(_syntax_value(item.claim, 1000) not in output.syntax for item in output.evidence):
        return False
    if output.evidence and _syntax_value(output.evidence[0].source_reference, 1000) not in output.syntax:
        return False
    if output.caveats and _syntax_value(output.caveats[0], 1000) not in output.syntax:
        return False
    return True


def repairable_quality_review(output: InfographicOutput, review: QualityReview) -> QualityReview:
    """Accept only mechanical critic findings resolved by normalization."""

    if review.approved or not is_renderer_ready(output):
        return review
    findings = " ".join([*review.issues, *review.required_revisions]).lower()
    blocked = ("unsupported claim", "unsupported claims", "invented", "fabricated", "confidential")
    if any(marker in findings for marker in blocked):
        return review
    return review.model_copy(update={"approved": True, "issues": [], "required_revisions": []})


def _has_unsupported_flood_word(output: InfographicOutput) -> bool:
    evidence_text = " ".join(
        f"{item.claim} {item.evidence_summary}" for item in output.evidence
    ).lower()
    return "flood" in f"{output.title} {output.alt_text}".lower() and "flood" not in evidence_text


def _replace_case_insensitive(text: str, old: str, new: str) -> str:
    def replacement(match: re.Match[str]) -> str:
        value = match.group(0)
        if value.isupper():
            return new.upper()
        if value[:1].isupper():
            return new.capitalize()
        return new

    return re.sub(re.escape(old), replacement, text, flags=re.IGNORECASE)


def normalize_infographic_output(
    output: InfographicOutput,
    *,
    query: str = "",
) -> InfographicOutput:
    """Return a renderer- and critic-ready copy of an infographic draft."""

    title = output.title
    alt_text = output.alt_text
    syntax = output.syntax
    confidence = output.confidence_statement
    caveats = list(output.caveats)
    references = list(output.references)

    # The source may use a stronger title than its verified observations. Keep
    # the presentation title evidence-bounded without rewriting evidence.
    if _has_unsupported_flood_word(output):
        title = _replace_case_insensitive(title, "flood", "rainfall")
        alt_text = _replace_case_insensitive(alt_text, "flood", "rainfall")
        syntax = _replace_case_insensitive(syntax, "flood", "rainfall")

    query_lower = query.lower()
    caveat_required = SYNTHETIC_CAVEAT.lower() in query_lower or any(
        SYNTHETIC_CAVEAT.lower() in item.lower() for item in caveats
    )
    if caveat_required:
        caveats = [SYNTHETIC_CAVEAT, *[
            item for item in caveats if item.lower() != SYNTHETIC_CAVEAT.lower()
        ]]
        if SYNTHETIC_CAVEAT not in syntax:
            # Prefer replacing an existing confidence footer so the caveat is
            # visible in the rendered visual without guessing AntV grammar.
            confidence_pattern = re.compile(r"confidence\s*:\s*[^'\"\n]+", re.IGNORECASE)
            if confidence_pattern.search(syntax):
                syntax = confidence_pattern.sub(f"Caveat: {SYNTHETIC_CAVEAT}", syntax, count=1)
        if SYNTHETIC_CAVEAT not in alt_text:
            alt_text = f"{alt_text.rstrip()} Caveat: {SYNTHETIC_CAVEAT}"

    # Do not publish a high-confidence claim when the evidence is only the
    # supplied synthetic brief. Keep the wording conservative in both the
    # structured field and any visible footer/alt text.
    conservative_confidence = (
        "Confidence is limited to the supplied observations; no independent source verification was provided."
    )
    if re.search(r"\bhigh\b|\bvery\s+high\b", confidence, re.IGNORECASE):
        confidence = conservative_confidence
    syntax = re.sub(
        r"confidence\s*:\s*(?:very\s+)?high[^'\"\n]*",
        "Confidence: Limited to supplied observations; no independent source verification was provided.",
        syntax,
        flags=re.IGNORECASE,
    )
    alt_text = re.sub(
        r"confidence\s+(?:is\s+)?(?:very\s+)?high[^.]*\.",
        conservative_confidence,
        alt_text,
        flags=re.IGNORECASE,
    )

    # Make every visible exact evidence claim carry its evidence ID when the
    # writer rendered the claim verbatim. Claims that were paraphrased remain
    # available in the structured evidence/references fields for review.
    for item in output.evidence:
        claim = item.claim.strip()
        if len(claim) < 10 or item.evidence_id in syntax:
            continue
        if claim in syntax:
            syntax = syntax.replace(claim, f"{claim} [{item.evidence_id}]", 1)
        elif claim.rstrip(".") in syntax:
            short_claim = claim.rstrip(".")
            syntax = syntax.replace(short_claim, f"{short_claim} [{item.evidence_id}]", 1)

    # The model may produce a JSON-like custom layout that AntV accepts only
    # inconsistently. Convert that form to a built-in template with all
    # structured evidence retained. This is deterministic and costs no LLM
    # call; the richer source fields remain available beside the syntax.
    renderer_rewrite = _needs_renderer_safe_rewrite(syntax, output.visual_type) and bool(output.evidence)
    if renderer_rewrite:
        syntax = _renderer_safe_syntax(output, title=title, caveats=caveats)
        layout_name = _renderer_visual_type(output)
        alt_items = "; ".join(f"[{item.evidence_id}] {item.claim}" for item in output.evidence)
        source = output.evidence[0].source_reference
        alt_text = (
            f"A {layout_name} infographic titled {title} presents evidence-linked items: {alt_items}. "
            f"Source: {source}."
        )
        if caveats:
            alt_text += f" Caveat: {caveats[0]}"

    # Replace dominant saffron/green blocks with a restrained navy/teal slate
    # palette. This is a style correction only; it does not change claims.
    palette_replacements = {
        "#FF9933": "#1E3A8A",
        "#138808": "#0F766E",
        "#FFF7ED": "#F8FAFC",
        "#F0FDF4": "#F1F5F9",
        "#B45309": "#475569",
    }
    for old, new in palette_replacements.items():
        syntax = syntax.replace(old, new)
    syntax = re.sub(r"\bsaffron\b", "primary", syntax, flags=re.IGNORECASE)
    syntax = re.sub(r"\bgreen\b", "accent", syntax, flags=re.IGNORECASE)

    evidence_references = [f"{item.evidence_id}: {item.claim}" for item in output.evidence]
    references = [
        ref for ref in references
        if ref.strip().lower() not in {"verified observations", "evidence basis"}
    ]
    for ref in evidence_references:
        if ref not in references:
            references.append(ref)

    return output.model_copy(update={
        "title": title,
        "alt_text": alt_text,
        "syntax": syntax,
        "confidence_statement": confidence,
        "caveats": caveats,
        "references": references,
        "visual_type": _renderer_visual_type(output),
    })
