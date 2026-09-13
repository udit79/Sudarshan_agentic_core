import json

import pytest

from pipelines.ppt.schemas import DeckPlan, EvidenceBinding, SlideContentIR, SlideSpec
from pipelines.ppt.source_workspace import EvidenceSourceBinding, write_deck_source_workspace


def _deck() -> DeckPlan:
    evidence = EvidenceBinding(evidence_id="E-1")
    return DeckPlan(
        presentation_id="deck-source-1",
        title="Source contract",
        theme_id="ntro",
        slides=[SlideSpec(
            slide_id="s1",
            sequence=1,
            intent="brief",
            one_message="A sourced message",
            content=SlideContentIR(slide_id="s1", headline="A sourced message", evidence=[evidence]),
            evidence=[evidence],
        )],
        evidence=[evidence],
    )


def test_source_workspace_writes_typed_manifests_without_raw_content(tmp_path) -> None:
    workspace = write_deck_source_workspace(
        _deck(),
        [EvidenceSourceBinding(evidence_id="E-1", source_ref="evidence://case-1/E-1")],
        tmp_path,
    )
    assert workspace.workspace_id.startswith("ppt-source-")
    payload = json.loads((tmp_path / "source-manifest.json").read_text(encoding="utf-8"))
    assert payload["sources"][0]["source_ref"] == "evidence://case-1/E-1"
    assert "raw" not in json.dumps(payload).lower()


def test_source_workspace_rejects_local_paths_and_missing_bindings(tmp_path) -> None:
    with pytest.raises(ValueError, match="opaque"):
        EvidenceSourceBinding(evidence_id="E-1", source_ref="C:\\secret.txt")
    with pytest.raises(ValueError, match="missing source"):
        write_deck_source_workspace(_deck(), [], tmp_path)
