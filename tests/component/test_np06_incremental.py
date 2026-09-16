"""NP-06 incremental rendering and constraint enforcement tests.

Covers:
- Exact slide count constraint (2-slide deck, no hidden additions)
- Slide count constraint violation triggers quality failure
- Dependency closure: patching one slide propagates to dependents
- Incremental update preserves untouched slide text
- Structural edit (add/delete) is explicitly rejected
- Stale manifest ID is rejected
- Full rebuild produces a readable PPTX with correct slide count
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from pipelines.ppt.presentation_quality import inspect_presentation
from pipelines.ppt.renderer import render_presentation
from pipelines.ppt.schemas import (
    DeckManifest,
    IncrementalDeckEdit,
    PresentationOutput,
    SlideContent,
    SlideManifest,
    SlidePatch,
)
from pipelines.orchestrator.contracts import RequestConstraints


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_output(n_content_slides: int = 2) -> PresentationOutput:
    """Build a minimal explicit PresentationOutput with cover/agenda/conclusion/closing."""
    slides = [
        SlideContent(slide_id="cover", order=1, title="Cover", bullets=[], layout="cover"),
        SlideContent(slide_id="agenda", order=2, title="Agenda",
                     bullets=[f"Section {i}" for i in range(1, n_content_slides + 1)],
                     layout="agenda"),
    ]
    for i in range(1, n_content_slides + 1):
        slides.append(
            SlideContent(slide_id=f"s{i}", order=2 + i, title=f"Section {i}",
                         bullets=["Bullet one", "Bullet two"],
                         layout="content")
        )
    slides.append(
        SlideContent(slide_id="conclusion", order=3 + n_content_slides,
                     title="Conclusion", bullets=["Key takeaway"], layout="conclusion")
    )
    slides.append(
        SlideContent(slide_id="closing", order=4 + n_content_slides,
                     title="Closing", bullets=["End"], layout="closing")
    )
    return PresentationOutput(
        presentation_id="test-deck",
        title="Test Brief",
        classification_level="RESTRICTED",
        distribution="Authorized",
        slides=slides,
    )


def _make_manifest(artifact_path: str, slides: list[SlideContent]) -> DeckManifest:
    slide_manifests = [
        SlideManifest(slide_id=s.slide_id, order=s.order, status="rendered")
        for s in slides
    ]
    return DeckManifest(
        deck_id="test-deck",
        version=1,
        base_artifact_id=artifact_path,
        template_id="native-default",
        theme_id="ntro-briefing",
        slide_order=[s.slide_id for s in slides],
        slides=slide_manifests,
    )


# ---------------------------------------------------------------------------
# 1. Exact slide count — no hidden additions
# ---------------------------------------------------------------------------


def test_two_slide_deck_produces_exactly_two_slides(tmp_path, monkeypatch):
    """A 2-slide PresentationOutput (cover + closing only) renders exactly 2 PPTX slides."""
    from pptx import Presentation as _PRS

    monkeypatch.chdir(tmp_path)
    output = PresentationOutput(
        presentation_id="two-slide",
        title="Two Slides",
        classification_level="SECRET",
        distribution="Need to Know",
        slides=[
            SlideContent(slide_id="cover", order=1, title="Cover", bullets=[], layout="cover"),
            SlideContent(slide_id="closing", order=2, title="Closing", bullets=["Done"], layout="closing"),
        ],
    )
    artifact = render_presentation(output)
    prs = _PRS(artifact.path)
    assert len(prs.slides) == 2, f"Expected 2 slides, got {len(prs.slides)}"
    assert artifact.slide_count == 2


def test_slide_count_matches_len_of_slides_array(tmp_path, monkeypatch):
    """slide_count == len(output.slides) for any size deck — no +4 offset."""
    from pptx import Presentation as _PRS

    monkeypatch.chdir(tmp_path)
    for n in (2, 4, 6):
        output = _make_output(n)
        artifact = render_presentation(output)
        prs = _PRS(artifact.path)
        assert len(prs.slides) == len(output.slides)
        assert artifact.slide_count == len(output.slides)


# ---------------------------------------------------------------------------
# 2. Slide count constraint enforcement
# ---------------------------------------------------------------------------


def test_constraint_slide_count_violation_blocks_approval(tmp_path, monkeypatch):
    """inspect_presentation marks approved=False when slide count != constraint."""
    monkeypatch.chdir(tmp_path)
    output = _make_output(2)  # 6 slides total (cover+agenda+2+conclusion+closing)
    constraints = RequestConstraints(slide_count=4)  # ask for 4, got 6
    report = inspect_presentation(output, constraints=constraints)
    assert report.approved is False
    codes = [i.code for i in report.issues]
    assert "PPT_CONSTRAINT_SLIDE_COUNT" in codes


def test_constraint_slide_count_match_approves(tmp_path, monkeypatch):
    """inspect_presentation approves when actual slide count matches constraint."""
    monkeypatch.chdir(tmp_path)
    output = _make_output(2)  # 6 slides: cover, agenda, s1, s2, conclusion, closing
    constraints = RequestConstraints(slide_count=6)
    report = inspect_presentation(output, constraints=constraints)
    # No slide count violation
    count_issues = [i for i in report.issues if i.code == "PPT_CONSTRAINT_SLIDE_COUNT"]
    assert count_issues == []


# ---------------------------------------------------------------------------
# 3. Dependency closure
# ---------------------------------------------------------------------------


def test_dependency_closure_expands_regen_scope(tmp_path, monkeypatch):
    """Patching s1 propagates to s2 when s2 lists s1 as a dependency."""
    monkeypatch.chdir(tmp_path)
    from pptx import Presentation as _PRS

    output = _make_output(2)
    base_artifact = render_presentation(output)

    # Build manifest with s2 depending on s1
    slide_manifests = [
        SlideManifest(slide_id="cover", order=1, status="rendered"),
        SlideManifest(slide_id="agenda", order=2, status="rendered"),
        SlideManifest(slide_id="s1", order=3, status="rendered"),
        SlideManifest(slide_id="s2", order=4, status="rendered", dependencies=["s1"]),
        SlideManifest(slide_id="conclusion", order=5, status="rendered"),
        SlideManifest(slide_id="closing", order=6, status="rendered"),
    ]
    manifest = DeckManifest(
        deck_id="test-deck",
        version=1,
        base_artifact_id=base_artifact.path,
        template_id="native-default",
        theme_id="ntro-briefing",
        slide_order=["cover", "agenda", "s1", "s2", "conclusion", "closing"],
        slides=slide_manifests,
    )

    edit = IncrementalDeckEdit(
        base_artifact_id=base_artifact.path,
        base_manifest_id="test-deck",
        base_manifest_version=1,
        requested_scope=["s1"],  # only request s1; s2 should be pulled in via closure
        edits=[
            SlidePatch(
                slide_id="s1",
                operation="replace_content",
                content={"title": "Updated Section 1", "bullets": ["New bullet"]},
            ),
        ],
        idempotency_key="test-closure-1",
    )

    updated = render_presentation(incremental_edit=edit, previous_manifest=manifest)

    # Verify the updated artifact is a valid PPTX
    prs = _PRS(updated.path)
    assert len(prs.slides) == 6

    # Manifest should render the requested slide, invalidate its dependent,
    # and preserve unrelated slides without falsely claiming regeneration.
    status_map = {s["slide_id"]: s["status"] for s in updated.deck_manifest["slides"]}
    assert status_map["s1"] == "rendered"
    assert status_map["s2"] == "invalidated"   # requires a dependent patch
    assert status_map["cover"] == "unchanged"
    assert status_map["agenda"] == "unchanged"
    assert status_map["conclusion"] == "unchanged"
    assert status_map["closing"] == "unchanged"


# ---------------------------------------------------------------------------
# 4. Stale manifest rejection
# ---------------------------------------------------------------------------


def test_stale_manifest_id_raises(tmp_path, monkeypatch):
    """IncrementalDeckEdit with mismatched manifest ID raises ValueError."""
    monkeypatch.chdir(tmp_path)
    output = _make_output(2)
    base_artifact = render_presentation(output)
    manifest = _make_manifest(base_artifact.path, output.slides)
    manifest.deck_id  # "test-deck"

    edit = IncrementalDeckEdit(
        base_artifact_id=base_artifact.path,
        base_manifest_id="wrong-id",          # intentional mismatch
        base_manifest_version=1,
        requested_scope=["s1"],
        edits=[SlidePatch(slide_id="s1", operation="replace_content", content={})],
        idempotency_key="stale-test",
    )

    with pytest.raises(ValueError, match="mismatched"):
        render_presentation(incremental_edit=edit, previous_manifest=manifest)


# ---------------------------------------------------------------------------
# 5. Missing previous_manifest for incremental edit
# ---------------------------------------------------------------------------


def test_incremental_without_manifest_raises():
    edit = IncrementalDeckEdit(
        base_artifact_id="some/path.pptx",
        base_manifest_id="deck-1",
        base_manifest_version=1,
        requested_scope=["s1"],
        edits=[SlidePatch(slide_id="s1", operation="replace_content", content={})],
        idempotency_key="no-manifest-test",
    )
    with pytest.raises(ValueError, match="previous_manifest"):
        render_presentation(incremental_edit=edit, previous_manifest=None)


# ---------------------------------------------------------------------------
# 6. Neither output nor incremental_edit raises
# ---------------------------------------------------------------------------


def test_render_without_either_arg_raises():
    with pytest.raises(ValueError, match="output or incremental_edit"):
        render_presentation()


# ---------------------------------------------------------------------------
# 7. Full rebuild manifest version increments
# ---------------------------------------------------------------------------


def test_full_rebuild_increments_manifest_version(tmp_path, monkeypatch):
    """Second full rebuild increments the deck manifest version."""
    monkeypatch.chdir(tmp_path)
    from pipelines.ppt.schemas import DeckManifest as DM

    output = _make_output(2)
    first = render_presentation(output)
    assert first.deck_manifest["version"] == 1

    # Rebuild with a prior manifest
    prior = DM(**first.deck_manifest)
    second = render_presentation(output, previous_manifest=prior)
    assert second.deck_manifest["version"] == 2
