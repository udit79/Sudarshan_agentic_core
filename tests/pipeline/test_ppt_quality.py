from __future__ import annotations

from pipelines.ppt.flowchart import layout_flowchart
from pipelines.ppt.quality import inspect_flowchart, repair_patches
from pipelines.ppt.schemas import EvidenceBinding, FlowchartEdge, FlowchartNode, FlowchartSpec


def test_quality_report_emits_source_map_and_passes_clean_graph() -> None:
    spec = FlowchartSpec(
        flowchart_id="clean",
        nodes=[
            FlowchartNode(node_id="a", label="Start", evidence=[EvidenceBinding(evidence_id="e-1")]),
            FlowchartNode(node_id="b", label="Review", evidence=[EvidenceBinding(evidence_id="e-2")]),
        ],
        edges=[FlowchartEdge(source="a", target="b")],
    )
    report = inspect_flowchart(layout_flowchart(spec))
    assert report.approved is True
    assert [entry.target_id for entry in report.source_map] == ["a", "b"]
    assert report.source_map[0].evidence_ids == ["e-1"]
    assert repair_patches(report) == []


def test_quality_report_finds_label_overflow_and_creates_targeted_patch() -> None:
    spec = FlowchartSpec(
        flowchart_id="long-label",
        nodes=[
            FlowchartNode(node_id="a", label="A very long label that cannot fit in the allocated node geometry"),
            FlowchartNode(node_id="b", label="B"),
        ],
        edges=[FlowchartEdge(source="a", target="b")],
    )
    report = inspect_flowchart(layout_flowchart(spec))
    assert report.approved is False
    assert any(item.issue_id == "flowchart.text-overflow" for item in report.diagnostics)
    patches = repair_patches(report)
    assert any(patch.operation == "rewrite" and patch.target_id == "a" for patch in patches)

