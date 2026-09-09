from pipelines.infographic.crew import InfographicFlow
from pipelines.infographic.normalization import normalize_infographic_output
from pipelines.infographic.schemas import InfographicOutput
from pipelines.advisory.schemas import EvidenceItem


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
        evidence=[EvidenceItem(
            evidence_id="E-1",
            claim="The case contains one documented step.",
            source_reference="case://1",
            evidence_summary="Supplied case information.",
            confidence=0.8,
        )],
        confidence_statement="Moderate confidence based on supplied information.",
    )

    assert output.syntax.startswith("infographic")
    assert output.render_status == "pending"


def test_infographic_output_normalizes_renderer_unsafe_punctuation() -> None:
    output = InfographicOutput(
        infographic_id="info-2",
        title="Rainfall “readiness” brief",
        visual_type="list",
        syntax=(
            "infographic list-row-simple-horizontal-arrow\n"
            "data\n"
            "  lists\n"
            "    - label “Verified”\n"
            "      desc Coastal rainfall – 142 mm"
        ),
        alt_text="A ‘verified’ rainfall brief.",
        evidence=[EvidenceItem(
            evidence_id="E-2",
            claim="Recorded rainfall was 142 mm.",
            source_reference="case://2",
            evidence_summary="Supplied case information.",
            confidence=0.8,
        )],
        confidence_statement="Moderate confidence based on supplied information.",
    )

    assert "“" not in output.syntax
    assert "”" not in output.syntax
    assert "–" not in output.syntax


def test_infographic_normalization_preserves_caveat_provenance_and_style() -> None:
    output = InfographicOutput(
        infographic_id="info-3",
        title="Coastal Flood Readiness",
        visual_type="comparison",
        syntax=(
            "infographic {\n"
            "  palette: { primary: '#FF9933', accent: '#138808' }\n"
            "  text: 'Heavy rainfall affected three coastal districts.'\n"
            "  footer: 'Confidence: High for the five verified observations.'\n"
            "}"
        ),
        alt_text="Coastal flood readiness with confidence high.",
        evidence=[EvidenceItem(
            evidence_id="E1",
            claim="Heavy rainfall affected three coastal districts.",
            source_reference="case://synthetic",
            evidence_summary="Supplied synthetic observation.",
            confidence=0.8,
        )],
        references=["Verified observations"],
        confidence_statement="Confidence is high for the supplied observations.",
    )

    repaired = normalize_infographic_output(
        output,
        query="This is synthetic test data only and must not be treated as operational intelligence.",
    )

    assert repaired.title == "Coastal Rainfall Readiness"
    assert repaired.visual_type == "other"
    assert repaired.confidence_statement.startswith("Confidence is limited")
    assert "This is synthetic test data only" in repaired.caveats[0]
    assert repaired.syntax.startswith("infographic list-grid-simple")
    assert "[E1]" in repaired.syntax
    assert "#FF9933" not in repaired.syntax
    assert "#138808" not in repaired.syntax
