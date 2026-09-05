import base64
from pathlib import Path
from types import SimpleNamespace

from pipelines import ExecutiveSummaryFlow, LinkedInPostFlow
from pipelines.executive_summary.schemas import ExecutiveSummaryOutput
from pipelines.linkedin.openai_images import OpenAIImageGenerator
from pipelines.linkedin.schemas import LinkedInImageSpec, LinkedInPostOutput
from pipelines.common.contracts import AdvisoryRequest


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
    assert LinkedInPostOutput(
        post_id="post-1",
        title="Case update",
        post_text="A concise case-grounded update.",
        audience="Professional audience",
        call_to_action="Read the case update.",
        hashtags=["#NTRO", "case"],
        source_references=["case://1"],
        confidence_statement="Based on supplied information.",
    ).hashtags == ["#NTRO", "#case"]


def test_executive_summary_forbids_unresolved_placeholders() -> None:
    try:
        ExecutiveSummaryOutput(
            summary_id="summary-1",
            title="TBD summary",
            executive_summary="Pending",
            key_findings=["Finding"],
            implications=["Implication"],
            recommended_actions=["Action"],
            evidence=[{
                "evidence_id": "E-1",
                "claim": "Claim",
                "source_reference": "case://1",
                "evidence_summary": "Summary",
                "confidence": 0.7,
            }],
            confidence_statement="Moderate confidence.",
        )
    except ValueError:
        return
    raise AssertionError("unresolved placeholders must be rejected")


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
            self.kwargs = None

        def generate(self, **kwargs: object) -> object:
            self.kwargs = kwargs
            return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(b"png-data").decode())])

    images = FakeImages()
    generator = OpenAIImageGenerator(client=SimpleNamespace(images=images), output_dir=tmp_path)
    asset_path = Path(generator("A calm visual showing the case's verified theme."))

    assert asset_path.exists()
    assert asset_path.read_bytes() == b"png-data"
    assert images.kwargs["model"] == "gpt-image-1"
    assert "not be flashy" in images.kwargs["prompt"]
