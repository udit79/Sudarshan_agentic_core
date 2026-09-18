import base64
from pathlib import Path
from types import SimpleNamespace

from pipelines import ExecutiveSummaryFlow, LinkedInPostFlow
from pipelines.advisory.schemas import EvidenceItem
from pipelines.executive_summary.schemas import ExecutiveSummaryOutput
from pipelines.linkedin.openai_images import OpenAIImageGenerator
from pipelines.linkedin.humanizer import audit_linkedin_text
from pipelines.linkedin.schemas import LinkedInImageSpec, LinkedInPostOutput
from pipelines.linkedin.visual_child import build_visual_child_call
from pipelines.common.contracts import AdvisoryRequest
from pipelines.ppt.crew import PresentationFlow
from pipelines.ppt.schemas import PresentationOutput, SlideContent


def test_automatic_text_flows_have_quality_and_delivery_routes() -> None:
    for flow_type, pipeline_name in (
        (LinkedInPostFlow, "linkedin_post"),
        (ExecutiveSummaryFlow, "executive_summary"),
    ):
        definition = flow_type.flow_definition()
        assert flow_type.pipeline_name == pipeline_name
        assert "persist_output" in definition.methods
        assert definition.methods["persist_output"].listen == "complete"
        assert not any(method.human_feedback for method in definition.methods.values())


def test_linkedin_schema_normalizes_hashtags_and_rejects_model_language() -> None:
    output = LinkedInPostOutput(
        post_id="post-1",
        title="Case update",
        post_text="A concise case-grounded update.",
        audience="Professional audience",
        call_to_action="Read the case update.",
        hashtags=["#NTRO", "case"],
        source_references=["case://1"],
        confidence_statement="Based on supplied information.",
    )
    assert output.hashtags == ["#NTRO", "#case"]
    assert output.approval_required == "publish"
    assert output.publish_status == "draft_only"
    assert output.humanizer_report.approved is True


def test_linkedin_humanizer_is_explainable_and_bounded() -> None:
    report = audit_linkedin_text(
        "In today's rapidly changing world, our revolutionary approach always delivers. "
        "As an AI, I cannot provide more details."
    )
    assert report.approved is False
    assert {issue.category for issue in report.issues} >= {"generic_phrase", "overclaim", "ai_tell"}
    assert report.revision_suggestions


def test_linkedin_visual_child_is_typed_and_never_publish_capable() -> None:
    output = LinkedInPostOutput(
        post_id="post-visual",
        title="Case update",
        post_text="A concise case-grounded update.",
        audience="Professional audience",
        call_to_action="Read the case update.",
        source_references=["case://1"],
        confidence_statement="Based on supplied information.",
        image=LinkedInImageSpec(
            requested=True,
            strategy="prompt",
            image_type="diagram",
            alt_text="Diagram of the case update",
            generation_prompt="Show only the verified case relationships.",
        ),
    )
    call = build_visual_child_call(output, parent_run_id="run-linkedin")
    assert call is not None
    assert call.skill_id == "visual.flowchart"
    assert call.parent_run_id == "run-linkedin"
    assert call.policy.max_parallel_children == 1
    assert output.publish_status == "draft_only"


def test_linkedin_quality_boundary_rejects_unbound_or_blocked_drafts() -> None:
    flow = LinkedInPostFlow(None)
    output = LinkedInPostOutput(
        post_id="post-review",
        title="Case update",
        post_text="A concise case-grounded update with a clear next step.",
        audience="Professional audience",
        call_to_action="Read the case update.",
        source_references=["case://1"],
        confidence_statement="Based on supplied information.",
    )
    prepared = flow.prepare_quality_output(output)
    issues = flow.quality_output_issues(prepared)
    assert prepared.humanizer_report.approved is True
    assert any("claim_bindings" in issue for issue in issues)


def test_executive_summary_forbids_unresolved_placeholders() -> None:
    try:
        ExecutiveSummaryOutput(
            summary_id="summary-1",
            title="TBD summary",
            executive_summary="Pending",
            key_findings=["Finding"],
            implications=["Implication"],
            recommended_actions=["Action"],
            evidence=[EvidenceItem(
                evidence_id="E-1",
                claim="Claim",
                source_reference="case://1",
                evidence_summary="Summary",
                confidence=0.7,
            )],
            confidence_statement="Moderate confidence.",
        )
    except ValueError:
        return
    raise AssertionError("unresolved placeholders must be rejected")


def test_presentation_normalizes_unvalidated_model_template_to_native_default() -> None:
    flow = PresentationFlow(None)
    output = PresentationOutput(
        presentation_id="live-template-fallback",
        title="Verified case briefing",
        template_id="model-invented-template",
        template_version="unknown",
        classification_level="RESTRICTED",
        distribution="Authorized",
        slides=[
            SlideContent(slide_id="s1", order=1, title="Verified observations", bullets=["Observed fact"], layout="content"),
            SlideContent(slide_id="s2", order=2, title="Unknowns", bullets=["Requires review"], layout="content"),
        ],
    )

    prepared = flow.prepare_quality_output(output)

    assert prepared.template_id == "native-default"
    assert prepared.template_version is None
    assert prepared.slides == output.slides


def test_linkedin_image_option_returns_prompt_or_optional_asset() -> None:
    draft = LinkedInPostOutput(
        post_id="post-1",
        title="Case update",
        post_text="A concise case-grounded update.",
        audience="Professional audience",
        call_to_action="Read the case update.",
        source_references=["case://1"],
        confidence_statement="Based on supplied information.",
        image=LinkedInImageSpec(
            requested=True,
            strategy="generate",
            image_type="infographic",
            alt_text="Infographic summarizing the case update",
            generation_prompt="A restrained professional infographic based only on the case facts.",
        ),
    )
    flow_without_generator = LinkedInPostFlow(None)
    prompt_result = flow_without_generator.enrich_output(draft)
    assert prompt_result.image.strategy == "prompt"
    assert prompt_result.image.generation_prompt

    flow_with_generator = LinkedInPostFlow(None, image_generator=lambda _: "asset://image-1")
    asset_result = flow_with_generator.enrich_output(draft)
    assert asset_result.image.strategy == "asset"
    assert asset_result.image.asset_uri == "asset://image-1"


def test_linkedin_image_quota_failure_is_explicitly_degraded() -> None:
    draft = LinkedInPostOutput(
        post_id="post-quota",
        title="Case update",
        post_text="A concise case-grounded update.",
        audience="Professional audience",
        call_to_action="Read the case update.",
        source_references=["case://1"],
        confidence_statement="Based on supplied information.",
        image=LinkedInImageSpec(
            requested=True,
            strategy="generate",
            image_type="illustration",
            alt_text="Illustration of the case update",
            generation_prompt="A restrained illustration based only on the case facts.",
        ),
    )

    def exhausted(_: str) -> str:
        raise RuntimeError("insufficient_quota: exceeded your current quota")

    result = LinkedInPostFlow(None, image_generator=exhausted).enrich_output(draft)
    assert result.image.strategy == "prompt"
    assert "quota_exhausted" in result.caveats[-1]


def test_linkedin_image_policy_defaults_to_internal_auto_decision() -> None:
    request = AdvisoryRequest(
        query="Create a case-grounded post",
        user_id="user-1",
        case_id="case-1",
        task_id="task-1",
    )
    flow = LinkedInPostFlow(None)
    assert flow.pipeline_options(request)["linkedin_image"]["policy"] == "auto"

    explicit_image = AdvisoryRequest(
        query="Create a LinkedIn post with an infographic image",
        user_id="user-1",
        case_id="case-1",
        task_id="task-1",
    )
    assert flow.pipeline_options(explicit_image)["linkedin_image"]["policy"] == "always"

    explicit_no_image = AdvisoryRequest(
        query="Create a LinkedIn post without an image",
        user_id="user-1",
        case_id="case-1",
        task_id="task-1",
    )
    assert flow.pipeline_options(explicit_no_image)["linkedin_image"]["policy"] == "never"

    disabled = AdvisoryRequest(
        query=request.query,
        user_id=request.user_id,
        case_id=request.case_id,
        task_id=request.task_id,
        metadata={"linkedin_image": {"requested": False}},
    )
    assert flow.pipeline_options(disabled)["linkedin_image"]["policy"] == "never"


def test_openai_image_adapter_writes_generated_base64_asset(tmp_path: Path) -> None:
    class FakeImages:
        def __init__(self) -> None:
            self.kwargs: dict[str, object] | None = None

        def generate(self, **kwargs: object) -> object:
            self.kwargs = kwargs
            return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(b"png-data").decode())])

    images = FakeImages()
    generator = OpenAIImageGenerator(client=SimpleNamespace(images=images), output_dir=tmp_path)
    asset_path = Path(generator("A calm visual showing the case's verified theme."))

    assert asset_path.exists()
    assert asset_path.read_bytes() == b"png-data"
    kwargs = images.kwargs
    assert kwargs is not None
    assert kwargs["model"] == "gpt-image-1"
    prompt = kwargs["prompt"]
    assert isinstance(prompt, str)
    assert "not be flashy" in prompt
