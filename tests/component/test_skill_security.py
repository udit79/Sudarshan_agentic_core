from __future__ import annotations

import json

import pytest

from skills.security import (
    SandboxError,
    SandboxPolicy,
    SandboxRunner,
    SkillIntegrityError,
    sign_skill_package,
    verify_skill_package,
)


def test_signed_skill_package_rejects_tampering(tmp_path):
    package = tmp_path / "skill"
    package.mkdir()
    (package / "manifest.json").write_text("{}", encoding="utf-8")
    (package / "SKILL.md").write_text("safe", encoding="utf-8")
    signature = sign_skill_package(package, "test-key")
    assert verify_skill_package(package, trust_tier="verified", signing_key="test-key") == signature["digest"]
    (package / "SKILL.md").write_text("tampered", encoding="utf-8")
    with pytest.raises(SkillIntegrityError):
        verify_skill_package(package, trust_tier="verified", signing_key="test-key")


def test_unsigned_non_builtin_skill_is_rejected(tmp_path):
    package = tmp_path / "skill"
    package.mkdir()
    (package / "manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SkillIntegrityError, match="requires signature"):
        verify_skill_package(package, trust_tier="untrusted")


def test_local_sandbox_is_explicitly_disabled_by_default():
    with pytest.raises(SandboxError):
        SandboxRunner(SandboxPolicy(timeout_seconds=1)).run(["python", "-c", "print('no')"])
