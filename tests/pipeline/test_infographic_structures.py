from pipelines.infographic.schemas import InfographicBlock, InfographicIR
from pipelines.infographic.structures import compile_infographic_structure
from pipelines.infographic.templates import infographic_theme_manifest


def _ir(kind: str = "timeline") -> InfographicIR:
    return InfographicIR(
        infographic_id="structure-1",
        title="A bounded structure",
        visual_type=kind,
        alt_text="A bounded structure",
        blocks=[
            InfographicBlock(block_id="a", label="Start", description="First", evidence_ids=["E1"]),
            InfographicBlock(block_id="b", label="Finish", description="Second", evidence_ids=["E2"]),
        ],
    )


def test_structure_compilers_are_typed_and_deterministic() -> None:
    timeline = compile_infographic_structure(_ir())
    assert timeline.kind == "timeline"
    assert timeline.edges[0].relation == "ordered"
    hierarchy = compile_infographic_structure(_ir("hierarchy"))
    assert hierarchy.edges[0].relation == "contains"
    comparison = compile_infographic_structure(_ir("comparison"))
    assert comparison.edges[0].relation == "compares"


def test_theme_manifest_is_versioned_and_local() -> None:
    theme = infographic_theme_manifest()
    assert theme.version == "ntro-default@1"
    assert theme.tokens["accent"].startswith("#")
