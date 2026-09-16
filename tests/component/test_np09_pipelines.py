"""Component tests for NP-09: Pipeline Release Correctness.

Verifies:
1. Advisory & Executive Summary: canonical evidence ID hashing, governed ID preservation,
   strict ClaimBinding & KeyFinding evidence linkage, approval-aware memory release gating.
2. LinkedIn & Social: claim bindings with verified evidence, humanizer score >= 0.70 &
   AI-tell blocking, non-duplicating provider_pending reconciliation.
3. Video: VideoProviderJobStore submit_unknown lifecycle, attempt-scoped scene cache paths.
4. Infographic & Diagram: standalone SVG strict accessibility enforcement,
   authenticated OperatorWaiver requirement for fallback releases.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Stub crewai and all required sub-packages BEFORE any pipeline module import.
# ---------------------------------------------------------------------------

def _make_pkg(name: str) -> types.ModuleType:
    """Create a stub package module and wire it into sys.modules."""
    mod = types.ModuleType(name)
    mod.__path__ = []  # type: ignore[assignment]
    mod.__package__ = name
    sys.modules[name] = mod
    parts = name.rsplit(".", 1)
    if len(parts) == 2 and parts[0] in sys.modules:
        setattr(sys.modules[parts[0]], parts[1], mod)
    return mod


_CREWAI_STUBS = [] if "crewai" in sys.modules else [
    "crewai",
    "crewai.flow",
    "crewai.flow.flow",
    "crewai.flow.persistence",
    "crewai.flow.human_feedback",
    "crewai.tools",
]
_CREATED_STUBS: list[str] = []
for _mod_name in _CREWAI_STUBS:
    if _mod_name not in sys.modules:
        _make_pkg(_mod_name)
        _CREATED_STUBS.append(_mod_name)

class _FlowStub:
    def __init_subclass__(cls, **kwargs):  # noqa: ANN001, ANN002, ANN003
        super().__init_subclass__(**kwargs)

    def __init__(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        pass

    def __class_getitem__(cls, item):  # noqa: ANN001
        """Allow Flow[TaskState] generic syntax."""
        return cls


if _CREWAI_STUBS:
    # Populate top-level crewai stubs.
    _crewai = sys.modules["crewai"]
    for _attr in ("Agent", "Crew", "Process", "Task", "TaskOutput"):
        if not hasattr(_crewai, _attr):
            setattr(_crewai, _attr, MagicMock)

    _ff = sys.modules["crewai.flow.flow"]
    _ff.Flow = _FlowStub
    _ff.listen = lambda *a, **kw: (lambda f: f)
    _ff.or_ = MagicMock
    _ff.router = lambda *a, **kw: (lambda f: f)
    _ff.start = lambda *a, **kw: (lambda f: f)

    _fp = sys.modules["crewai.flow.persistence"]
    _fp.FlowPersistence = MagicMock
    _fp.SQLiteFlowPersistence = MagicMock
    _fp.persist = lambda *a, **kw: (lambda f: f)

    _fhf = sys.modules["crewai.flow.human_feedback"]
    _fhf.HumanFeedback = MagicMock

    _ct = sys.modules["crewai.tools"]
    _ct.BaseTool = MagicMock

# Stub the memory module
if "memory" not in sys.modules:
    _mem = _make_pkg("memory")
    _CREATED_STUBS.append("memory")
    for _attr in ("AccessContext", "KnowledgeUnit", "MemoryType", "ScopeType", "Source", "SourceType"):
        setattr(_mem, _attr, MagicMock)

# ---------------------------------------------------------------------------
# Now safe to import pipeline modules
# ---------------------------------------------------------------------------
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import pytest  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from pipelines.advisory.schemas import (  # noqa: E402
    ActionItem,
    AdvisoryOutput,
    ClaimBinding,
    EvidenceItem,
    Recommendation,
    deterministic_evidence_id,
)
from pipelines.executive_summary.schemas import ExecutiveSummaryOutput, KeyFinding  # noqa: E402
from pipelines.common.release_gate import can_release_to_case_memory  # noqa: E402
from pipelines.infographic.quality import SVGQualityReport, inspect_svg  # noqa: E402
from pipelines.infographic.waiver import OperatorWaiverStore  # noqa: E402
from pipelines.linkedin.humanizer import audit_linkedin_text  # noqa: E402
from pipelines.linkedin.schemas import (  # noqa: E402
    HumanizerReport,
    LinkedInClaimBinding,
    LinkedInPostOutput,
)
from pipelines.video.provider_jobs import VideoProviderJobStore  # noqa: E402
from integrations.providers.social import (  # noqa: E402
    SocialCapabilityBoundary,
    SocialReceipt,
    SocialRequest,
)
from integrations.providers.social_approval import (  # noqa: E402
    SocialApprovalRecord,
    SocialApprovalStore,
    SocialReleaseService,
)

# These stubs are needed only while importing the lightweight contract tests.
# Leaving them in sys.modules contaminates later pipeline tests: a real Flow
# class can be replaced by _FlowStub depending on pytest collection order.
for _mod_name in reversed(_CREATED_STUBS):
    _module = sys.modules.pop(_mod_name, None)
    if _module is None or "." not in _mod_name:
        continue
    _parent_name, _child_name = _mod_name.rsplit(".", 1)
    _parent = sys.modules.get(_parent_name)
    if _parent is not None and getattr(_parent, _child_name, None) is _module:
        delattr(_parent, _child_name)


# ---------------------------------------------------------------------------
# Lightweight helpers that mirror flow quality_output_issues without crewai
# ---------------------------------------------------------------------------

def _exec_summary_quality_issues(output: ExecutiveSummaryOutput) -> list[str]:
    """Mirror of ExecutiveSummaryFlow.quality_output_issues."""
    issues: list[str] = []
    known_evidence_ids = {e.evidence_id for e in output.evidence}
    for kf in output.key_findings:
        if not kf.evidence_ids:
            issues.append(f"key finding '{kf.finding_id}' must cite at least one evidence ID")
        for eid in kf.evidence_ids:
            if eid not in known_evidence_ids:
                issues.append(
                    f"key finding '{kf.finding_id}' references unknown evidence id '{eid}'"
                )
    for claim in output.claim_bindings:
        if claim.role == "fact" and not claim.evidence_ids:
            issues.append(
                f"factual claim '{claim.claim_id}' must cite at least one evidence ID"
            )
        for eid in claim.evidence_ids:
            if eid not in known_evidence_ids:
                issues.append(
                    f"claim '{claim.claim_id}' references unknown evidence ID '{eid}'"
                )
    return issues


def _linkedin_quality_issues(output: LinkedInPostOutput) -> list[str]:
    """Mirror of LinkedInPostFlow.quality_output_issues."""
    issues: list[str] = []
    if not output.claim_bindings:
        issues.append("claim_bindings must identify evidence for every material public claim")
    else:
        for binding in output.claim_bindings:
            if binding.role == "fact" and not (binding.evidence_ids or binding.source_references):
                issues.append(
                    f"factual claim binding '{binding.claim_id}' "
                    "must reference verified evidence_ids or source_references"
                )
    if output.humanizer_report.score < 0.70:
        issues.append(
            f"humanizer score {output.humanizer_report.score:.2f} is below the release threshold of 0.70"
        )
    if not output.humanizer_report.approved:
        blocking = [
            i.message for i in output.humanizer_report.issues if i.severity == "block"
        ]
        if blocking:
            issues.extend(blocking)
        elif output.humanizer_report.score >= 0.70:
            issues.append("humanizer review rejected the draft")
    if output.approval_required != "publish" or output.publish_status != "draft_only":
        issues.append("LinkedIn generation must remain draft_only and require separate publish approval")
    return issues


def _make_advisory(**kwargs: Any) -> AdvisoryOutput:
    ev_list: list[EvidenceItem] = kwargs.get("evidence", [])
    ev0_id = ev_list[0].evidence_id if ev_list else None

    recs = kwargs.pop("recommendations", None)
    if recs is None:
        recs = [
            Recommendation(
                priority="P1",
                action="Enact reservations",
                responsible_party="DevOps Lead",
                timeline="30 days",
                rationale="Cost savings.",
                evidence_ids=[ev0_id] if ev0_id else [],
            )
        ]

    action_items = kwargs.pop("action_items", None)
    if action_items is None:
        action_items = [
            ActionItem(
                priority="P1",
                action="Review current spend",
                responsible_party="Finance Lead",
                timeline="14 days",
                completion_signal="Report delivered",
            )
        ]

    base: dict[str, Any] = {
        "advisory_id": "adv-1",
        "title": "Advisory Brief",
        "subject": "Cloud Spend",
        "severity_rating": "high",
        "classification_level": "SECRET",
        "distribution": "internal",
        "executive_summary": "Executive briefing on cloud cost reduction.",
        "overview": "Overview of infrastructure metrics.",
        "situation": "Situation is stable.",
        "assessment": "Assessment indicates optimization opportunity.",
        "impact_analysis": "Cost savings expected.",
        "observed_patterns": ["Compute spikes at peak hours"],
        "recommendations": recs,
        "action_items": action_items,
        "evidence": ev_list,
        "confidence_statement": "High confidence based on verified billing logs.",
    }
    base.update(kwargs)
    return AdvisoryOutput(**base)


# =========================================================================
# 1. Advisory & Executive Summary Tests
# =========================================================================

def test_advisory_deterministic_evidence_id_hashing() -> None:
    id1 = deterministic_evidence_id("https://sec.gov/filing/10k", "Revenue grew 14% year-over-year")
    id2 = deterministic_evidence_id("https://sec.gov/filing/10k", "Revenue grew 14% year-over-year")
    id3 = deterministic_evidence_id("https://sec.gov/filing/10q", "Revenue grew 14% year-over-year")
    assert id1 == id2
    assert id1.startswith("evi-")
    assert id1 != id3


def test_advisory_evidence_item_preserves_governed_id() -> None:
    gov_item = EvidenceItem(
        evidence_id="evi-governed-12345",
        source_reference="corp-governance://sec/2024",
        claim="Operating margin reached 22%",
        evidence_summary="Operating margin reached 22% in official filings.",
        confidence=0.92,
    )
    assert gov_item.evidence_id == "evi-governed-12345"

    auto_item = EvidenceItem(
        source_reference="corp-governance://sec/2024",
        claim="Operating margin reached 22%",
        evidence_summary="Operating margin reached 22% in official filings.",
        confidence=0.92,
    )
    assert auto_item.evidence_id.startswith("evi-")


def test_advisory_claim_binding_and_action_item_linkage() -> None:
    ev = EvidenceItem(
        source_reference="https://audit.internal/report.pdf",
        claim="Cloud infrastructure costs increased by 35% in Q3",
        evidence_summary="Infrastructure cost analysis.",
        confidence=0.95,
    )
    valid_output = _make_advisory(
        evidence=[ev],
        claim_bindings=[
            ClaimBinding(
                claim_id="cb-1",
                text="Cloud infrastructure costs increased by 35% in Q3",
                evidence_ids=[ev.evidence_id],
                role="fact",
            )
        ],
        action_items=[
            ActionItem(
                priority="P1",
                action="Enact compute reservations to reduce cloud spend by 20%",
                responsible_party="DevOps Lead",
                timeline="30 days",
                completion_signal="Cloud budget shows 20% drop",
                evidence_ids=[ev.evidence_id],
            )
        ],
        recommendations=[
            Recommendation(
                priority="P1",
                action="Enact reservations",
                responsible_party="DevOps Lead",
                timeline="30 days",
                rationale="Cost savings.",
                evidence_ids=[ev.evidence_id],
            )
        ],
    )
    assert len(valid_output.claim_bindings) == 1
    assert valid_output.action_items[0].evidence_ids == [ev.evidence_id]

    with pytest.raises(ValidationError, match="unknown evidence ID"):
        _make_advisory(
            evidence=[ev],
            claim_bindings=[],
            action_items=[
                ActionItem(
                    priority="P1",
                    action="Do something ungrounded",
                    responsible_party="DevOps Lead",
                    timeline="30 days",
                    completion_signal="Done",
                    evidence_ids=["evi-does-not-exist"],
                )
            ],
            recommendations=[
                Recommendation(
                    priority="P1",
                    action="Enact reservations",
                    responsible_party="DevOps Lead",
                    timeline="30 days",
                    rationale="Cost savings.",
                    evidence_ids=[ev.evidence_id],
                )
            ],
        )

    with pytest.raises(ValidationError, match="unknown evidence ID"):
        _make_advisory(
            evidence=[ev],
            claim_bindings=[
                ClaimBinding(
                    claim_id="cb-2",
                    text="Invented fact",
                    evidence_ids=["evi-missing"],
                    role="fact",
                )
            ],
            action_items=[
                ActionItem(
                    priority="P3",
                    action="Review bills",
                    responsible_party="Finance Lead",
                    timeline="60 days",
                    completion_signal="Review complete",
                    evidence_ids=[ev.evidence_id],
                )
            ],
            recommendations=[
                Recommendation(
                    priority="P1",
                    action="Enact reservations",
                    responsible_party="DevOps Lead",
                    timeline="30 days",
                    rationale="Cost savings.",
                    evidence_ids=[ev.evidence_id],
                )
            ],
        )


def test_executive_summary_key_finding_evidence_linkage() -> None:
    ev_id = deterministic_evidence_id("doc://q3", "Operating profit grew by 4M")
    ev_item = EvidenceItem(
        evidence_id=ev_id,
        source_reference="doc://q3",
        claim="Operating profit grew by 4M",
        evidence_summary="Financial disclosure.",
        confidence=0.95,
    )
    output = ExecutiveSummaryOutput(
        summary_id="sum-1",
        title="Quarterly Review",
        executive_summary="Quarterly executive summary.",
        evidence=[ev_item],
        key_findings=[
            KeyFinding(finding_id="kf-1", text="Operating profit grew by 4M", evidence_ids=[ev_id])
        ],
        implications=["Positive margin expansion"],
        recommended_actions=["Maintain current operational efficiency"],
        confidence_statement="High confidence based on validated reports.",
        claim_bindings=[
            ClaimBinding(
                claim_id="cb-1",
                text="Operating profit grew by 4M",
                evidence_ids=[ev_id],
                role="fact",
            )
        ],
    )
    assert output.key_findings[0].evidence_ids == [ev_id]
    assert len(_exec_summary_quality_issues(output)) == 0

    with pytest.raises(ValidationError, match="references unknown evidence ID"):
        ExecutiveSummaryOutput(
            summary_id="sum-1",
            title="Quarterly Review",
            executive_summary="Quarterly executive summary.",
            evidence=[ev_item],
            key_findings=[
                KeyFinding(
                    finding_id="kf-1",
                    text="Ungrounded claim with unknown evidence",
                    evidence_ids=["evi-unknown-nonexistent"],
                )
            ],
            implications=["Unknown"],
            recommended_actions=["Investigate"],
            confidence_statement="Low confidence.",
            claim_bindings=[],
        )

    with pytest.raises(ValidationError, match="must cite at least one evidence ID"):
        ExecutiveSummaryOutput(
            summary_id="sum-1",
            title="Quarterly Review",
            executive_summary="Quarterly executive summary.",
            evidence=[ev_item],
            key_findings=[
                KeyFinding(
                    finding_id="kf-1",
                    text="Operating profit grew by 4M",
                    evidence_ids=[ev_id],
                )
            ],
            implications=["Unknown"],
            recommended_actions=["Investigate"],
            confidence_statement="Low confidence.",
            claim_bindings=[
                ClaimBinding(
                    claim_id="cb-unbound",
                    text="Factual claim without evidence",
                    evidence_ids=[],
                    role="fact",
                )
            ],
        )

    mock_bad = output.model_copy(deep=True)
    object.__setattr__(mock_bad, "key_findings", [
        KeyFinding(finding_id="kf-bad", text="Broken", evidence_ids=["evi-nonexistent"])
    ])
    issues = _exec_summary_quality_issues(mock_bad)
    assert any("unknown evidence id" in i.lower() for i in issues)


def test_case_memory_release_gate() -> None:
    allowed, _ = can_release_to_case_memory(
        pipeline="advisory",
        output={"summary": "verified"},
        quality_approved=True,
        status="succeeded",
        artifact={"summary": "verified"},
        human_approval_required=False,
        human_approved=True,
    )
    assert allowed

    allowed_blocked_human, _ = can_release_to_case_memory(
        pipeline="advisory",
        output={"summary": "verified"},
        quality_approved=True,
        status="succeeded",
        artifact={"summary": "verified"},
        human_approval_required=True,
        human_approved=False,
    )
    assert not allowed_blocked_human

    allowed_blocked_status, _ = can_release_to_case_memory(
        pipeline="advisory",
        output={"summary": "verified"},
        quality_approved=True,
        status="partial",
        artifact={"summary": "verified"},
        human_approval_required=False,
        human_approved=True,
    )
    assert not allowed_blocked_status

    allowed_degraded, _ = can_release_to_case_memory(
        pipeline="infographic",
        output={"svg": "<svg></svg>"},
        quality_approved=True,
        status="succeeded",
        artifact={"degraded": True, "renderer_mode": "fallback"},
        is_degraded=True,
        operator_waiver_id=None,
    )
    assert not allowed_degraded


# =========================================================================
# 2. LinkedIn & Social Tests
# =========================================================================

def test_linkedin_claims_require_evidence_and_humanizer_gate() -> None:
    output = LinkedInPostOutput(
        post_id="post-1",
        title="Engineering Update",
        post_text="Our system reduced database query latency by 45% in production.",
        audience="Tech leads",
        call_to_action="Check the repo",
        source_references=["https://internal.telemetry/db-p99"],
        confidence_statement="Verified in telemetry.",
        claim_bindings=[
            LinkedInClaimBinding(
                claim_id="cl-1",
                claim="Our system reduced database query latency by 45% in production.",
                role="fact",
                evidence_ids=["evi-db-latency"],
            )
        ],
        humanizer_report=HumanizerReport(approved=True, score=0.88),
    )
    assert len(_linkedin_quality_issues(output)) == 0

    broken_output = LinkedInPostOutput(
        post_id="post-1",
        title="Engineering Update",
        post_text="Our system reduced database query latency by 45% in production.",
        audience="Tech leads",
        call_to_action="Check the repo",
        source_references=["https://internal.telemetry/db-p99"],
        confidence_statement="Unverified.",
        claim_bindings=[
            LinkedInClaimBinding(
                claim_id="cl-1",
                claim="Our system reduced database query latency by 45% in production.",
                role="fact",
                evidence_ids=[],
                source_references=[],
            )
        ],
        humanizer_report=HumanizerReport(approved=True, score=0.88),
    )
    broken_issues = _linkedin_quality_issues(broken_output)
    assert any("evidence" in i.lower() for i in broken_issues)


def test_humanizer_gate_blocks_ai_tells_and_enforces_score_threshold() -> None:
    cliche_text = (
        "As an AI language model, in today\u2019s rapidly changing world, it is important to note "
        "that cutting-edge technology is revolutionary. Furthermore, unlock the potential of our solutions."
    )
    report = audit_linkedin_text(cliche_text)
    assert report.score < 0.70
    assert not report.approved
    assert len(report.issues) > 0
    for iss in report.issues:
        assert iss.rule_id
        assert iss.category
        assert iss.location is not None or iss.evidence is not None

    crisp_text = (
        "We migrated our SQLite databases to WAL mode yesterday. "
        "Read p99 dropped from 120ms to 4ms under identical query workloads."
    )
    crisp_report = audit_linkedin_text(crisp_text)
    assert crisp_report.score >= 0.70
    assert crisp_report.approved


def test_social_pending_reconciliation_preserves_pending_state(tmp_path: Path) -> None:
    db_path = tmp_path / "social_approvals.db"
    store = SocialApprovalStore(str(db_path))
    post_count = 0

    class MockBoundary(SocialCapabilityBoundary):
        def __init__(self) -> None:
            super().__init__()

        def execute(self, request: SocialRequest, *, cancel_event: Any = None) -> SocialReceipt:
            nonlocal post_count
            post_count += 1
            return SocialReceipt(
                receipt_id="rcpt-1",
                provider="linkedin",
                operation="create_post",
                status="pending",
                target_ref="https://linkedin.com/feed",
                provider_request_id="prov-task-123",
            )

    service = SocialReleaseService(MockBoundary(), store)
    req = SocialRequest(
        provider="linkedin",
        operation="create_post",
        target_ref="https://linkedin.com/feed",
        payload={"text": "Verified status update"},
        idempotency_key="idemp-soc-1",
    )
    scope = {"user_id": "user-1", "case_id": "case-1"}

    record = service.submit_post(req, authorization_scope=scope, actor_id="user-1")
    service.approve(record.approval_id, actor_id="approver-1")

    receipt = service.release(record.approval_id, req, authorization_scope=scope, worker_id="worker-1")
    assert receipt.status == "pending"
    assert post_count == 1

    current = store.get(record.approval_id)
    assert current is not None
    assert current.status == "provider_pending"

    def check_still_pending(rec: SocialApprovalRecord) -> tuple[str, SocialReceipt | None]:
        assert rec.approval_id == record.approval_id
        return "pending", SocialReceipt(
            receipt_id="rcpt-recheck",
            provider="linkedin",
            operation="create_post",
            status="pending",
            target_ref=rec.target_ref,
            provider_request_id="prov-task-123",
        )

    updated = service.reconcile_provider_pending(
        record.approval_id, check_fn=check_still_pending, next_check_delay=60.0
    )
    assert updated.status == "provider_pending"
    assert post_count == 1

    def check_succeeded(rec: SocialApprovalRecord) -> tuple[str, SocialReceipt | None]:
        return "succeeded", SocialReceipt(
            receipt_id="rcpt-final",
            provider="linkedin",
            operation="create_post",
            status="succeeded",
            target_ref=rec.target_ref,
            provider_request_id="prov-task-123",
        )

    final = service.reconcile_provider_pending(record.approval_id, check_fn=check_succeeded)
    assert final.status == "succeeded"
    assert post_count == 1
    store.close()


# =========================================================================
# 3. Video Pipeline Tests
# =========================================================================

def test_video_provider_job_store_submit_unknown_lifecycle(tmp_path: Path) -> None:
    db_path = str(tmp_path / "video_jobs.db")
    store = VideoProviderJobStore(db_path)

    job = store.record_submit_start(
        run_id="run-vid-1", provider="openai-native", submit_fingerprint="fingerprint-abc"
    )
    assert job.status == "submitting"

    job_unknown = store.record_submit_unknown(
        "run-vid-1", error="HTTP connection timed out during submit"
    )
    assert job_unknown.status == "submit_unknown"

    retried_job = store.reconcile_job(
        "run-vid-1", lambda p, t: ("submitting", None, "Retry scheduled")
    )
    assert retried_job is not None
    assert retried_job.status == "submitting"

    store.record_submit_unknown("run-vid-1", error="Second timeout")
    reconciled_job = store.reconcile_job(
        "run-vid-1", lambda p, t: ("pending", {"task_id": "prov-task-999"}, None)
    )
    assert reconciled_job is not None
    assert reconciled_job.status == "pending"

    completed_job = store.record_terminal(
        "run-vid-1",
        status="succeeded",
        receipt={"video_url": "https://cdn.example/vid.mp4"},
    )
    assert completed_job.status == "succeeded"


def test_video_generator_partial_status_and_attempt_scoped_cache(tmp_path: Path) -> None:
    from pipelines.video.native_generator import NativeVideoGenerator, VideoScene
    from pipelines.video.contracts import VideoRunManifest

    generator = NativeVideoGenerator()

    def mock_generate_scene(  # type: ignore[override]
        scene: VideoScene,
        work_dir: Path,
        index: int,
        ffmpeg: str,
        subject: str,
        package_root: Path,
        cancel_event: Any = None,
        attempt_id: str = "1",
    ) -> str:
        if scene.scene_id == "scene-2":
            raise RuntimeError("Scene 2 media generation failed")
        out_dir = package_root / "attempts" / str(attempt_id) / "scenes"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"{scene.scene_id}.mp4"
        out_file.write_text("dummy-segment", encoding="utf-8")
        scene.video_path = str(out_file)
        return str(out_file)

    generator._generate_scene = mock_generate_scene  # type: ignore[method-assign]

    scenes = [
        VideoScene(scene_id="scene-1", narration="Scene 1 narrative", duration_seconds=3),
        VideoScene(scene_id="scene-2", narration="Scene 2 narrative", duration_seconds=3),
    ]
    manifest_path = tmp_path / "pkg1" / "video-manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = VideoRunManifest(run_id="run-1", subject="Attempt Test", renderer_version="native-video@2")

    seg_paths, failed_ids, _ = generator._render_scene_batch(
        scenes,
        manifest,
        manifest_path,
        tmp_path / "work1",
        ffmpeg="ffmpeg",
        subject="Attempt Test",
        package_root=tmp_path / "pkg1",
        cancel_event=None,
        authorization_scope=None,
        attempt_id="1",
    )
    assert "scene-2" in failed_ids
    cache_att1 = tmp_path / "pkg1" / "attempts" / "1" / "scenes" / "scene-1.mp4"
    assert cache_att1.exists()

    manifest2 = VideoRunManifest(run_id="run-2", subject="Attempt Test", renderer_version="native-video@2")
    manifest_path2 = tmp_path / "pkg1" / "video-manifest2.json"

    seg_paths2, failed_ids2, _ = generator._render_scene_batch(
        scenes[:1],
        manifest2,
        manifest_path2,
        tmp_path / "work2",
        ffmpeg="ffmpeg",
        subject="Attempt Test",
        package_root=tmp_path / "pkg1",
        cancel_event=None,
        authorization_scope=None,
        attempt_id="2",
    )
    cache_att2 = tmp_path / "pkg1" / "attempts" / "2" / "scenes" / "scene-1.mp4"
    assert cache_att2.exists()
    assert cache_att1 != cache_att2


# =========================================================================
# 4. Infographic SVG & Waiver Tests
# =========================================================================

def test_standalone_svg_accessibility_enforcement() -> None:
    accessible_svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 600" '
        'width="800" height="600" role="img" aria-labelledby="diagram-title diagram-desc">\n'
        '  <title id="diagram-title">System Architecture</title>\n'
        '  <desc id="diagram-desc">Detailed architecture showing microservices and message bus.</desc>\n'
        '  <rect width="100" height="100" fill="#2563eb" />\n'
        '</svg>'
    )
    rep = inspect_svg(accessible_svg, renderer_mode="native", strict_accessibility=True)
    assert rep.approved
    assert not any("accessibility" in i.lower() or "missing" in i.lower() for i in rep.issues)

    inaccessible_svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 600" width="800" height="600">\n'
        '  <rect width="100" height="100" fill="#2563eb" />\n'
        '</svg>'
    )
    rep_bad = inspect_svg(inaccessible_svg, renderer_mode="native", strict_accessibility=True)
    assert not rep_bad.approved
    assert any("missing" in i.lower() or "accessibility" in i.lower() for i in rep_bad.issues)


def test_operator_waiver_store_and_fallback_release_gating(tmp_path: Path) -> None:
    db_path = str(tmp_path / "waivers.db")
    store = OperatorWaiverStore(db_path)

    waiver = store.issue_waiver(
        run_id="run-info-1",
        operator_id="operator-alice",
        reason="Visual pipeline degraded; human reviewer approved fallback for executive meeting",
        valid_seconds=300.0,
    )
    assert waiver.waiver_id.startswith("waiver-")
    assert not waiver.used

    fallback_svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 600" '
        'width="800" height="600" role="img" aria-labelledby="diagram-title diagram-desc">\n'
        '  <title id="diagram-title">Fallback Chart</title>\n'
        '  <desc id="diagram-desc">Degraded text chart fallback</desc>\n'
        '  <rect width="100" height="100" fill="#2563eb" />\n'
        '</svg>'
    )

    rep_rejected = inspect_svg(fallback_svg, renderer_mode="fallback", operator_waiver_id=None)
    assert not rep_rejected.approved
    assert any("waiver" in i.lower() for i in rep_rejected.issues)

    rep_waived = inspect_svg(fallback_svg, renderer_mode="fallback", operator_waiver_id=waiver.waiver_id)
    assert rep_waived.approved

    consumed = store.verify_and_consume_waiver(waiver.waiver_id, run_id="run-info-1")
    assert consumed is True

    consumed_again = store.verify_and_consume_waiver(waiver.waiver_id, run_id="run-info-1")
    assert consumed_again is False
