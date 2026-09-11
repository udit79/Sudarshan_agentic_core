"""Executable deterministic visual child used by parent skills."""

from __future__ import annotations

import os
import re
from pathlib import Path
from threading import Event

from api.artifacts import ArtifactStore
from pipelines.common.contracts import AdvisoryRequest, PipelineResponse
from pipelines.common.visual_qa import inspect_visual_artifact
from pipelines.orchestrator.cache import stable_hash
from pipelines.ppt.flowchart import flowchart_from_visual_ir, layout_flowchart, render_flowchart_pptx, render_flowchart_svg
from pipelines.ppt.quality import inspect_flowchart
from pipelines.ppt.schemas import LayoutBox, VisualIR


def run_visual_flowchart(request: AdvisoryRequest, *, cancel_event: Event | None = None) -> PipelineResponse:
    """Render one typed flowchart child to verified editable artifacts."""

    if cancel_event is not None and cancel_event.is_set():
        return PipelineResponse("failed", "visual_flowchart", request.task_id, request.task_id, failure="child cancelled")
    raw = request.metadata.get("flowchart")
    if not isinstance(raw, dict):
        raw = {"visual_id": request.task_id, "alt_text": request.query, "nodes": [], "edges": []}
    visual = VisualIR(
        visual_id=str(raw.get("visual_id") or request.task_id),
        kind="flowchart",
        bounds=LayoutBox(x=0.08, y=0.18, width=0.84, height=0.64),
        alt_text=str(raw.get("alt_text") or request.query)[:2000],
        data={key: value for key, value in raw.items() if key not in {"visual_id", "alt_text"}},
    )
    if not visual.data.get("nodes"):
        visual = visual.model_copy(update={"data": {**visual.data, **{
            "nodes": [
                {"node_id": "evidence", "label": "Evidence", "kind": "start"},
                {"node_id": "decision", "label": "Decision", "kind": "end"},
            ],
            "edges": [{"source": "evidence", "target": "decision", "label": "supports"}],
        }}})
    spec = flowchart_from_visual_ir(visual)
    layout = layout_flowchart(spec)
    run_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(request.metadata.get("parent_run_id") or request.task_id))
    root = Path(os.getenv("SUDARSHAN_ARTIFACT_ROOT", "artifacts"))
    output_dir = root / "children" / "flowcharts" / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    svg_path = output_dir / "flowchart.svg"
    pptx_path = output_dir / "flowchart.pptx"
    svg_path.write_text(render_flowchart_svg(spec, layout=layout), encoding="utf-8")
    render_flowchart_pptx(spec, pptx_path, layout=layout, title=visual.alt_text)
    graph_quality = inspect_flowchart(layout)
    for artifact_path, kind in ((svg_path, "flowchart-svg"), (pptx_path, "flowchart-pptx")):
        graph_quality.approved = graph_quality.approved and inspect_visual_artifact(artifact_path, kind="svg" if kind.endswith("svg") else "pptx").approved
    quality_id = "quality-" + stable_hash({"run_id": request.task_id, "visual": visual.model_dump(mode="json")})[:24]
    quality_path = root / ".state" / "quality_reports" / f"{quality_id}.json"
    quality_path.parent.mkdir(parents=True, exist_ok=True)
    quality_path.write_text(graph_quality.model_dump_json(indent=2), encoding="utf-8")
    store = ArtifactStore(root)
    manifests = [
        store.register(
            path,
            run_id=request.metadata.get("parent_run_id", request.task_id),
            kind=kind,
            classification_level=request.classification_level,
            quality_status="passed" if graph_quality.approved else "failed",
            renderer_version=os.getenv("SUDARSHAN_PPT_RENDERER_VERSION", "sudarshan-flowchart@1"),
            schema_version="flowchart-ir@1",
            source_ir_hash=stable_hash(visual.model_dump(mode="json")),
        )
        for path, kind in ((svg_path, "flowchart-svg"), (pptx_path, "flowchart-pptx"))
    ]
    artifact_ids = [manifest.artifact_id for manifest in manifests]
    if not graph_quality.approved:
        return PipelineResponse(
            "failed", "visual_flowchart", request.task_id, request.task_id,
            failure="visual child quality gate failed",
            artifact={"artifact_ids": artifact_ids},
            metadata={"quality_report_id": quality_id, "quality_status": "failed"},
        )
    return PipelineResponse(
        "succeeded", "visual_flowchart", request.task_id, request.task_id,
        output={"kind": "FlowchartIR", "visual_id": visual.visual_id},
        artifact={"artifact_ids": artifact_ids, "quality_report_id": quality_id},
        metadata={"artifact_ids": artifact_ids, "quality_report_id": quality_id, "quality_status": "passed"},
    )


__all__ = ["run_visual_flowchart"]
