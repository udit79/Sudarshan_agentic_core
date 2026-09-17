"""Strict contracts for durable runs, skills, artifacts, and quality gates.

These models are deliberately transport-neutral. They do not import LangGraph,
CrewAI, the Harness SDK, or Cognee so that HTTP, MCP, workers, and tests can
share the same boundary without creating a second orchestrator.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pipelines.common.correlation import HarnessCorrelation

RunStatus = Literal[
    "accepted",
    "queued",
    "planning",
    "running",
    "waiting_on_dependency",
    "waiting_on_child_skill",
    "waiting_for_input",
    "waiting_for_approval",
    "retrying",
    "validating",
    "rendering",
    "quality_check",
    "repairing",
    "pending",
    "succeeded",
    "partial",
    "failed",
    "cancelled",
    "completed",
]

QualityStatus = Literal["pending", "passed", "failed", "repairable", "blocked"]
SideEffectClass = Literal["none", "write_artifact", "external_write", "publish"]
UsageChargeType = Literal["provider", "retry", "cache_hit", "cache_write", "orchestration"]
UsageBillingStatus = Literal["unreconciled", "matched", "adjusted", "missing"]


def _non_empty(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TelemetryUsage(ContractModel):
    """Safe provider-usage projection; prompts and model output are excluded."""

    provider: str | None = None
    model: str | None = None
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    latency_ms: int = Field(default=0, ge=0)
    estimated_cost: float = Field(default=0.0, ge=0)
    is_estimate: bool = False

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.reasoning_tokens


class TelemetrySummary(ContractModel):
    """Dashboard-safe aggregate for one run."""

    event_count: int = Field(default=0, ge=0)
    child_count: int = Field(default=0, ge=0)
    artifact_count: int = Field(default=0, ge=0)
    cache_hits: int = Field(default=0, ge=0)
    cache_misses: int = Field(default=0, ge=0)
    cache_waits: int = Field(default=0, ge=0)
    wait_count: int = Field(default=0, ge=0)
    quality_report_count: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    latency_ms: int = Field(default=0, ge=0)
    estimated_cost: float = Field(default=0.0, ge=0)
    usage_is_estimate: bool = False
    last_stage: str = ""
    last_status: str = ""

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.reasoning_tokens


class RunSummary(ContractModel):
    """Safe current projection for APIs, MCP, and the frontend."""

    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    skill_id: str = Field(min_length=1)
    skill_version: str = Field(min_length=1)
    execution_version: str = Field(min_length=1)
    status: RunStatus
    stage: str = Field(min_length=1)
    progress: int = Field(default=0, ge=0, le=100)
    requires_action: bool = False
    quality_status: QualityStatus = "pending"
    artifact_count: int = Field(default=0, ge=0)
    child_count: int = Field(default=0, ge=0)
    error_code: str | None = None
    telemetry: TelemetrySummary = Field(default_factory=TelemetrySummary)
    harness_correlation: HarnessCorrelation | None = None
    created_at: str = Field(default_factory=_utc_now)
    updated_at: str = Field(default_factory=_utc_now)


class RunEvent(ContractModel):
    """Replayable event projection; never contains prompts or raw memory."""

    event_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    stage: str = Field(min_length=1)
    status: RunStatus
    progress: int = Field(default=0, ge=0, le=100)
    message: str = Field(default="", max_length=2000)
    child_id: str | None = None
    skill_call_id: str | None = None
    artifact_id: str | None = None
    error_code: str | None = None
    requires_action: bool = False
    wait_reason: str = Field(default="", max_length=500)
    quality_status: QualityStatus = "pending"
    quality_report_id: str | None = None
    child_count: int = Field(default=0, ge=0)
    provider: str | None = None
    model: str | None = None
    usage: TelemetryUsage | None = None
    cache_status: Literal["hit", "miss", "wait", "write", "not_applicable"] | None = None
    source_sequence: int | None = None
    node_id: str | None = None
    parent_node_id: str | None = None
    attempt_id: str | None = None
    lane_id: str | None = None
    fallback: bool = False
    provider_request_id: str | None = None
    usage_id: str | None = None
    timestamp: str = Field(default_factory=_utc_now)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ArtifactManifest(ContractModel):
    """Immutable, classified description of a generated artifact."""

    artifact_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    # Ownership is part of the artifact contract, not inferred from a path or
    # from classification alone.  Optional values preserve read compatibility
    # with manifests created before NP-14; new application registrations must
    # provide them.
    user_id: str | None = None
    case_id: str | None = None
    task_id: str | None = None
    kind: str = Field(min_length=1)
    name: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    preview_uri: str | None = None
    sha256: str = Field(min_length=64, max_length=64)
    size_bytes: int = Field(ge=0)
    classification_level: str = Field(min_length=1)
    quality_status: QualityStatus = "pending"
    quality_report_id: str | None = None
    quality_issues: list[str] = Field(default_factory=list)
    degraded: bool = False
    fallback_renderer: str | None = None
    source_ir_hash: str | None = None
    renderer_version: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    parent_artifact_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=_utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_ownership_tuple(self) -> "ArtifactManifest":
        ownership = (self.user_id, self.case_id, self.task_id)
        if any(value is not None for value in ownership) and not all(ownership):
            raise ValueError("artifact ownership must include user_id, case_id, and task_id together")
        return self

    @field_validator("sha256", "source_ir_hash")
    @classmethod
    def validate_hash(cls, value: str | None) -> str | None:
        if value is not None and not _SHA256_RE.fullmatch(value):
            raise ValueError("hash fields must contain a lowercase SHA-256 digest")
        return value


class QualityReport(ContractModel):
    """Combined deterministic and model-assisted release assessment."""

    quality_report_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    artifact_id: str | None = None
    status: QualityStatus
    score: float | None = Field(default=None, ge=0, le=1)
    issues: list[str] = Field(default_factory=list)
    required_revisions: list[str] = Field(default_factory=list)
    validator_ids: list[str] = Field(default_factory=list)
    evidence_checks: dict[str, Any] = Field(default_factory=dict)
    visual_checks: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_utc_now)


class UsageRecord(ContractModel):
    """Provider-normalized usage for one model/tool execution boundary."""

    usage_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    attempt_id: str | None = None
    node_id: str | None = None
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    cache_read_tokens: int = Field(default=0, ge=0)
    cache_write_tokens: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    latency_ms: int = Field(default=0, ge=0)
    estimated_cost: float | None = Field(default=None, ge=0)
    is_estimate: bool = False
    charge_type: UsageChargeType = "provider"
    parent_usage_id: str | None = None
    provider_request_id: str | None = None
    media_units: float | None = Field(default=None, ge=0)
    finish_reason: str | None = None
    retry_after_seconds: float | None = Field(default=None, ge=0)
    provider_fields: dict[str, Any] = Field(default_factory=dict)
    billing_status: UsageBillingStatus = "unreconciled"
    recorded_at: str = Field(default_factory=_utc_now)


class RunPolicy(ContractModel):
    max_wall_time_ms: int = Field(default=300_000, ge=1)
    max_model_tokens: int = Field(default=6_000, ge=256)
    max_tool_calls: int = Field(default=32, ge=0)
    max_parallel_children: int = Field(default=4, ge=1)
    max_cost: float | None = Field(default=None, ge=0)
    approval_required_for: list[SideEffectClass] = Field(default_factory=list)


class SkillManifest(ContractModel):
    skill_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    input_schema: str = Field(min_length=1)
    output_artifact_types: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    model_policy: dict[str, Any] = Field(default_factory=dict)
    budget_policy: RunPolicy = Field(default_factory=RunPolicy)
    quality_gates: list[str] = Field(default_factory=list)
    risk_class: str = Field(min_length=1)
    trust_tier: Literal["builtin", "verified", "untrusted"] = "builtin"
    side_effects: list[SideEffectClass] = Field(default_factory=list)
    coordination: dict[str, Any] = Field(default_factory=dict)
    context_policy: dict[str, Any] = Field(default_factory=dict)
    references: dict[str, Any] = Field(default_factory=dict)
    renderers: list[str] = Field(default_factory=list)
    checkers: list[str] = Field(default_factory=list)


class SkillCall(ContractModel):
    skill_call_id: str = Field(min_length=1)
    parent_run_id: str = Field(min_length=1)
    parent_node_id: str = Field(min_length=1)
    skill_id: str = Field(min_length=1)
    skill_version: str = Field(min_length=1)
    input_artifact_ids: list[str] = Field(default_factory=list)
    input_payload: dict[str, Any] = Field(default_factory=dict)
    policy: RunPolicy = Field(default_factory=RunPolicy)
    depth: int = Field(default=0, ge=0)
    max_depth: int = Field(default=3, ge=0)

    @model_validator(mode="after")
    def validate_depth(self) -> "SkillCall":
        if self.depth > self.max_depth:
            raise ValueError("skill call depth exceeds max_depth")
        return self


class SkillResult(ContractModel):
    skill_call_id: str = Field(min_length=1)
    child_run_id: str = Field(min_length=1)
    status: Literal["succeeded", "failed", "waiting", "cancelled", "blocked", "partial"]
    artifact_ids: list[str] = Field(default_factory=list)
    quality_report_id: str | None = None
    usage_ids: list[str] = Field(default_factory=list)
    failure_code: str | None = None
    failure_message: str | None = None
    child_plan: list[dict[str, Any]] = Field(default_factory=list)
    child_outcomes: list[dict[str, Any]] = Field(default_factory=list)


class ChildTaskSpec(ContractModel):
    """Typed child request emitted by a parent planner.

    The spec is the portable hand-off between native skills, CrewAI adapters,
    MCP workers, and A2A specialists. It intentionally contains references,
    not a nested prompt transcript.
    """

    child_id: str = Field(min_length=1)
    parent_run_id: str = Field(min_length=1)
    parent_node_id: str = Field(min_length=1)
    skill_id: str = Field(min_length=1)
    input_evidence_ids: list[str] = Field(default_factory=list)
    input_payload: dict[str, Any] = Field(default_factory=dict)
    output_artifact_types: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    required: bool = True
    fallback: str | None = None
    policy: RunPolicy = Field(default_factory=RunPolicy)

    @model_validator(mode="after")
    def validate_dependencies(self) -> "ChildTaskSpec":
        if self.child_id in self.dependencies:
            raise ValueError("child task cannot depend on itself")
        if len(set(self.dependencies)) != len(self.dependencies):
            raise ValueError("child task dependencies must be unique")
        return self


class ChildTaskOutcome(ContractModel):
    """Safe parent projection after one child has completed or failed."""

    child_id: str = Field(min_length=1)
    status: Literal["succeeded", "failed", "waiting", "cancelled", "blocked"]
    artifact_ids: list[str] = Field(default_factory=list)
    quality_report_id: str | None = None
    fallback_used: str | None = None
    delivery_blocked: bool = False
    failure_code: str | None = None


class NodeSpec(ContractModel):
    node_id: str = Field(min_length=1)
    skill_id: str = Field(min_length=1)
    input_refs: list[str] = Field(default_factory=list)
    output_schema: str = Field(min_length=1)
    dependencies: list[str] = Field(default_factory=list)
    estimated_cost: float | None = Field(default=None, ge=0)
    timeout_ms: int = Field(default=120_000, ge=1)
    retry_policy: dict[str, Any] = Field(default_factory=dict)
    concurrency_group: str = Field(default="default", min_length=1)
    required_capabilities: list[str] = Field(default_factory=list)
    side_effect_class: SideEffectClass = "none"
    validator_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_dependencies(self) -> "NodeSpec":
        if self.node_id in self.dependencies:
            raise ValueError("node cannot depend on itself")
        if len(set(self.dependencies)) != len(self.dependencies):
            raise ValueError("node dependencies must be unique")
        return self


class ContextPack(ContractModel):
    pack_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    stage_id: str = Field(min_length=1)
    query: str = Field(min_length=1, max_length=4000)
    records: list[dict[str, Any]] = Field(default_factory=list)
    source_artifact_ids: list[str] = Field(default_factory=list)
    token_budget: int = Field(default=2000, ge=256)
    retrieval_trace_id: str | None = None
    scope: dict[str, str] = Field(default_factory=dict)
    context_text: str = ""
    context_level: Literal["L0", "L1", "L2"] = "L2"


def project_progress_event(event: Mapping[str, Any], *, sequence: int) -> RunEvent:
    """Project a legacy progress event into the replayable common contract."""

    payload = dict(event)
    return RunEvent(
        event_id=str(payload.get("event_id", f"evt-{sequence}")),
        run_id=str(payload["run_id"]),
        task_id=str(payload["task_id"]),
        sequence=sequence,
        stage=str(payload["stage"]),
        status=payload["status"],
        progress=int(payload.get("progress", 0)),
        message=str(payload.get("message", "")),
        child_id=payload.get("child_id"),
        skill_call_id=payload.get("skill_call_id"),
        artifact_id=payload.get("artifact_id"),
        error_code=payload.get("error_code"),
        requires_action=bool(payload.get("requires_action", False)),
        wait_reason=str(payload.get("wait_reason", "")),
        quality_status=payload.get("quality_status", "pending"),
        quality_report_id=payload.get("quality_report_id"),
        child_count=int(payload.get("child_count", 0) or 0),
        provider=payload.get("provider"),
        model=payload.get("model"),
        usage=payload.get("usage"),
        cache_status=payload.get("cache_status"),
        source_sequence=int(payload.get("source_sequence")) if payload.get("source_sequence") is not None else None,
        node_id=payload.get("node_id"),
        parent_node_id=payload.get("parent_node_id"),
        attempt_id=payload.get("attempt_id"),
        lane_id=payload.get("lane_id"),
        fallback=bool(payload.get("fallback", False)),
        provider_request_id=payload.get("provider_request_id"),
        usage_id=payload.get("usage_id"),
        timestamp=str(payload.get("timestamp", _utc_now())),
    )


class RequestConstraints(ContractModel):
    slide_count: int | None = Field(default=None, ge=1)
    page_count: int | None = Field(default=None, ge=1)
    theme_id: str | None = None
    color_palette: list[str] = Field(default_factory=list)
    theme_tokens: dict[str, str] = Field(default_factory=dict)
    required_sections: list[str] = Field(default_factory=list)
    revision_scope: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_page_count(self) -> "RequestConstraints":
        if self.slide_count is not None and self.page_count is not None and self.slide_count != self.page_count:
            raise ValueError("slide_count and page_count must match when both are provided")
        if self.slide_count is None and self.page_count is not None:
            self.slide_count = self.page_count
        return self


class EvidenceRef(ContractModel):
    evidence_id: str
    source_id: str
    provenance: dict[str, Any] = Field(default_factory=dict)
    classification_level: str


class PreparationRecord(ContractModel):
    preparation_id: str
    context_pack_id: str
    normalized_request: dict[str, Any]
    authorized_user_id: str
    case_id: str
    task_id: str
    classification: str
    selected_pipelines: list[str]
    constraint_set: RequestConstraints
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    memory_snapshot_id: str | None = None
    status: Literal["prepared", "needs_clarification", "rejected"]
    created_at: str
    expires_at: str
    consumed_by_run_id: str | None = None
    request_fingerprint: str


# ---------------------------------------------------------------------------
# NP-08 — Public DAG projection contracts
# ---------------------------------------------------------------------------

DAGNodeStatus = Literal[
    "pending", "ready", "running", "succeeded", "waiting", "failed", "blocked", "cancelled"
]

#: Node statuses for which failure details are permitted.
TERMINAL_NODE_STATUSES: frozenset[str] = frozenset({"failed", "blocked", "cancelled"})


class PublicChildSpec(ContractModel):
    """Minimal public description of an admitted child node (no internal spec fields)."""

    node_id: str = Field(min_length=1, max_length=120)
    skill_id: str = Field(min_length=1, max_length=120)
    dependencies: list[str] = Field(default_factory=list, max_length=100)
    output_schema_ref: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_dependencies(self) -> "PublicChildSpec":
        if len(self.dependencies) != len(set(self.dependencies)):
            raise ValueError("dependencies must be unique")
        return self


class PublicDAGNode(ContractModel):
    """Safe public projection of a single DAG node."""

    node_id: str = Field(min_length=1, max_length=120)
    skill_id: str = Field(min_length=1, max_length=120)
    status: DAGNodeStatus
    progress: int | None = Field(default=None, ge=0, le=100)
    attempt_id: str | None = Field(default=None, max_length=120)
    lane_id: str | None = Field(default=None, max_length=120)
    started_at: str | None = None
    completed_at: str | None = None
    repair_attempts: int = Field(default=0, ge=0)
    max_repairs: int = Field(default=0, ge=0)
    output_ref: str | None = Field(default=None, pattern=r"^artifact-[0-9a-f]{64}$")
    failure_code: str | None = Field(default=None, max_length=120)
    safe_failure_summary: str | None = Field(default=None, max_length=500)


class PublicDAGEdge(ContractModel):
    """Directed dependency edge between two public DAG nodes."""

    source: str = Field(min_length=1, max_length=120)
    target: str = Field(min_length=1, max_length=120)
    kind: Literal["dependency"] = "dependency"


class PublicDAGGraph(ContractModel):
    """Full public projection of a run's DAG, safe for external readers."""

    run_id: str = Field(min_length=1, max_length=120)
    revision: int = Field(default=0, ge=0)
    status: RunStatus
    created_at: str
    updated_at: str
    failure_code: str | None = Field(default=None, max_length=120)
    safe_failure_summary: str | None = Field(default=None, max_length=500)
    nodes: list[PublicDAGNode] = Field(default_factory=list)
    edges: list[PublicDAGEdge] = Field(default_factory=list)


class RunEnqueueIntent(ContractModel):
    """Durable outbox record describing a pending scheduler enqueue.

    ``created_at`` is intentionally ``Optional`` on input; the DAG store
    assigns it during persistence so callers cannot inject a timestamp.
    """

    event_id: str = Field(min_length=1, max_length=120)
    run_id: str = Field(min_length=1, max_length=120)
    queue_name: str = Field(min_length=1, max_length=120)
    payload_fingerprint: str = Field(min_length=1, max_length=120)
    created_at: str | None = None  # server-assigned during persistence


class DAGTransitionIntent(ContractModel):
    """Caller-supplied intent to advance DAG state.

    Scope rules
    -----------
    ``node`` scope
        - Requires ``node_id`` and ``node_status``.
        - ``failure_code`` / ``safe_failure_summary`` only allowed when
          ``node_status in TERMINAL_NODE_STATUSES`` (failed, blocked, cancelled).
        - Forbids run-level and admission fields.

    ``run`` scope
        - Requires ``run_status``.
        - ``failure_code`` / ``safe_failure_summary`` only allowed when
          ``run_status == "failed"``.
        - Forbids node and admission fields.

    ``admission`` scope
        - Requires ``parent_node_id`` and ``admitted_nodes``.
        - Forbids all node / run / failure fields.
    """

    event_id: str = Field(min_length=1, max_length=120)
    run_id: str = Field(min_length=1, max_length=120)
    scope: Literal["run", "node", "admission"]

    node_id: str | None = Field(default=None, max_length=120)
    parent_node_id: str | None = Field(default=None, max_length=120)
    node_status: DAGNodeStatus | None = None
    run_status: RunStatus | None = None
    admitted_nodes: list[PublicChildSpec] | None = None

    progress: int | None = Field(default=None, ge=0, le=100)
    attempt_id: str | None = Field(default=None, max_length=120)
    lane_id: str | None = Field(default=None, max_length=120)
    # started_at and completed_at are NOT accepted from callers; the store
    # derives them automatically from status transitions.
    failure_code: str | None = Field(default=None, max_length=120)
    safe_failure_summary: str | None = Field(default=None, max_length=500)
    output_ref: str | None = Field(default=None, pattern=r"^artifact-[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_scope(self) -> "DAGTransitionIntent":  # noqa: C901
        if self.scope == "node":
            if not self.node_id or not self.node_status:
                raise ValueError("node scope requires node_id and node_status")
            if self.run_status or self.parent_node_id or self.admitted_nodes:
                raise ValueError("node scope forbids run/admission fields")
            # Failure detail fields are only meaningful for terminal statuses.
            if self.node_status not in TERMINAL_NODE_STATUSES and (
                self.failure_code or self.safe_failure_summary
            ):
                raise ValueError(
                    "failure_code and safe_failure_summary are only allowed for terminal"
                    " node statuses: failed, blocked, cancelled"
                )
        elif self.scope == "run":
            if not self.run_status:
                raise ValueError("run scope requires run_status")
            if any(
                [
                    self.node_id,
                    self.node_status,
                    self.parent_node_id,
                    self.admitted_nodes,
                    self.progress,
                    self.attempt_id,
                    self.lane_id,
                    self.output_ref,
                ]
            ):
                raise ValueError("run scope forbids node/admission fields")
            if self.run_status != "failed" and (self.failure_code or self.safe_failure_summary):
                raise ValueError("run scope only allows failure fields when run_status is 'failed'")
        elif self.scope == "admission":
            if not self.parent_node_id or not self.admitted_nodes:
                raise ValueError("admission scope requires parent_node_id and admitted_nodes")
            if any(
                [
                    self.node_id,
                    self.node_status,
                    self.run_status,
                    self.progress,
                    self.attempt_id,
                    self.lane_id,
                    self.failure_code,
                    self.safe_failure_summary,
                    self.output_ref,
                ]
            ):
                raise ValueError("admission scope forbids node/run/failure fields")
        return self


class DAGTransitionRecord(ContractModel):
    """Durable record of an applied transition; revision and timestamp are server-assigned."""

    intent: DAGTransitionIntent
    revision: int = Field(ge=0)
    timestamp: str  # Server-generated ISO-8601 UTC
