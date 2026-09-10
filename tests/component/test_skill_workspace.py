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


def test_workspace_rejects_incomplete_or_mismatched_packages(tmp_path) -> None:
    bad = tmp_path / "bad-skill"
    bad.mkdir()
    (bad / "manifest.json").write_text(
        json.dumps({"skill_id": "bad.skill", "version": "1.0.0", "purpose": "bad"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing"):
        SkillWorkspace(tmp_path).discover()

