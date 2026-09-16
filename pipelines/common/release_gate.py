"""Shared post-enrichment release gate for durable Case memory write-back.

This gate runs immediately before `memory_manager.remember(...)` across all
generation pipelines (Advisory, Executive Summary, LinkedIn, Video, Infographic,
and Diagram). It prevents degraded, unsupported, pending, or unapproved outputs
from polluting Case memory.
"""

from __future__ import annotations

from typing import Any, Mapping


def can_release_to_case_memory(
    *,
    pipeline: str,
    output: Any,
    quality_approved: bool,
    status: str,
    artifact: Any | None = None,
    is_degraded: bool = False,
    operator_waiver_id: str | None = None,
    human_approval_required: bool = False,
    human_approved: bool = False,
    memory_policy_allows_degraded: bool = False,
) -> tuple[bool, str]:
    """Single gate evaluating whether an execution result is eligible for Case memory.

    Returns (can_release: bool, reason: str).
    """

    # 1. Quality review must be approved
    if not quality_approved:
        return False, "Quality critic rejected the output"

    # 2. Output status must be releasable ('succeeded' only; never 'partial', 'failed', 'pending')
    if status != "succeeded":
        return False, f"Output status '{status}' is not releasable to Case memory"

    # 3. Output object must exist
    if output is None:
        return False, "Output payload is missing"

    # 4. If human approval is required, it must be explicitly granted
    if human_approval_required and not human_approved:
        return False, "Human approval is required but not granted"

    # 5. Inspect post-enrichment output and artifact metadata.
    artifact_degraded = False
    renderer_mode = None
    render_status = None
    quality_report = {}

    if isinstance(output, Mapping):
        render_status = output.get("render_status")
    elif hasattr(output, "render_status"):
        render_status = getattr(output, "render_status")
    elif hasattr(output, "model_dump"):
        render_status = output.model_dump(mode="json").get("render_status")

    if render_status in {"syntax_only", "failed"}:
        return False, f"Output render_status '{render_status}' is not eligible for Case memory"

    if isinstance(artifact, Mapping):
        artifact_degraded = bool(artifact.get("degraded", False))
        renderer_mode = artifact.get("renderer_mode")
        quality_report = artifact.get("quality_report") or {}
    elif hasattr(artifact, "model_dump"):
        dumped = artifact.model_dump(mode="json")
        artifact_degraded = bool(dumped.get("degraded", False))
        renderer_mode = dumped.get("renderer_mode")
        quality_report = dumped.get("quality_report") or {}

    # Renderer mode constraints: syntax_only or failed modes can never be released
    if renderer_mode in {"syntax_only", "failed", "unknown"}:
        return False, f"Artifact renderer_mode '{renderer_mode}' is not eligible for Case memory"

    if isinstance(quality_report, Mapping) and quality_report.get("approved") is False:
        return False, "Artifact post-render quality report rejected the artifact"

    # 6. Check degradation: overall is_degraded or artifact_degraded
    effective_degraded = is_degraded or artifact_degraded
    if effective_degraded:
        if not operator_waiver_id:
            return False, "Degraded output requires an authenticated operator waiver for release"
        if not memory_policy_allows_degraded:
            return False, "Case memory policy does not permit degraded output write-back even with waiver"

    return True, "Releasable to Case memory"
