"""System-style JSON contracts reaching the deterministic renderers."""

from __future__ import annotations

import json
from pathlib import Path

from pipelines.diagram.export import DiagramExportRequest, export_diagram
from pipelines.diagram.family import DiagramSpec
from pipelines.executive_summary.schemas import ExecutiveSummaryOutput
from pipelines.infographic.normalization import normalize_infographic_output
from pipelines.infographic.renderer import AntVInfographicRenderer
from pipelines.infographic.schemas import InfographicOutput
from pipelines.linkedin.schemas import LinkedInPostOutput
from pipelines.ppt.flowchart import flowchart_from_visual_ir, render_flowchart_pptx, render_flowchart_svg
from pipelines.ppt.schemas import LayoutBox, VisualIR
from pipelines.video.contracts import VideoPackage


FIXTURE = Path(__file__).parents[1] / "fixtures" / "infographic-final-output.json"


def test_system_json_contracts_are_typed_safe_and_renderer_ready(tmp_path) -> None:
    evidence = {
        "evidence_id": "E-1",
        "claim": "The supplied case brief contains one reviewed source.",
        "source_reference": "case://synthetic/source-1",
        "evidence_summary": "Synthetic test data supplied to the pipeline.",
        "confidence": 0.8,
    }

    linkedin = LinkedInPostOutput.model_validate({
        "post_id": "post-1",
        "title": "A verified workflow",
        "post_text": "A short, evidence-linked draft for review.",
        "audience": "technical leaders",
        "call_to_action": "Review the draft.",
        "source_references": ["case://synthetic/source-1"],
        "confidence_statement": "Limited to the supplied observation.",
        "claim_bindings": [{"claim_id": "C-1", "claim": "A verified workflow", "evidence_ids": ["E-1"]}],
    })
    assert linkedin.publish_status == "draft_only"
    assert linkedin.approval_required == "publish"

    summary = ExecutiveSummaryOutput.model_validate({
        "summary_id": "summary-1",
        "title": "Case summary",
        "executive_summary": "One reviewed source is available for assessment.",
            "key_findings": [{
                "finding_id": "kf-1",
                "text": "One reviewed source is available.",
                "evidence_ids": ["E-1"],
            }],
        "implications": ["Further independent verification is needed."],
        "recommended_actions": ["Review the source record."],
        "evidence": [evidence],
        "confidence_statement": "Limited to supplied observations.",
    })
    assert summary.evidence[0].evidence_id == "E-1"

    package = VideoPackage.model_validate({
        "subject": "Case briefing",
        "transcript": "Verified opening statement.",
        "storyboard": [{
            "scene_id": "scene-1",
            "narration": "Verified opening statement.",
            "visual_description": "A restrained briefing room.",
            "duration_seconds": 5,
        }],
    })
    assert package.provider_payload()["video_script"] == "Verified opening statement."
    assert "renderer_id" not in package.provider_payload()

    infographic = normalize_infographic_output(
        InfographicOutput.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    )
    svg_path = Path(AntVInfographicRenderer(output_dir=tmp_path, timeout_seconds=30)(
        infographic.syntax,
        artifact_name="json-contract",
    ))
    assert svg_path.is_file()
    assert "<script" not in svg_path.read_text(encoding="utf-8").lower()

    diagram = DiagramSpec.model_validate({
        "diagram_id": "case-process",
        "kind": "flowchart",
        "title": "Case process",
        "nodes": [
            {"node_id": "ingest", "label": "Ingest", "role": "start", "evidence_ids": ["E-1"]},
            {"node_id": "review", "label": "Review", "role": "process", "evidence_ids": ["E-1"]},
        ],
        "edges": [{"source": "ingest", "target": "review", "label": "source review"}],
        "evidence_ids": ["E-1"],
        "accessibility": {"title": "Case process", "description": "Ingest followed by review."},
    })
    diagram_artifact = export_diagram(
        diagram,
        DiagramExportRequest(output_path=str(tmp_path / "case-process.svg")),
    )
    assert diagram_artifact.quality["approved"] is True

    visual = VisualIR.model_validate({
        "visual_id": "case-flow",
        "kind": "flowchart",
        "bounds": LayoutBox(x=0.1, y=0.1, width=0.8, height=0.8),
        "alt_text": "Ingest followed by review.",
        "evidence": [{"evidence_id": "E-1", "role": "supports"}],
        "data": {
            "nodes": [{"id": "ingest", "label": "Ingest", "kind": "start"}, {"id": "review", "label": "Review", "kind": "end"}],
            "edges": [{"from": "ingest", "to": "review", "label": "review"}],
        },
    })
    flowchart = flowchart_from_visual_ir(visual)
    assert "Ingest" in render_flowchart_svg(flowchart)
    pptx_artifact = render_flowchart_pptx(flowchart, tmp_path / "case-flow.pptx", title="Case process")
    assert Path(pptx_artifact.path).is_file()
