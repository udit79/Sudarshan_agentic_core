"""Fail-closed application of targeted PPT visual repair patches."""

from __future__ import annotations

from typing import Any

from pipelines.ppt.schemas import LayoutBox, RepairPatch, SlideContentIR, VisualIR


class RepairApplicationError(ValueError):
    """Raised when a repair patch would escape the typed repair boundary."""


def apply_repair_patch(slide: SlideContentIR, patch: RepairPatch) -> SlideContentIR:
    """Apply one bounded patch and preserve all existing evidence bindings.

    A patch may update slide wording or visual geometry/alt text, but it may
    not inject evidence, renderer payloads, or silently remove an evidence
    binding.  The returned Pydantic model revalidates placeholders and bounds.
    """

    if patch.target_id == slide.slide_id:
        return _apply_slide_patch(slide, patch)

    visual_index = next((index for index, visual in enumerate(slide.visuals) if visual.visual_id == patch.target_id), None)
    if visual_index is None:
        raise RepairApplicationError(f"repair target not found: {patch.target_id}")
    visual = slide.visuals[visual_index]
    _reject_evidence_mutation(patch, visual.evidence)
    if patch.operation == "remove":
        raise RepairApplicationError("removing a visual requires evidence revalidation")
    updated = _apply_visual_patch(visual, patch)
    visuals = list(slide.visuals)
    visuals[visual_index] = updated
    return slide.model_copy(update={"visuals": visuals})


def apply_repair_patches(slide: SlideContentIR, patches: list[RepairPatch], *, max_patches: int = 8) -> SlideContentIR:
    """Apply a bounded sequence of patches in order."""

    if max_patches < 1 or len(patches) > max_patches:
        raise RepairApplicationError(f"repair patch count must be between 1 and {max_patches}")
    current = slide
    seen: set[str] = set()
    for patch in patches:
        if patch.issue_id in seen:
            raise RepairApplicationError(f"duplicate repair issue: {patch.issue_id}")
        seen.add(patch.issue_id)
        current = apply_repair_patch(current, patch)
    return current


def _apply_slide_patch(slide: SlideContentIR, patch: RepairPatch) -> SlideContentIR:
    _reject_evidence_mutation(patch, slide.evidence)
    if patch.operation != "rewrite":
        raise RepairApplicationError("slide-level repairs support only rewrite")
    value = patch.value
    updates: dict[str, Any] = {}
    if "headline" in value:
        updates["headline"] = _required_text(value["headline"], "headline")
    if "body" in value:
        body = value["body"]
        if not isinstance(body, list) or not all(isinstance(item, str) and item.strip() for item in body):
            raise RepairApplicationError("body repair must be a non-empty list of text")
        updates["body"] = body
    if not updates:
        raise RepairApplicationError("slide rewrite requires headline or body")
    return slide.model_copy(update=updates)


def _apply_visual_patch(visual: VisualIR, patch: RepairPatch) -> VisualIR:
    value = patch.value
    if patch.operation == "rewrite":
        if set(value) != {"alt_text"}:
            raise RepairApplicationError("visual rewrite may update alt_text only")
        return visual.model_copy(update={"alt_text": _required_text(value["alt_text"], "alt_text")})
    if patch.operation in {"move", "resize"}:
        allowed = {"x", "y"} if patch.operation == "move" else {"width", "height"}
        if not set(value).issubset(allowed):
            raise RepairApplicationError(f"{patch.operation} repair has unsupported fields")
        bounds = visual.bounds.model_dump()
        bounds.update({key: _finite_number(value[key], key) for key in value})
        return visual.model_copy(update={"bounds": LayoutBox.model_validate(bounds)})
    if patch.operation == "replace":
        if set(value) != {"alt_text"}:
            raise RepairApplicationError("visual replacement may update alt_text only")
        return visual.model_copy(update={"alt_text": _required_text(value["alt_text"], "alt_text")})
    raise RepairApplicationError(f"unsupported repair operation for visual: {patch.operation}")


def _reject_evidence_mutation(patch: RepairPatch, existing: object) -> None:
    if "evidence" in patch.value or "evidence_ids" in patch.value:
        raise RepairApplicationError("repair patches cannot change evidence bindings")
    if patch.operation == "remove" and existing:
        raise RepairApplicationError("removing evidence-bound content requires revalidation")


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RepairApplicationError(f"{name} repair must be non-empty text")
    return value.strip()


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RepairApplicationError(f"{name} repair must be numeric")
    return float(value)


__all__ = ["RepairApplicationError", "apply_repair_patch", "apply_repair_patches"]
