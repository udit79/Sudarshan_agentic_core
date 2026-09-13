from __future__ import annotations

import pytest

from pipelines.ppt.child_artifacts import ChildArtifactRef, SlideArtifactBundle, reconcile_slide_artifacts
from pipelines.ppt.schemas import FlowchartNode, FlowchartSpec
from pipelines.ppt.svg_contract import write_canonical_svg
from pipelines.ppt.template_workspace import LayoutContract, PptTemplateContract, write_template_workspace


def _svg() -> str:
    return '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80"><title>brief</title><rect width="120" height="80"/></svg>'


def test_canonical_svg_is_quality_gated_and_hashed(tmp_path) -> None:
    artifact = write_canonical_svg(
        tmp_path / "brief.svg",
        _svg(),
        source_ir=FlowchartSpec(flowchart_id="brief", nodes=[FlowchartNode(node_id="a", label="A")]),
        renderer_version="native-svg@1",
        required_text=("brief",),
    )
    assert artifact.width == 120
    assert len(artifact.source_ir_hash) == 64
    with pytest.raises(ValueError, match="remote"):
        write_canonical_svg(tmp_path / "bad.svg", _svg().replace("<rect", '<script src="https://bad"/><rect'), source_ir="x", renderer_version="x")


def test_template_workspace_validates_master_layout_identity(tmp_path) -> None:
    contract = PptTemplateContract(
        template_id="ntro-briefing",
        version="1",
        master_id="ntro-master",
        design_tokens={"accent": "#38BDF8"},
        layouts=[LayoutContract(layout_id="flow", master_id="ntro-master", purpose="flowchart", required_regions=["title", "visual"])],
    )
    path = write_template_workspace(contract, tmp_path)
    assert path.is_file()
    with pytest.raises(ValueError, match="master"):
        PptTemplateContract(
            template_id="bad", version="1", master_id="master-a", design_tokens={"accent": "#000000"},
            layouts=[LayoutContract(layout_id="x", master_id="master-b", purpose="title", required_regions=["title"])],
        )


def test_child_artifact_reconciliation_is_quality_and_slide_scoped() -> None:
    ref = ChildArtifactRef(
        artifact_id="artifact-1", slide_id="s1", kind="flowchart", quality_report_id="quality-1",
        quality_status="passed", source_ir_hash="a" * 64,
    )
    result = reconcile_slide_artifacts(["s1"], [SlideArtifactBundle(slide_id="s1", artifacts=[ref])])
    assert result["s1"].artifacts[0].artifact_id == "artifact-1"
    with pytest.raises(ValueError, match="unknown slide"):
        reconcile_slide_artifacts(["s1"], [SlideArtifactBundle(slide_id="s2", artifacts=[ref.model_copy(update={"slide_id": "s2"})])])
