"""Skill package discovery and lazy resource loading.

The manifest is the compact discovery surface. ``SKILL.md`` and the other
resources are loaded only after a Harness or runtime selects a skill. This
keeps catalog prompts small and makes user-added skills follow one validated
folder contract.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipelines.orchestrator.contracts import RunPolicy, SkillManifest
from skills.security import verify_skill_package


REQUIRED_FILES = ("manifest.json", "SKILL.md", "schema.json", "policy.json", "failures.json")


@dataclass(frozen=True, slots=True)
class SkillPackage:
    path: Path
    manifest: SkillManifest

    def load_body(self) -> str:
        return (self.path / "SKILL.md").read_text(encoding="utf-8")

    def load_text(self, name: str, *, max_chars: int | None = None) -> str:
        """Load a declared text resource without allowing path traversal."""

        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("path traversal: skill resources must stay inside the package")
        target = (self.path / relative).resolve()
        package_root = self.path.resolve()
        if package_root not in target.parents and target != package_root:
            raise ValueError("skill resource escapes the package")
        text = target.read_text(encoding="utf-8")
        if max_chars is not None and max_chars < 1:
            raise ValueError("max_chars must be positive")
        return text if max_chars is None else text[:max_chars]

    def load_json(self, name: str) -> dict[str, Any]:
        if Path(name).name != name or not name.endswith(".json"):
            raise ValueError("skill resources must be a direct JSON file")
        value = json.loads((self.path / name).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"skill resource {name} must contain an object")
        return value


class SkillWorkspace:
    """Discover and validate all versioned skill folders below ``skills/``."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else Path(__file__).resolve().parent

    def discover(self) -> dict[str, SkillPackage]:
        packages: dict[str, SkillPackage] = {}
        if not self.root.exists():
            return packages
        for manifest_path in sorted(self.root.glob("*/manifest.json")):
            package = self._load_package(manifest_path.parent)
            if package.manifest.skill_id in packages:
                raise ValueError(f"duplicate skill id: {package.manifest.skill_id}")
            packages[package.manifest.skill_id] = package
        return packages

    def get(self, skill_id: str) -> SkillPackage | None:
        return self.discover().get(str(skill_id).strip().lower())

    def manifests(self) -> dict[str, SkillManifest]:
        return {skill_id: package.manifest for skill_id, package in self.discover().items()}

    def _load_package(self, path: Path) -> SkillPackage:
        missing = [name for name in REQUIRED_FILES if not (path / name).is_file()]
        if missing:
            raise ValueError(f"skill package {path.name} is missing: {', '.join(missing)}")
        raw = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"skill manifest {path.name} must contain an object")
        budget = raw.get("budget_policy", {})
        manifest = SkillManifest(
            skill_id=str(raw["skill_id"]),
            version=str(raw["version"]),
            purpose=str(raw["purpose"]),
            input_schema=str(raw.get("input_schema", "AdvisoryRequest")),
            output_artifact_types=list(raw.get("output_artifact_types", [])),
            required_capabilities=list(raw.get("required_capabilities", [])),
            allowed_tools=list(raw.get("allowed_tools", [])),
            model_policy=dict(raw.get("model_policy", {})),
            budget_policy=RunPolicy(**budget),
            quality_gates=list(raw.get("quality_gates", [])),
            risk_class=str(raw.get("risk_class", "RESTRICTED")),
            trust_tier=str(raw.get("trust_tier", "builtin")),
            side_effects=list(raw.get("side_effects", [])),
            coordination=dict(raw.get("coordination", {})),
            context_policy=dict(raw.get("context_policy", {})),
            references=dict(raw.get("references", {})),
            renderers=list(raw.get("renderers", [])),
            checkers=list(raw.get("checkers", [])),
        )
        if path.name != manifest.skill_id.replace(".", "-"):
            raise ValueError(f"skill directory must be named after {manifest.skill_id}")
        verify_skill_package(
            path,
            trust_tier=manifest.trust_tier,
            trusted_digests=os.getenv("SUDARSHAN_TRUSTED_SKILL_DIGESTS", "").split(","),
        )
        return SkillPackage(path=path, manifest=manifest)


__all__ = ["REQUIRED_FILES", "SkillPackage", "SkillWorkspace"]
