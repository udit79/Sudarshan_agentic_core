from skills.catalog import build_skill_manifests, canonical_skill_id, skill_pipeline


def test_core_skill_catalog_is_harness_neutral() -> None:
    manifests = build_skill_manifests()

    assert "presentation.case-brief" in manifests
    assert canonical_skill_id("ppt") == "presentation.case-brief"
    assert skill_pipeline("video.storyboard") == "video"
