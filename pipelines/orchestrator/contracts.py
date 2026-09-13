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
    timestamp: str = Field(default_factory=_utc_now)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ArtifactManifest(ContractModel):
    """Immutable, classified description of a generated artifact."""

    artifact_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
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
    status: Literal["succeeded", "failed", "waiting", "cancelled", "blocked"]
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
        timestamp=str(payload.get("timestamp", _utc_now())),
    )
