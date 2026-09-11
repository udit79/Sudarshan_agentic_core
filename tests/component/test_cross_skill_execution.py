from pipelines.orchestrator.contracts import RunPolicy
from pipelines.orchestrator.cross_skill import build_child_plan, execute_child_plan
from pipelines.orchestrator.skill_runtime import RunContext, SkillRuntime
from pipelines.orchestrator.types import PipelineAdapter
from pipelines.ppt.child_skill import run_visual_flowchart
from integrations.deepseek_harness.skill_catalog import build_skill_manifests


def test_all_real_parent_types_emit_typed_child_plans():
    assert build_child_plan(
        "presentation.case-brief",
        {"slides": [{"title": "Decision workflow", "bullets": ["Process review"]}]},
        parent_run_id="run-ppt",
        parent_node_id="presentation",
    )[0].skill_id == "visual.flowchart"
    assert build_child_plan(
        "linkedin.post",
        {"title": "Update", "image": {"requested": True, "image_type": "diagram"}},
        parent_run_id="run-linkedin",
        parent_node_id="linkedin_post",
    )[0].required is False
    assert build_child_plan(
        "infographic",
        {"title": "Process", "visual_type": "process"},
        parent_run_id="run-info",
        parent_node_id="infographic",
    )
    assert build_child_plan(
        "video.storyboard",
        {"storyboard": [{"scene_id": "one"}, {"scene_id": "two"}]},
        parent_run_id="run-video",
        parent_node_id="video.storyboard",
    )


def test_real_flowchart_child_executes_and_is_reconciled(tmp_path, monkeypatch):
    monkeypatch.setenv("SUDARSHAN_ARTIFACT_ROOT", str(tmp_path))
    manifests = build_skill_manifests()
    runtime = SkillRuntime(
        {"visual.flowchart": PipelineAdapter("visual.flowchart", run_visual_flowchart)},
        {"visual.flowchart": manifests["visual.flowchart"]},
    )
    parent_policy = RunPolicy(max_model_tokens=4000, max_wall_time_ms=300000, max_parallel_children=2)
    context = RunContext(
        run_id="run-cross-skill",
        task_id="task-cross-skill",
        user_id="operator-1",
        case_id="case-1",
        policy=parent_policy,
        allowed_capabilities=frozenset({"render.diagram"}),
        allowed_tools=frozenset({"diagram.layout", "artifact.write"}),
        allowed_trust_tiers=frozenset({"builtin", "verified"}),
    )
    spec = build_child_plan(
        "infographic",
        {"title": "Process", "visual_type": "process"},
        parent_run_id="run-cross-skill",
        parent_node_id="infographic",
    )
    outcomes = execute_child_plan(runtime, spec, parent_context=context)
    assert outcomes[0].status == "succeeded"
    assert outcomes[0].artifact_ids
    assert outcomes[0].quality_report_id
