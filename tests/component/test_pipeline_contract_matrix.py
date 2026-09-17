"""Phase 5: real contract coverage for each registered pipeline route.

These tests stay at the deterministic contract boundary.  They do not call a
live model or provider, so failures are reproducible and no credentials or
case text are written to test output.
"""
from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from pipelines.advisory.schemas import (
    ActionItem,
    AdvisoryOutput,
    ClaimBinding,
    EvidenceItem,
    Recommendation,
)
from pipelines.common.contracts import AdvisoryRequest, PipelineResponse
from pipelines.executive_summary.schemas import ExecutiveSummaryOutput, KeyFinding
from pipelines.infographic.schemas import InfographicOutput
from pipelines.linkedin.schemas import LinkedInPostOutput
from pipelines.orchestrator.contracts import RequestConstraints
from pipelines.ppt.schemas import PresentationOutput, SlideContent
from pipelines.video.contracts import VideoPackage, VideoScene
from pipelines.video.planner import OpenAIVideoPlanner, VideoPlanningError
from pipelines.orchestrator.understanding import PromptCrafterAgent, RequestUnderstandingAgent


# ``ppt`` is a compatibility alias of ``presentation``.  It is included in
# the route matrix because it is still accepted by the public router.
ROUTES = (
    "advisory",
    "executive_summary",
    "linkedin_post",
    "presentation",
    "ppt",
    "infographic",
    "video",
    "visual_flowchart",
)


def make_request(route: str, **overrides: Any) -> AdvisoryRequest:
    values: dict[str, Any] = {
        "query": f"Create a verified {route} for the supplied case evidence.",
        "user_id": "user-contract",
        "case_id": "case-contract",
        "task_id": f"task-{route}",
        "requested_pipelines": (route,),
    }
    values.update(overrides)
    return AdvisoryRequest(**values)


def evidence(evidence_id: str = "evi-contract-1") -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        claim="The supplied case contains one verified observation.",
        source_reference="evidence://contract/source-1",
        evidence_summary="Sanitized contract fixture.",
        confidence=0.9,
    )


def valid_advisory() -> AdvisoryOutput:
    item = evidence()
    return AdvisoryOutput(
        advisory_id="advisory-contract-1",
        title="Verified case advisory",
        subject="Contract fixture",
        severity_rating="moderate",
        classification_level="RESTRICTED",
        distribution="Authorized NTRO personnel",
        executive_summary="The supplied case contains one verified observation.",
        overview="This is a sanitized contract fixture.",
        situation="The situation is limited to the supplied evidence.",
        assessment="The observation requires normal review.",
        impact_analysis="No impact beyond the supplied case is asserted.",
        observed_patterns=["One verified observation"],
        recommendations=[Recommendation(
            priority="P2",
            action="Review the observation",
            responsible_party="Case analyst",
            timeline="Within 7 days",
            rationale="The source is available for review.",
            evidence_ids=[item.evidence_id],
        )],
        action_items=[ActionItem(
            priority="P2",
            action="Record the review outcome",
            responsible_party="Case analyst",
            timeline="Within 7 days",
            completion_signal="Review recorded",
            evidence_ids=[item.evidence_id],
        )],
        evidence=[item],
        confidence_statement="Based only on the sanitized contract fixture.",
        claim_bindings=[ClaimBinding(
            claim_id="claim-contract-1",
            text="The supplied case contains one verified observation.",
            role="fact",
            evidence_ids=[item.evidence_id],
        )],
    )


def valid_executive_summary() -> ExecutiveSummaryOutput:
    item = evidence()
    return ExecutiveSummaryOutput(
        summary_id="summary-contract-1",
        title="Verified case summary",
        executive_summary="The supplied case contains one verified observation.",
        key_findings=[KeyFinding(
            finding_id="finding-contract-1",
            text="The supplied case contains one verified observation.",
            evidence_ids=[item.evidence_id],
        )],
        implications=["Normal analyst review is required."],
        recommended_actions=["Review the supplied source."],
        evidence=[item],
        confidence_statement="Based only on the sanitized contract fixture.",
    )


def valid_linkedin_post() -> LinkedInPostOutput:
    return LinkedInPostOutput(
        post_id="post-contract-1",
        title="Verified case update",
        post_text="A verified case observation is ready for human review.",
        audience="Professional audience",
        call_to_action="Review the case update.",
        source_references=["evidence://contract/source-1"],
        confidence_statement="Based only on the supplied source.",
    )


def valid_infographic() -> InfographicOutput:
    return InfographicOutput(
        infographic_id="infographic-contract-1",
        title="Verified case process",
        syntax="infographic list-grid-simple\n  data: [\"One verified observation\"]",
        alt_text="A list containing one verified case observation.",
        evidence=[evidence()],
        confidence_statement="Based only on the sanitized contract fixture.",
    )


def valid_presentation() -> PresentationOutput:
    return PresentationOutput(
        presentation_id="presentation-contract-1",
        title="Verified case briefing",
        classification_level="RESTRICTED",
        distribution="Authorized NTRO personnel",
        slides=[
            SlideContent(slide_id="slide-1", order=1, title="Situation", bullets=["One verified observation"]),
            SlideContent(slide_id="slide-2", order=2, title="Next step", bullets=["Review the supplied source"]),
        ],
    )


@pytest.mark.parametrize("route", ROUTES)
def test_each_public_route_accepts_the_shared_request_contract(route: str) -> None:
    request = make_request(route)

    assert request.requested_pipelines == (route,)
    assert request.user_id == "user-contract"
    assert request.case_id == "case-contract"
    assert request.task_id == f"task-{route}"


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("missing_field", ("query", "user_id", "case_id", "task_id"))
def test_each_public_route_rejects_missing_request_identity_or_query(
    route: str, missing_field: str
) -> None:
    with pytest.raises(ValueError, match=missing_field):
        make_request(route, **{missing_field: ""})


def test_presentation_constraints_accept_boundary_and_reject_invalid_values() -> None:
    assert RequestConstraints(slide_count=1).slide_count == 1
    assert RequestConstraints(slide_count=15).slide_count == 15

    with pytest.raises(ValidationError):
        RequestConstraints(slide_count=0)
    with pytest.raises(ValidationError, match="must match"):
        RequestConstraints(slide_count=2, page_count=3)


def test_pipeline_specific_optional_constraints_are_not_silently_reinterpreted() -> None:
    request = make_request(
        "presentation",
        constraints={
            "slide_count": 2,
            "page_count": 2,
            "theme_tokens": {"accent": "#38BDF8"},
        },
    )
    assert request.constraints["slide_count"] == 2
    assert request.constraints["page_count"] == 2
    assert request.constraints["theme_tokens"]["accent"] == "#38BDF8"


@pytest.mark.parametrize(
    ("pipeline", "builder", "missing_field"),
    [
        ("advisory", valid_advisory, "evidence"),
        ("executive_summary", valid_executive_summary, "evidence"),
        ("linkedin_post", valid_linkedin_post, "post_text"),
        ("infographic", valid_infographic, "syntax"),
        ("presentation", valid_presentation, "slides"),
        ("video", lambda: VideoPackage(subject="Contract fixture"), "subject"),
    ],
)
def test_each_transformation_contract_accepts_valid_output_and_rejects_malformed_output(
    pipeline: str, builder: Any, missing_field: str
) -> None:
    output = builder()
    assert output

    malformed = output.model_dump(mode="json")
    malformed.pop(missing_field, None)
    model = type(output)
    with pytest.raises(ValidationError):
        model.model_validate(malformed)


def test_advisory_rejects_unresolved_placeholders_and_unlinked_recommendations() -> None:
    payload = valid_advisory().model_dump(mode="json")
    payload["executive_summary"] = "TBD"
    with pytest.raises(ValidationError, match="placeholder"):
        AdvisoryOutput.model_validate(payload)

    payload = valid_advisory().model_dump(mode="json")
    payload["recommendations"][0]["evidence_ids"] = []
    with pytest.raises(ValidationError, match="must cite"):
        AdvisoryOutput.model_validate(payload)


def test_executive_summary_rejects_unlinked_factual_claims() -> None:
    payload = valid_executive_summary().model_dump(mode="json")
    payload["claim_bindings"] = [{
        "claim_id": "claim-unlinked",
        "text": "Unsupported factual claim",
        "role": "fact",
        "evidence_ids": [],
    }]
    with pytest.raises(ValidationError, match="must cite"):
        ExecutiveSummaryOutput.model_validate(payload)


def test_linkedin_contract_is_draft_only_and_rejects_model_language() -> None:
    payload = valid_linkedin_post().model_dump(mode="json")
    payload["publish_status"] = "approved_for_publish"
    with pytest.raises(ValidationError, match="cannot approve or publish"):
        LinkedInPostOutput.model_validate(payload)

    payload = valid_linkedin_post().model_dump(mode="json")
    payload["post_text"] = "As an AI language model, this is a case update."
    with pytest.raises(ValidationError, match="model self-reference"):
        LinkedInPostOutput.model_validate(payload)


def test_infographic_contract_requires_antv_syntax() -> None:
    payload = valid_infographic().model_dump(mode="json")
    payload["syntax"] = "plain text, not AntV syntax"
    with pytest.raises(ValidationError, match="AntV infographic directive"):
        InfographicOutput.model_validate(payload)


def test_presentation_contract_rejects_duplicate_slide_identity() -> None:
    payload = valid_presentation().model_dump(mode="json")
    payload["slides"][1]["slide_id"] = payload["slides"][0]["slide_id"]
    with pytest.raises(ValidationError, match="slide IDs"):
        PresentationOutput.model_validate(payload)


def test_video_contract_enforces_scene_duration_boundaries() -> None:
    assert VideoScene(scene_id="scene-1", duration_seconds=1).duration_seconds == 1
    assert VideoScene(scene_id="scene-2", duration_seconds=600).duration_seconds == 600
    with pytest.raises(ValidationError):
        VideoScene(scene_id="scene-3", duration_seconds=0)
    with pytest.raises(ValidationError):
        VideoScene(scene_id="scene-4", duration_seconds=601)


def test_video_planner_reports_missing_provider_credentials_clearly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    planner = OpenAIVideoPlanner(client=None)
    with pytest.raises(VideoPlanningError, match="OPENAI_API_KEY is required"):
        planner.plan(
            subject="Contract fixture",
            query="Create a case-grounded video",
            memory_context="",
        )


@pytest.mark.parametrize("route", ROUTES)
def test_empty_memory_is_explicitly_labelled_in_the_prompt_plan(route: str) -> None:
    request = make_request(route)
    understanding = RequestUnderstandingAgent().run(request)
    plan = PromptCrafterAgent().run(request, understanding, "")

    assert plan.memory_context == ""
    assert "No permitted memory was recalled" in plan.prompt_text


@pytest.mark.parametrize("route", ROUTES)
def test_declared_missing_information_requests_clarification_before_generation(route: str) -> None:
    request = AdvisoryRequest(
        query=f"Create a {route} for the case.",
        user_id="user-contract",
        case_id="case-contract",
        task_id=f"task-{route}",
        metadata={
            "pipeline": route,
            "missing_information": ["the case objective"],
        },
    )

    understanding = RequestUnderstandingAgent().run(request)

    assert understanding.clarification_required is True
    assert understanding.missing_information == ["the case objective"]
    assert understanding.clarification_questions == ["Please provide the case objective."]


@pytest.mark.parametrize("route", ROUTES)
def test_transport_response_must_be_explicit_for_success_and_failure(route: str) -> None:
    success = PipelineResponse(
        status="succeeded",
        pipeline=route,
        task_id=f"task-{route}",
        run_id=f"run-{route}",
        output={"validated": True},
    )
    assert success.status == "succeeded"

    failed = PipelineResponse(
        status="failed",
        pipeline=route,
        task_id=f"task-{route}",
        run_id=f"run-{route}",
        failure="sanitized provider failure",
        attempts=2,
    )
    assert failed.failure == "sanitized provider failure"
    assert failed.attempts == 2

    with pytest.raises(ValueError, match="require output"):
        PipelineResponse(
            status="succeeded",
            pipeline=route,
            task_id=f"task-{route}",
            run_id=f"run-{route}",
        )
    with pytest.raises(ValueError, match="require failure"):
        PipelineResponse(
            status="failed",
            pipeline=route,
            task_id=f"task-{route}",
            run_id=f"run-{route}",
        )
