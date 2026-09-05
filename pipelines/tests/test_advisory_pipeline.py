from pipelines.advisory.artifact import render_advisory
from pipelines.advisory.crew import AdvisoryFlow
from pipelines.advisory.schemas import ActionItem, AdvisoryOutput, EvidenceItem, Recommendation
from pipelines.common.contracts import AdvisoryRequest


def sample_advisory() -> AdvisoryOutput:
    return AdvisoryOutput(
        advisory_id="advisory-test-1",
        title="Case Advisory: Reported Situation",
        subject="Reported situation",
        severity_rating="moderate",
        classification_level="RESTRICTED",
        distribution="Authorized NTRO personnel",
        executive_summary="The available information supports a focused review.",
        overview="The case concerns information provided by the reporting person.",
        situation="The current situation is documented in the supplied case material.",
        assessment="The assessment is bounded by the available evidence.",
        impact_analysis="Potential impact requires validation against additional information.",
        observed_patterns=["A recurring pattern is present in the supplied material."],
        recommendations=[Recommendation(
            priority="P2",
            action="Validate the reported information with the responsible team.",
            responsible_party="Case owner",
            timeline="Within the current review cycle",
            rationale="Validation reduces uncertainty before further action.",
            evidence_ids=["E-1"],
        )],
        action_items=[ActionItem(
            priority="P2",
            action="Record the validation result in the case file.",
            responsible_party="Case owner",
            timeline="After validation",
            completion_signal="Validation result recorded",
        )],
        evidence=[EvidenceItem(
            evidence_id="E-1",
            claim="The situation was reported by the person in the case.",
            source_reference="case://test/report",
            evidence_summary="Source statement supplied with the case.",
            confidence=0.8,
        )],
        references=["case://test/report"],
        handling_instructions=["Distribute only to authorized recipients."],
        confidence_statement="Moderate confidence based on the supplied case material.",
        intelligence_gaps=["Independent corroboration is pending."],
        caveats=["This is a case-specific analytical artifact."],
    )


def test_advisory_request_requires_a_task_boundary() -> None:
    request = AdvisoryRequest(
        query="Review the supplied case information",
        user_id="user-1",
        case_id="case-1",
        task_id="task-1",
    )
    assert request.access_context.task_id == "task-1"


def test_human_approval_routes_are_registered() -> None:
    definition = AdvisoryFlow.flow_definition()
    approval = definition.methods["request_human_approval"]

    human_feedback = approval.human_feedback
    assert human_feedback is not None
    emit = human_feedback.emit
    assert emit is not None
    assert list(emit) == ["approved", "rejected", "needs_revision"]
    assert definition.methods["persist_case_output"].listen == "approved"


def test_renderer_is_formal_and_contains_provenance() -> None:
    content = render_advisory(sample_advisory(), approved_by="reviewer-1")

    assert "**NTRO CASE ADVISORY**" in content
    assert "## Evidence and Provenance" in content
    assert "## Recommended Actions" in content
    assert "**Human approval:** APPROVED by reviewer-1" in content
    assert "CrewAI" not in content
    assert "agent" not in content.lower()
