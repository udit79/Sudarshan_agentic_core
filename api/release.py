"""Deterministic release/rollback preflight checks.

The module does not run deployment commands. It produces an auditable stop/go
report that CI or an operator can combine with the actual test and backup
results from the target environment.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Mapping

from pydantic import BaseModel, ConfigDict, Field


class ReleaseCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_id: str = Field(min_length=1)
    passed: bool
    message: str = Field(min_length=1)


class ReleaseReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    release_id: str = Field(min_length=1)
    passed: bool
    checks: list[ReleaseCheck] = Field(default_factory=list)
    failed_checks: list[str] = Field(default_factory=list)


DEFAULT_RELEASE_FILES = (
    "docs/release-runbook.md",
    "docs/rollback-runbook.md",
    "docs/sudarshan-2.0-remaining-work-plan.md",
    ".env.example",
)


def run_release_checks(
    root: str | Path,
    *,
    release_id: str,
    test_results: Mapping[str, bool] | None = None,
    required_files: Iterable[str] = DEFAULT_RELEASE_FILES,
) -> ReleaseReport:
    """Check release evidence without mutating the repository or environment."""

    base = Path(root)
    checks: list[ReleaseCheck] = []
    for relative in required_files:
        path = base / relative
        checks.append(
            ReleaseCheck(
                check_id=f"file:{relative}",
                passed=path.is_file(),
                message=("present" if path.is_file() else "required release file is missing"),
            )
        )
    for name, passed in (test_results or {}).items():
        checks.append(
            ReleaseCheck(
                check_id=f"test:{name}",
                passed=bool(passed),
                message="reported passed" if passed else "reported failed",
            )
        )
    failed = [item.check_id for item in checks if not item.passed]
    return ReleaseReport(
        release_id=release_id,
        passed=not failed,
        checks=checks,
        failed_checks=failed,
    )


__all__ = ["ReleaseCheck", "ReleaseReport", "run_release_checks"]
