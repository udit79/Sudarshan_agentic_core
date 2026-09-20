"""Typed contracts and boundary models for DeepSeek Harness MCP and A2A interfaces."""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class _SubscriptableModel(BaseModel):
    """Base model that supports dict-like subscripting for seamless backward compatibility."""

    def __getitem__(self, key: str) -> Any:
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)


class LineageContext(_SubscriptableModel):
    """Server-derived, tamper-proof execution lineage."""

    root_run_id: str
    parent_run_id: str | None = None
    parent_node_id: str | None = None
    lineage_depth: int = 0
    revision_sequence: int = 0
    causal_chain: list[str] = Field(default_factory=list)
    trace_id: str | None = None

    def model_safe(self) -> "LineageContext":
        """Return a copy with only the fields safe to expose to the model layer.

        The full causal_chain, lineage_depth, and revision_sequence are
        server-internal and must not be visible to the model, which could use
        them to infer authorization boundaries or replay attacks.
        Only run_id / parent reference fields are model-safe.
        """
        return LineageContext(
            root_run_id=self.root_run_id,
            parent_run_id=self.parent_run_id,
            parent_node_id=None,   # not needed by model
            lineage_depth=0,       # strip depth — model must not route based on it
            revision_sequence=0,   # strip — server-managed
            causal_chain=[],       # strip — exposes run graph topology
            trace_id=self.trace_id,
        )


class PreparationResponse(_SubscriptableModel):
    """Typed result of the persisted request-preparation phase."""

    status: Literal["prepared", "needs_clarification", "rejected"]
    preparation_id: str | None = None
    context_pack_id: str | None = None
    normalized_request: dict[str, Any] = Field(default_factory=dict)
    expires_at: str = ""
    memory_snapshot_id: str | None = None
    clarification_questions: list[str] = Field(default_factory=list)
    rejection_code: str | None = None
    rejection_reason: str | None = None


class StartRunResponse(_SubscriptableModel):
    """Actionable typed response for start_sudarshan_run."""

    status: str
    run_id: str
    task_id: str
    operation: str = "submit"
    reused: bool = False
    attempt_id: str | None = None
    next_actions: list[str] = Field(
        default_factory=lambda: ["get_sudarshan_status", "wait_sudarshan"]
    )
    dag_revision: int = 0
    lineage: LineageContext | None = None
    pipeline: str | None = None
    pipelines: list[str] = Field(default_factory=list)
    classification_level: str = "RESTRICTED"
    distribution: str = "Authorized NTRO personnel"
    artifact_id: str | None = None


class StatusResponse(_SubscriptableModel):
    """Frontend-safe, typed projection of run status."""

    status: str
    run_id: str
    task_id: str = ""
    operation: str = "status"
    stage: str = "queued"
    event_cursor: int = 0
    wait_reason: str | None = None
    artifact_id: str | None = None
    artifact_manifests: list[dict[str, Any]] = Field(default_factory=list)
    quality_report: dict[str, Any] | None = None
    dag_revision: int = 0
    next_actions: list[str] = Field(default_factory=list)
    progress_percentage: float = 0.0
    lineage: LineageContext | None = None


class ArtifactResponse(_SubscriptableModel):
    """Verified, integrity-checked artifact manifest."""

    artifact_id: str
    operation: str = "get_artifact"
    uri: str = ""
    mime_type: str = ""
    sha256: str = ""
    classification_level: str = "RESTRICTED"
    created_at: str = ""
    provenance: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    manifest: dict[str, Any] = Field(default_factory=dict)
    download_uri: str = ""
    integrity_verified: bool = True
    run_id: str | None = None
    task_id: str | None = None
    status: str | None = None


class WaitResponse(_SubscriptableModel):
    """Actionable typed response for bounded wait operation."""

    status: str
    run_id: str
    task_id: str = ""
    operation: str = "wait"
    timed_out: bool = False
    events: list[dict[str, Any]] = Field(default_factory=list)
    wait_reason: str | None = None
    artifact_id: str | None = None
    artifact_manifests: list[dict[str, Any]] = Field(default_factory=list)
    event_cursor: int = 0


class SkillInvokeResponse(_SubscriptableModel):
    """Typed response for local/direct skill invocation."""

    status: str
    run_id: str
    task_id: str
    skill_id: str
    skill_version: str = "1.0"
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    quality_status: str = "passed"
    lineage: LineageContext | None = None
    result: dict[str, Any] = Field(default_factory=dict)


class DAGResponse(_SubscriptableModel):
    """Public DAG projection for run execution."""

    status: str = "ready"
    run_id: str
    revision: int = 0
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    lanes: list[dict[str, Any]] = Field(default_factory=list)
    updated_at: str = ""


class ObservabilityResponse(_SubscriptableModel):
    """Operator-only safe trace projection, without prompts or raw memory."""

    status: str = "ready"
    run_id: str
    events: list[dict[str, Any]] = Field(default_factory=list)
    event_count: int = 0


class TrajectoryResponse(_SubscriptableModel):
    """Safe Harness timeline projection of recorded Sudarshan lifecycle events."""

    status: str = "ready"
    run_id: str
    events: list[dict[str, Any]] = Field(default_factory=list)
    event_count: int = 0
    lanes: list[dict[str, Any]] = Field(default_factory=list)
