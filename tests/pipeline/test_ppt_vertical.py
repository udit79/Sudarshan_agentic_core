from __future__ import annotations

import time

from pipelines.ppt.schemas import VisualIR, LayoutBox
from pipelines.ppt.vertical import PresentationVerticalSlice


def visual() -> VisualIR:
    return VisualIR(
        visual_id="vertical-flow",
        kind="flowchart",
        bounds=LayoutBox(x=0.08, y=0.18, width=0.84, height=0.64),
        alt_text="Vertical flowchart",
        data={
            "nodes": [
                {"id": "a", "label": "Ingest", "kind": "start"},
                {"id": "b", "label": "Review", "kind": "end"},
            ],
            "edges": [{"from": "a", "to": "b"}],
        },
    )


def wait_for_terminal(service: PresentationVerticalSlice, run_id: str):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        state = service.status(run_id)
        if state["status"] in {"succeeded", "failed", "blocked"}:
            return state
        time.sleep(0.01)
    raise AssertionError(service.status(run_id))


def test_flowchart_vertical_slice_delivers_verified_manifests_and_quality(tmp_path) -> None:
    service = PresentationVerticalSlice(
        artifact_root=tmp_path / "artifacts",
        dag_db_path=tmp_path / "dag.db",
        queue_db_path=tmp_path / "queue.db",
        max_workers=2,
    )
    try:
        accepted = service.start_flowchart(
            visual(),
            run_id="vertical-run",
            operator_id="operator-1",
            case_id="case-1",
        )
        assert accepted["run_id"] == "vertical-run"
        state = wait_for_terminal(service, "vertical-run")
        assert state["status"] == "succeeded"
        assert state["quality_report"]["approved"] is True
        assert {item["kind"] for item in state["artifacts"]} == {"flowchart-svg", "presentation-pptx"}
        for item in state["artifacts"]:
            assert item["quality_status"] == "passed"
            loaded, _ = service.artifact_store.get(item["artifact_id"])
            assert loaded.sha256 == item["sha256"]
    finally:
        service.close()


def test_flowchart_vertical_slice_fails_quality_without_delivery(tmp_path) -> None:
    bad = VisualIR(
        visual_id="bad-flow",
        kind="flowchart",
        bounds=LayoutBox(x=0.08, y=0.18, width=0.84, height=0.64),
        alt_text="Bad flowchart",
        data={
            "nodes": [
                {"id": "a", "label": "A very long label that cannot fit in the allocated node geometry"},
                {"id": "b", "label": "B"},
            ],
            "edges": [{"from": "a", "to": "b"}],
        },
    )
    service = PresentationVerticalSlice(
        artifact_root=tmp_path / "artifacts",
        dag_db_path=tmp_path / "dag.db",
        queue_db_path=tmp_path / "queue.db",
    )
    try:
        service.start_flowchart(bad, run_id="bad-run", operator_id="operator-1")
        state = wait_for_terminal(service, "bad-run")
        assert state["status"] == "failed"
        assert state["quality_report"]["approved"] is False
        assert all(item["quality_status"] == "failed" for item in state["artifacts"])
    finally:
        service.close()
