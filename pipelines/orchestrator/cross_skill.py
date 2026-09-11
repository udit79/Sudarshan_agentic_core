"""Small typed cross-skill planner and bounded executor."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Mapping

from pipelines.orchestrator.child_tasks import reconcile_child_result, validate_child_plan
from pipelines.orchestrator.contracts import ChildTaskOutcome, ChildTaskSpec, RunPolicy, SkillResult
from pipelines.orchestrator.skill_runtime import RunContext, SkillRuntime


_VISUAL_WORDS = ("process", "workflow", "dependency", "decision", "lifecycle", "flowchart", "timeline")


def build_child_plan(
    parent_skill: str,
    output: Any,
    *,
    parent_run_id: str,
    parent_node_id: str,
    requested_visuals: Mapping[str, Any] | None = None,
) -> tuple[ChildTaskSpec, ...]:
    """Convert each supported parent output into typed specialist requests."""

    payload = output.model_dump(mode="json") if hasattr(output, "model_dump") else dict(output or {})
    parent_run_id = str(parent_run_id).strip() or "unbound-parent"
    requested = dict(requested_visuals or {})
    parent = str(parent_skill).strip().lower()
    specs: list[ChildTaskSpec] = []

    if parent in {"presentation", "presentation.case-brief", "ppt"}:
        for index, slide in enumerate(payload.get("slides", []), start=1):
            slide_data = dict(slide or {})
            text = " ".join([str(slide_data.get("title", "")), *map(str, slide_data.get("bullets", []))]).lower()
            explicit = requested.get(str(index), requested.get(f"slide-{index}", False))
            if not explicit and not any(word in text for word in _VISUAL_WORDS):
                continue
            specs.append(_flowchart_spec(
                f"{parent_run_id}:slide-{index}:visual",
                parent_run_id,
                f"slide-{index}",
                f"Create the editable visual for slide {index}.",
                _sequence_graph(f"slide-{index}", slide_data.get("title", f"Slide {index}")),
                required=bool(explicit) if isinstance(explicit, bool) else True,
            ))

    elif parent in {"linkedin", "linkedin.post", "linkedin_post"}:
        image = dict(payload.get("image") or {})
        visual = dict(payload.get("visual_child") or {})
        if image.get("requested") and image.get("image_type") in {"diagram", "infographic"}:
            specs.append(_flowchart_spec(
                f"{parent_run_id}:linkedin:visual",
                parent_run_id,
                parent_node_id,
                "Create the optional LinkedIn visual from the approved draft claims.",
                _sequence_graph("linkedin", payload.get("title", "LinkedIn visual")),
                required=False,
            ))

    elif parent == "infographic":
        if payload.get("visual_type") in {"process", "flow", "hierarchy", "timeline"}:
            specs.append(_flowchart_spec(
                f"{parent_run_id}:infographic:visual",
                parent_run_id,
                parent_node_id,
                "Create the editable graph companion for the infographic.",
                _sequence_graph("infographic", payload.get("title", "Infographic")),
                required=False,
            ))

    elif parent in {"video", "video.storyboard", "video_storyboard"}:
        scenes = list(payload.get("storyboard", []))
        if len(scenes) > 1:
            specs.append(_flowchart_spec(
                f"{parent_run_id}:video:storyboard-visual",
                parent_run_id,
                parent_node_id,
                "Create an editable storyboard timeline for the video package.",
                _scene_graph(scenes),
                required=False,
            ))

    return validate_child_plan(specs)


def execute_child_plan(
    runtime: SkillRuntime,
    specs: tuple[ChildTaskSpec, ...] | list[ChildTaskSpec],
    *,
    parent_context: RunContext,
) -> tuple[ChildTaskOutcome, ...]:
    """Run ready children in parallel and reconcile every result safely."""

    pending = {item.child_id: item for item in validate_child_plan(specs)}
    outcomes: dict[str, ChildTaskOutcome] = {}
    while pending:
        ready = [item for item in pending.values() if all(dep in outcomes for dep in item.dependencies)]
        if not ready:
            raise ValueError("child plan cannot make progress; dependency cycle or missing result")
        with ThreadPoolExecutor(
            max_workers=min(parent_context.policy.max_parallel_children, len(ready)),
            thread_name_prefix="sudarshan-child-plan",
        ) as pool:
            futures = {pool.submit(runtime.invoke_child_task, item, parent_context=parent_context): item for item in ready}
            for future in as_completed(futures):
                item = futures[future]
                result = future.result()
                outcomes[item.child_id] = reconcile_child_result(item, result)
                pending.pop(item.child_id, None)
    return tuple(outcomes[item.child_id] for item in validate_child_plan(specs))


def _flowchart_spec(child_id: str, run_id: str, node_id: str, query: str, graph: dict[str, Any], *, required: bool) -> ChildTaskSpec:
    return ChildTaskSpec(
        child_id=child_id,
        parent_run_id=run_id,
        parent_node_id=node_id,
        skill_id="visual.flowchart",
        input_payload={"query": query, "flowchart": graph},
        output_artifact_types=["diagram.ir", "svg", "pptx"],
        required=required,
        fallback="text-only-or-timeline-fallback",
        policy=RunPolicy(max_model_tokens=1500, max_wall_time_ms=120_000, max_tool_calls=8, max_parallel_children=1),
    )


def _sequence_graph(prefix: str, title: Any) -> dict[str, Any]:
    return {
        "visual_id": f"{prefix}-visual",
        "alt_text": str(title or prefix),
        "direction": "left-to-right",
        "nodes": [
            {"node_id": f"{prefix}-start", "label": "Evidence", "kind": "start"},
            {"node_id": f"{prefix}-end", "label": str(title or "Decision")[:160], "kind": "end"},
        ],
        "edges": [{"source": f"{prefix}-start", "target": f"{prefix}-end", "label": "supports"}],
    }


def _scene_graph(scenes: list[Any]) -> dict[str, Any]:
    nodes = []
    edges = []
    for index, scene in enumerate(scenes, start=1):
        data = dict(scene or {})
        node_id = f"scene-{index}"
        nodes.append({"node_id": node_id, "label": str(data.get("scene_id", node_id))[:160], "kind": "process"})
        if index > 1:
            edges.append({"source": f"scene-{index - 1}", "target": node_id, "label": "next"})
    return {"visual_id": "storyboard-timeline", "alt_text": "Video storyboard timeline", "direction": "left-to-right", "nodes": nodes, "edges": edges}


__all__ = ["build_child_plan", "execute_child_plan"]
