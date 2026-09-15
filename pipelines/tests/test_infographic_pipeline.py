from pipelines.infographic.crew import InfographicFlow
from pipelines.infographic.normalization import normalize_infographic_output
from pipelines.infographic.schemas import InfographicOutput
from pipelines.advisory.schemas import EvidenceItem, QualityReview
from pipelines.infographic.normalization import is_renderer_ready, repairable_quality_review


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
    assert repaired.visual_type == "comparison"
    assert repaired.confidence_statement.startswith("Confidence is limited")
    assert "This is synthetic test data only" in repaired.caveats[0]
    assert repaired.syntax.startswith("infographic compare-hierarchy-row-letter-card-compact-card")
    assert "  title Coastal Rainfall Readiness" in repaired.syntax
    assert "label Brief" not in repaired.syntax
    assert "[E1]" in repaired.syntax
    assert "#FF9933" not in repaired.syntax
    assert "#138808" not in repaired.syntax


def test_infographic_normalization_keeps_situation_specific_layouts() -> None:
    expected = {
        "list": "infographic sudarshan-readable-list",
        "process": "infographic sequence-steps-simple",
        "timeline": "infographic sequence-timeline-simple",
        "comparison": "infographic compare-hierarchy-row-letter-card-compact-card",
        "hierarchy": "infographic hierarchy-tree-tech-style-compact-card",
        "flow": "infographic sequence-steps-simple",
    }
    evidence = [EvidenceItem(
        evidence_id=f"E{i}",
        claim=f"Observation {i} is verified.",
        source_reference="case://test",
        evidence_summary=f"Summary {i}.",
        confidence=0.8,
    ) for i in range(1, 3)]
    for visual_type, template in expected.items():
        output = InfographicOutput(
            infographic_id="layout-test",
            title="Situation brief",
            visual_type=visual_type,
            syntax="infographic { bad: value }",
            alt_text="Situation brief",
            evidence=evidence,
            confidence_statement="Moderate confidence.",
        )
        assert normalize_infographic_output(output).syntax.startswith(template)


def test_infographic_normalization_repairs_list_grid_drafts_with_long_labels() -> None:
    output = InfographicOutput(
        infographic_id="list-grid-test",
        title="Coastal Readiness Status Summary",
        visual_type="list",
        syntax=(
            "infographic list-grid-compact-card\n"
            "data\n"
            "  title Coastal Readiness Status Summary\n"
            "  lists\n"
            "    - label [E1] Source: Coastal Flood...\n"
            "      desc Source: Coastal Flood Response..."
        ),
        alt_text="Coastal readiness status summary.",
        evidence=[EvidenceItem(
            evidence_id="E1",
            claim=(
                "Source: Coastal Flood Response Readiness Brief, dated 15 August 2026. "
                "This is synthetic test data only and must not be treated as operational intelligence."
            ),
            source_reference="case://synthetic",
            evidence_summary="Synthetic source brief provided in user request.",
            confidence=0.8,
        )],
        confidence_statement="Moderate confidence.",
    )

    repaired = normalize_infographic_output(output)

    assert repaired.syntax.startswith("infographic sudarshan-readable-list")
    assert "  title Coastal Readiness Status Summary" in repaired.syntax
    assert "  colorPrimary #1E3A8A" in repaired.syntax
    assert "label [E1] Verified observation" in repaired.syntax
    assert "desc Source: Coastal Flood Response Readiness Brief, dated 15 August 2026." in repaired.syntax
    assert "..." not in repaired.syntax
    assert "..." not in repaired.alt_text
    assert "Full limitations remain" not in repaired.alt_text
    assert "Source: case://synthetic." in repaired.alt_text
    assert len(repaired.syntax.split("label [E1] ", 1)[1].split("\n", 1)[0]) < 80


def test_infographic_normalization_uses_a_flow_layout_for_larger_flow_sets() -> None:
    evidence = [EvidenceItem(
        evidence_id=f"E{i}",
        claim=f"Observation {i} is verified and operationally relevant.",
        source_reference="case://test",
        evidence_summary=f"Summary {i}.",
        confidence=0.8,
    ) for i in range(1, 8)]
    output = InfographicOutput(
        infographic_id="flow-layout-test",
        title="Situation flow",
        visual_type="flow",
        syntax="infographic list-grid-compact-card",
        alt_text="A four-panel situation flow with separate metadata and caveat panels.",
        evidence=evidence,
        confidence_statement="Moderate confidence.",
    )

    repaired = normalize_infographic_output(output)

    assert repaired.visual_type == "flow"
    assert repaired.syntax.startswith("infographic sequence-snake-steps-simple")
    assert "four-panel" not in repaired.alt_text


def test_infographic_normalization_downgrades_mixed_flow_content_to_a_list() -> None:
    claims = [
        ("E1", "Heavy rainfall affected three coastal districts."),
        ("E2", "Recorded rainfall was 142 mm during the previous 24 hours."),
        ("E3", "Three transport corridors have restricted movement."),
        ("E4", "Two temporary shelters are operating near the eastern transit zone."),
        ("E5", "Emergency supplies are expected to cover 72 hours."),
        ("E6", "Recommended analytical focus: shelter capacity; route status; supply coverage."),
        ("E7", "Information gaps: district-level impact; shelter occupancy; resupply timing."),
    ]
    output = InfographicOutput(
        infographic_id="mixed-flow-test",
        title="Coastal Readiness Situation Summary",
        visual_type="flow",
        syntax=(
            "infographic sequence-snake-steps-simple\n"
            "data\n"
            "  title Coastal Readiness Situation Summary\n"
            "  sequences\n"
            "    - label [E1] Heavy rainfall...\n"
            "      desc Heavy rainfall affected three..."
        ),
        alt_text="A flow infographic with truncated panels.",
        evidence=[EvidenceItem(
            evidence_id=evidence_id,
            claim=claim,
            source_reference="Source: Coastal Flood Response Readiness Brief.",
            evidence_summary=claim,
            confidence=1,
        ) for evidence_id, claim in claims],
        confidence_statement="Confidence is limited.",
        caveats=["This is synthetic test data only and must not be treated as operational intelligence."],
    )

    repaired = normalize_infographic_output(output)

    assert repaired.visual_type == "list"
    assert repaired.syntax.startswith("infographic sudarshan-readable-list")
    assert "..." not in repaired.syntax
    assert "..." not in repaired.alt_text
    assert "Heavy rainfall affected three coastal districts." in repaired.syntax


def test_infographic_quality_repair_accepts_only_complete_canonical_output() -> None:
    output = InfographicOutput(
        infographic_id="quality-repair-test",
        title="Situation summary",
        visual_type="list",
        syntax=(
            "infographic sudarshan-readable-list\n"
            "data\n"
            "  title Situation summary\n"
            "  lists\n"
            "    - label [E1] Verified observation\n"
            "      desc Heavy rainfall affected three coastal districts.\n"
            "    - label Source\n"
            "      desc Coastal Flood Response Readiness Brief."
        ),
        alt_text="A list infographic titled Situation summary. Source: Coastal Flood Response Readiness Brief.",
        evidence=[EvidenceItem(
            evidence_id="E1",
            claim="Heavy rainfall affected three coastal districts.",
            source_reference="Coastal Flood Response Readiness Brief.",
            evidence_summary="Heavy rainfall affected three coastal districts.",
            confidence=1,
        )],
        confidence_statement="Confidence is limited.",
    )
    mechanical_rejection = QualityReview(
        approved=False,
        issues=["The labels were abbreviated and the visual type should be a list."],
        required_revisions=["Remove the truncation and align the structure."],
    )
    unsupported = QualityReview(approved=False, issues=["The output contains an unsupported claim."])

    assert is_renderer_ready(output)
    assert repairable_quality_review(output, mechanical_rejection).approved
    assert not repairable_quality_review(output, unsupported).approved
