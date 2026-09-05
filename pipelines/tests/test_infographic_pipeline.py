from pipelines.infographic.crew import InfographicFlow
from pipelines.infographic.schemas import InfographicOutput


def test_infographic_flow_has_render_and_case_delivery_routes() -> None:
    definition = InfographicFlow.flow_definition()

    assert InfographicFlow.pipeline_name == "infographic"
    assert definition.methods["persist_output"].listen == "complete"
    assert not any(method.human_feedback for method in definition.methods.values())


def test_infographic_output_requires_antv_directive() -> None:
    output = InfographicOutput(
        infographic_id="info-1",
        title="Case process",
        visual_type="process",
        syntax=(
            "infographic list-row-simple-horizontal-arrow\n"
            "data\n"
            "  lists\n"
            "    - label Step 1\n"
            "      desc Start"
        ),
        alt_text="A process showing the first case step.",
        evidence=[{
            "evidence_id": "E-1",
            "claim": "The case contains one documented step.",
            "source_reference": "case://1",
            "evidence_summary": "Supplied case information.",
            "confidence": 0.8,
        }],
        confidence_statement="Moderate confidence based on supplied information.",
    )

    assert output.syntax.startswith("infographic")
    assert output.render_status == "pending"
