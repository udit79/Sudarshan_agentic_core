"""T20 presentation visual vertical slice.

This service demonstrates the production boundary for one visual child skill:
the DAG owns ordering and recovery, the renderer owns deterministic files, the
quality gate decides promotion, and ``ArtifactStore`` owns immutable delivery
manifests. It intentionally does not make the Harness session the scheduler.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from threading import Event, Lock
from typing import Any, Mapping

from api.artifacts import ArtifactStore
from api.control_plane import ControlPlane
from api.dag_scheduler import DAGSchedulerBridge
from pipelines.orchestrator.contracts import NodeSpec
from pipelines.orchestrator.dag import DAGNodeState, DependencyDAG
from pipelines.ppt.flowchart import FlowchartLayout, layout_flowchart, render_flowchart_pptx, render_flowchart_svg
from pipelines.ppt.quality import VisualDiagnostic, VisualQualityReport, inspect_flowchart
from pipelines.common.visual_qa import inspect_visual_artifact
from pipelines.ppt.schemas import FlowchartSpec, VisualIR
from pipelines.orchestrator.cache import stable_hash


_RUN_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")


class PresentationVerticalSlice:
    """Run one flowchart visual through DAG, QA, and artifact delivery."""

    def __init__(
        self,
        *,
        artifact_root: str | Path | None = None,
        dag_db_path: str | Path | None = None,
        queue_db_path: str | Path | None = None,
        max_workers: int | None = None,
        control_plane: ControlPlane | None = None,
    ) -> None:
        self.artifact_store = ArtifactStore(artifact_root or os.getenv("SUDARSHAN_ARTIFACT_ROOT", "artifacts"))
        dag_path = dag_db_path or os.getenv("SUDARSHAN_PPT_DAG_DB_PATH", "artifacts/.state/presentation_dag.db")
        queue_path = queue_db_path or os.getenv("SUDARSHAN_PPT_DAG_QUEUE_DB_PATH", "artifacts/.state/presentation_dag_queue.db")
        worker_count = max_workers or int(os.getenv("SUDARSHAN_PPT_DAG_MAX_WORKERS", "2"))
        lease_ms = int(os.getenv("SUDARSHAN_PPT_DAG_LEASE_MS", "900000"))
        self.dag = DependencyDAG(dag_path, control_plane=control_plane, lease_ms=lease_ms)
        self._runs: dict[str, dict[str, Any]] = {}
        self._lock = Lock()
        self._quality_root = self.artifact_store.root / ".state" / "quality_reports"
        self._quality_root.mkdir(parents=True, exist_ok=True)
        self.bridge = DAGSchedulerBridge(
            self.dag,
            self._execute_node,
            queue_db_path=queue_path,
            max_workers=worker_count,
            lease_ms=lease_ms,
            control_plane=control_plane,
        )

    def start_flowchart(
        self,
        visual: VisualIR,
        *,
        run_id: str,
        operator_id: str,
        task_id: str | None = None,
        case_id: str = "case-unknown",
        classification_level: str = "RESTRICTED",
        distribution: str = "Authorized NTRO personnel",
    ) -> dict[str, Any]:
        if visual.kind != "flowchart":
            raise ValueError("T20 presentation vertical slice accepts only flowchart visuals")
        if not run_id.strip() or not operator_id.strip():
            raise ValueError("run_id and operator_id are required")
        spec = self._visual_to_spec(visual)
        nodes = [
            NodeSpec(
                node_id="visual.flowchart",
                skill_id="visual.flowchart",
                output_schema="FlowchartIR",
                validator_ids=["flowchart.graph"],
            ),
            NodeSpec(
                node_id="visual.flowchart.qa",
                skill_id="visual.flowchart.qa",
                output_schema="VisualQualityReport",
                dependencies=["visual.flowchart"],
                validator_ids=["flowchart.visual"],
            ),
            NodeSpec(
                node_id="presentation.flowchart.delivery",
                skill_id="presentation.flowchart.delivery",
                output_schema="ArtifactManifest",
                dependencies=["visual.flowchart.qa"],
                required_capabilities=["artifact.write"],
            ),
        ]
        with self._lock:
            self._runs[run_id] = {
                "spec": spec,
                "visual": visual,
                "task_id": task_id or run_id,
                "case_id": case_id,
                "classification_level": classification_level,
                "distribution": distribution,
                "operator_id": operator_id,
                "artifacts": [],
                "quality_report": None,
            }
        payload = {
            "query": "Render the selected flowchart visual",
            "user_id": operator_id,
            "case_id": case_id,
            "task_id": task_id or run_id,
            "classification_level": classification_level,
            "distribution": distribution,
        }
        return self.bridge.start_run(run_id, nodes, payload, operator_id=operator_id)

    def status(self, run_id: str) -> dict[str, Any]:
        result = self.bridge.status(run_id)
        with self._lock:
            state = self._runs.get(run_id, {})
            if state.get("quality_report") is not None:
                result["quality_report"] = state["quality_report"]
            result["artifacts"] = list(state.get("artifacts", []))
            result["task_id"] = state.get("task_id")
            result["case_id"] = state.get("case_id")
        return result

    def close(self) -> None:
        self.bridge.close()

    def _execute_node(self, node: DAGNodeState, payload: Mapping[str, Any], cancel_event: Event) -> Mapping[str, Any]:
        run_id = node.run_id
        with self._lock:
            state = self._runs.get(run_id)
        if state is None:
            return {"status": "failed", "failure_code": "VERTICAL_RUN_NOT_FOUND", "error": "vertical run state is missing"}
        if cancel_event.is_set():
            return {"status": "cancelled", "failure_code": "CANCELLED", "error": "visual job cancelled"}
        if node.node_id == "visual.flowchart":
            return self._render_node(run_id, state)
        if node.node_id == "visual.flowchart.qa":
            return self._quality_node(run_id, state)
        if node.node_id == "presentation.flowchart.delivery":
            refs = [manifest["artifact_id"] for manifest in state.get("artifacts", [])]
            return {"status": "succeeded", "output_ref": ",".join(refs)}
        return {"status": "failed", "failure_code": "UNKNOWN_VERTICAL_NODE", "error": node.node_id}

    def _render_node(self, run_id: str, state: dict[str, Any]) -> Mapping[str, Any]:
        spec: FlowchartSpec = state["spec"]
        layout = layout_flowchart(spec)
        run_dir = self.artifact_store.root / "presentations" / "flowcharts" / _RUN_ID_RE.sub("_", run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        svg_path = run_dir / "flowchart.svg"
        pptx_path = run_dir / "flowchart.pptx"
        svg_path.write_text(render_flowchart_svg(spec, layout=layout), encoding="utf-8")
        render_flowchart_pptx(spec, pptx_path, layout=layout, title=state["visual"].alt_text)
        with self._lock:
            state["layout"] = layout
            state["svg_path"] = svg_path
            state["pptx_path"] = pptx_path
        return {"status": "succeeded", "output_ref": f"flowchart-ir:{run_id}"}

    def _quality_node(self, run_id: str, state: dict[str, Any]) -> Mapping[str, Any]:
        report: VisualQualityReport = inspect_flowchart(state["layout"])
        renderer_version = os.getenv("SUDARSHAN_PPT_RENDERER_VERSION", "sudarshan-flowchart@1")
        for artifact_path, label in ((state["svg_path"], "svg"), (state["pptx_path"], "pptx")):
            rendered = inspect_visual_artifact(
                artifact_path,
                kind=label,
                renderer_version=renderer_version,
            )
            for issue in rendered.issues:
                report.diagnostics.append(
                    VisualDiagnostic(
                        issue_id=f"renderer.{label}",
                        target_id=str(artifact_path),
                        severity="error",
                        message=issue,
                        repairable=False,
                    )
                )
        report.approved = report.approved and not any(item.severity == "error" for item in report.diagnostics)
        report_path = self._quality_root / f"{_RUN_ID_RE.sub('_', run_id)}.json"
        report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        with self._lock:
            state["quality_report"] = report.model_dump(mode="json")
        source_hash = stable_hash(state["spec"].model_dump(mode="json"))
        manifests = []
        for kind, path in (("flowchart-svg", state["svg_path"]), ("presentation-pptx", state["pptx_path"])):
            manifests.append(
                self.artifact_store.register(
                    path,
                    run_id=run_id,
                    kind=kind,
                    classification_level=state["classification_level"],
                    quality_status="passed" if report.approved else "failed",
                    renderer_version=renderer_version,
                    schema_version="flowchart-ir@1",
                    evidence_ids=[
                        evidence_id
                        for node in state["spec"].nodes
                        for evidence_id in (binding.evidence_id for binding in node.evidence)
                    ],
                    source_ir_hash=source_hash,
                )
            )
        with self._lock:
            state["artifacts"] = [manifest.model_dump(mode="json") for manifest in manifests]
        if not report.approved:
            issues = ", ".join(item.issue_id for item in report.diagnostics)
            return {
                "status": "failed",
                "failure_code": "VISUAL_QUALITY_FAILED",
                "error": issues or "visual quality gate failed",
            }
        return {"status": "succeeded", "output_ref": f"quality:{run_id}"}

    @staticmethod
    def _visual_to_spec(visual: VisualIR) -> FlowchartSpec:
        from pipelines.ppt.flowchart import flowchart_from_visual_ir

        return flowchart_from_visual_ir(visual)


__all__ = ["PresentationVerticalSlice"]
