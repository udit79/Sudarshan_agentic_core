from __future__ import annotations

from pathlib import Path

import pytest

from pipelines.ppt.renderer import render_presentation
from pipelines.ppt.schemas import DeckManifest, IncrementalDeckEdit, SlidePatch
from pipelines.ppt.template_workspace import LayoutContract, PptTemplateContract
from tests.component.test_np06_incremental import _make_output, _make_manifest


def _template() -> PptTemplateContract:
    return PptTemplateContract(
        template_id="ntro-briefing",
        version="1",
        master_id="ntro-master",
        design_tokens={"background": "#0B1220", "accent": "#38BDF8"},
        layouts=[
            LayoutContract(layout_id="title", master_id="ntro-master", purpose="title", required_regions=["title"]),
            LayoutContract(layout_id="narrative", master_id="ntro-master", purpose="narrative", required_regions=["title", "body"]),
            LayoutContract(layout_id="closing", master_id="ntro-master", purpose="closing", required_regions=["title", "body"]),
        ],
    )


def test_full_manifest_contains_source_and_rendered_slide_hashes(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    artifact = render_presentation(_make_output(2))
    manifest = DeckManifest.model_validate(artifact.deck_manifest)
    assert all(len(slide.source_ir_hash or "") == 64 for slide in manifest.slides)
    assert all(len(slide.rendered_part_hash or "") == 64 for slide in manifest.slides)
    assert manifest.master_id == "native-master"


def test_incremental_manifest_preserves_unrelated_slide_part_hashes(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    output = _make_output(2)
    base = render_presentation(output)
    base_manifest = DeckManifest.model_validate(base.deck_manifest)
    edit = IncrementalDeckEdit(
        base_artifact_id=base.path,
        base_manifest_id=base_manifest.deck_id,
        base_manifest_version=base_manifest.version,
        requested_scope=["s1"],
        edits=[SlidePatch(slide_id="s1", operation="replace_content", content={"title": "Updated"})],
        idempotency_key="p1-hash-test",
    )
    updated = render_presentation(incremental_edit=edit, previous_manifest=base_manifest)
    before = {item.slide_id: item for item in base_manifest.slides}
    after = {item["slide_id"]: item for item in updated.deck_manifest["slides"]}
    assert after["cover"]["status"] == "unchanged"
    assert after["cover"]["rendered_part_hash"] == before["cover"].rendered_part_hash
    assert after["s1"]["status"] == "rendered"
    assert after["s1"]["source_ir_hash"] != before["s1"].source_ir_hash


def test_template_contract_is_required_for_non_default_templates(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    output = _make_output(1).model_copy(update={"template_id": "ntro-briefing"})
    with pytest.raises(ValueError, match="template_contract"):
        render_presentation(output)
    artifact = render_presentation(output, template_contract=_template())
    assert artifact.deck_manifest["master_id"] == "ntro-master"


def test_template_contract_rejects_unplanned_slide_purpose(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    output = _make_output(1).model_copy(update={"template_id": "ntro-briefing"})
    template = _template().model_copy(update={"layouts": [_template().layouts[0]]})
    with pytest.raises(ValueError, match="no layout"):
        render_presentation(output, template_contract=template)
