from __future__ import annotations

import json

import pytest

from skills.workspace import SkillWorkspace


def test_workspace_discovers_validated_versioned_packages_and_loads_body_on_demand() -> None:
    workspace = SkillWorkspace()
    packages = workspace.discover()

    assert {
        "presentation.case-brief",
        "visual.flowchart",
        "video.storyboard",
        "infographic",
        "linkedin.post",
    }.issubset(packages)
    assert "flowchart" in packages["visual.flowchart"].load_body().lower()
    assert packages["presentation.case-brief"].load_json("schema.json")["child_calls"] == ["visual.flowchart"]
    visual = packages["visual.flowchart"]
    assert visual.manifest.context_policy["default_level"] == "L1"
    assert visual.manifest.renderers == ["diagram.native-svg", "diagram.pptx"]
    assert "Visual flowchart" in visual.load_text("SKILL.md", max_chars=200)
    with pytest.raises(ValueError, match="path traversal|escapes"):
        visual.load_text("../README.md")


def test_workspace_rejects_incomplete_or_mismatched_packages(tmp_path) -> None:
    bad = tmp_path / "bad-skill"
    bad.mkdir()
    (bad / "manifest.json").write_text(
        json.dumps({"skill_id": "bad.skill", "version": "1.0.0", "purpose": "bad"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing"):
        SkillWorkspace(tmp_path).discover()
