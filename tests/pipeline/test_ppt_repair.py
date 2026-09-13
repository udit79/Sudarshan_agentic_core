from __future__ import annotations

import pytest

from pipelines.ppt.repair import RepairApplicationError, apply_repair_patch, apply_repair_patches
from pipelines.ppt.schemas import EvidenceBinding, LayoutBox, RepairPatch, SlideContentIR, VisualIR


def make_slide() -> SlideContentIR:
    return SlideContentIR(
        slide_id="slide-1",
        headline="Case overview",
        body=["Verified observation"],
        evidence=[EvidenceBinding(evidence_id="ev-1")],
        visuals=[VisualIR(
            visual_id="visual-1",
            kind="shape",
            bounds=LayoutBox(x=0.1, y=0.1, width=0.3, height=0.2),
            alt_text="Case overview visual",
            evidence=[EvidenceBinding(evidence_id="ev-1")],
        )],
    )


def test_targeted_geometry_repair_preserves_evidence() -> None:
    repaired = apply_repair_patch(make_slide(), RepairPatch(
        issue_id="flowchart.off-canvas",
        target_id="visual-1",
        operation="move",
        value={"x": 0.2, "y": 0.25},
    ))

    assert repaired.visuals[0].bounds.x == 0.2
    assert repaired.visuals[0].bounds.y == 0.25
    assert repaired.visuals[0].evidence[0].evidence_id == "ev-1"


def test_repair_rejects_evidence_injection_and_invalid_bounds() -> None:
    with pytest.raises(RepairApplicationError, match="evidence bindings"):
        apply_repair_patch(make_slide(), RepairPatch(
            issue_id="bad-evidence",
            target_id="visual-1",
            operation="move",
            value={"x": 0.2, "evidence_ids": ["ev-new"]},
        ))
    with pytest.raises(ValueError, match="within normalized slide bounds"):
        apply_repair_patch(make_slide(), RepairPatch(
            issue_id="bad-bounds",
            target_id="visual-1",
            operation="resize",
            value={"width": 0.95},
        ))


def test_slide_rewrite_is_bounded_and_patch_sequence_is_deduplicated() -> None:
    patch = RepairPatch(issue_id="rewrite-1", target_id="slide-1", operation="rewrite", value={"headline": "Updated overview"})
    repaired = apply_repair_patches(make_slide(), [patch])
    assert repaired.headline == "Updated overview"
    with pytest.raises(RepairApplicationError, match="duplicate repair issue"):
        apply_repair_patches(make_slide(), [patch, patch])
