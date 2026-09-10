from integrations.deepseek_harness.skill_catalog import (
    build_skill_manifests,
    canonical_skill_id,
    skill_summary,
)


def test_catalog_uses_canonical_ids_and_safe_summaries() -> None:
    manifests = build_skill_manifests()
    assert "presentation.case-brief" in manifests
    assert "visual.flowchart" in manifests
    assert canonical_skill_id("ppt") == "presentation.case-brief"

    summary = skill_summary(manifests["presentation.case-brief"], available=True)
    assert summary["skill_id"] == "presentation.case-brief"
    assert summary["available"] is True
    assert "prompt" not in summary
    assert "api_key" not in summary
    assert summary["output_artifact_types"]
