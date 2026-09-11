from threading import Event
from integrations.deepseek_harness.application import SudarshanApplication
from integrations.deepseek_harness.skill_catalog import build_skill_manifests
from memory import AccessContext, MemoryLifecycleHooks, MemoryManager, RetrievedMemory, build_context_uri, reference_for_memory
from pipelines.linkedin.humanizer import audit_linkedin_text
from pipelines.linkedin.policies import resolve_top_level_parent, validate_comment_text, validate_reply_text
from pipelines.linkedin.voice_profile import VoiceProfile, voice_context
from pipelines.orchestrator.cross_skill import build_child_plan
from pipelines.orchestrator.contracts import RunPolicy
from pipelines.orchestrator.skill_runtime import RunContext, SkillRuntime
from pipelines.orchestrator.types import PipelineAdapter
from pipelines.ppt.child_skill import run_visual_flowchart


def test_linkedin_specialist_packages_are_discoverable_and_bounded() -> None:
    manifests = build_skill_manifests()
    assert manifests["linkedin.comment"].coordination["pipeline"] == "linkedin_comment"
    assert manifests["linkedin.reply"].coordination["pipeline"] == "linkedin_reply"
    assert manifests["linkedin.reshare"].coordination["pipeline"] == "linkedin_reshare"
    assert manifests["linkedin.humanizer"].version == "2.0.0"
    assert manifests["linkedin.comment"].budget_policy.max_model_tokens == 2500


def test_visual_intent_routes_to_the_matching_child_skill() -> None:
    infographic = build_child_plan(
        "linkedin.post",
        {"title": "Case", "image": {"requested": True, "image_type": "infographic"}},
        parent_run_id="run-1",
        parent_node_id="linkedin_post",
    )
    diagram = build_child_plan(
        "linkedin.post",
        {"title": "Case", "image": {"requested": True, "image_type": "diagram"}},
        parent_run_id="run-2",
        parent_node_id="linkedin_post",
    )
    assert infographic[0].skill_id == "infographic"
    assert diagram[0].skill_id == "visual.flowchart"


def test_linkedin_visual_child_runs_through_runtime_and_reconciles(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SUDARSHAN_ARTIFACT_ROOT", str(tmp_path))
    manifests = build_skill_manifests()
    runtime = SkillRuntime(
        {"visual.flowchart": PipelineAdapter("visual.flowchart", run_visual_flowchart)},
        {"visual.flowchart": manifests["visual.flowchart"]},
    )
    context = RunContext(
        run_id="run-linkedin-child",
        task_id="task-linkedin-child",
        user_id="u1",
        case_id="case-1",
        policy=RunPolicy(max_model_tokens=4000, max_wall_time_ms=300000, max_parallel_children=2),
        allowed_capabilities=frozenset({"render.diagram"}),
        allowed_tools=frozenset({"diagram.layout", "artifact.write"}),
        allowed_trust_tiers=frozenset({"builtin", "verified"}),
    )
    spec = build_child_plan(
        "linkedin.post",
        {"title": "Grounded update", "image": {"requested": True, "image_type": "diagram"}},
        parent_run_id="run-linkedin-child",
        parent_node_id="linkedin_post",
    )
    from pipelines.orchestrator.cross_skill import execute_child_plan

    outcomes = execute_child_plan(runtime, spec, parent_context=context)
    response = {"output": {"visual_child": {"skill_id": "visual.flowchart", "status": "eligible"}}}
    SudarshanApplication._project_visual_child(response, outcomes, spec)
    assert outcomes[0].status == "succeeded"
    assert response["output"]["visual_child"]["status"] == "succeeded"
    assert response["output"]["visual_child"]["artifact_ids"]


def test_humanizer_v2_is_explainable_and_voice_aware() -> None:
    report = audit_linkedin_text(
        "This is revolutionary and guaranteed. However, therefore, additionally, moreover, ultimately.",
        voice_profile={"avoid_phrases": ["revolutionary"]},
    )
    assert report.version == "2.0"
    assert report.diff_summary
    assert any(issue.rule_id == "HUM-VOICE-001" for issue in report.issues)


def test_linkedin_comment_reply_and_parent_policies() -> None:
    assert "comment_contains_link" in validate_comment_text("A useful point; https://example.com")
    assert "reply_too_short" in validate_reply_text("ok")
    assert resolve_top_level_parent({"is_top_level": True, "comment_urn": "urn:li:comment:1"}) == "urn:li:comment:1"
    assert resolve_top_level_parent({"parent_comment_urn": "urn:li:comment:1"}) == "urn:li:comment:1"


def test_voice_profile_is_explicit_and_context_is_bounded() -> None:
    profile = VoiceProfile(profile_id="voice:u1", user_id="u1", tone="direct", preferred_phrases=["show the work"])
    assert "show the work" in voice_context(profile)


def test_context_reference_preserves_hierarchy_and_hooks_are_non_blocking() -> None:
    memory = RetrievedMemory(
        "overview",
        scope_type="case",
        scope_id="case-1",
        source_reference="source-1",
        memory_id="mem-1",
        provenance={"source_id": "source-1"},
        context_level="L1",
    )
    reference = reference_for_memory(memory)
    assert reference.level == "L1"
    assert reference.uri == build_context_uri(scope_type="case", scope_id="case-1", source_id="source-1", level="L1")

    finished = Event()
    received = []
    hooks = MemoryLifecycleHooks(lambda event, payload: (received.append((event, payload)), finished.set()))
    hooks.compaction({"run_id": "run-1", "level": "L1"})
    assert finished.wait(1)
    assert received[0][0] == "compaction"


def test_profile_and_lesson_helpers_are_user_scoped_and_audited() -> None:
    class Backend:
        def remember(self, **kwargs):
            return {"status": "accepted"}

    manager = MemoryManager(Backend())
    context = AccessContext(user_id="u1", case_id="case-1")
    profile = manager.remember_profile({"profile_id": "voice:u1", "tone": "direct"}, context)
    lesson = manager.remember_lesson("Keep visual child fallback explicit.", context)
    assert profile.memory.memory_type.value == "profile"
    assert lesson.memory.memory_type.value == "lesson"
    assert {event.event_type for event in manager.event_log.list()} >= {"profile_updated", "lesson_recorded"}
