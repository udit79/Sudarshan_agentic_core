"""MCP tool server for the DeepSeek Harness.

The Harness invokes this server as a trusted backend tool. It receives only
the public request contract and gets back the normal Sudarshan result. Memory
credentials, Cognee clients, and provider credentials stay in this Python
process and are never exposed as model tools.
"""

from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from integrations.deepseek_harness.adapter import get_harness_adapter
from integrations.deepseek_harness.contracts import (
    ArtifactResponse,
    DAGResponse,
    ObservabilityResponse,
    PreparationResponse,
    SkillInvokeResponse,
    StartRunResponse,
    StatusResponse,
    TrajectoryResponse,
    WaitResponse,
)


mcp = FastMCP(
    "sudarshan-agentic-core",
    instructions=(
        "Use start_sudarshan_run for asynchronous NTRO case operations. Use "
        "get_sudarshan_status for frontend-safe progress, "
        "get_sudarshan_artifact for verified artifact manifests, "
        "get_sudarshan_dag for execution graph visualization, "
        "get_sudarshan_trajectory for the safe execution timeline and parallel lanes, "
        "wait_sudarshan for bounded waiting on completion or user action, "
        "resume_sudarshan for clarification or approval decisions, and "
        "cancel_sudarshan for cooperative cancellation. The tools route "
        "through the application orchestrator and return validated output "
        "or an actionable state. Use the scoped evidence search tools for "
        "source-grounded retrieval; do not re-ingest files or request raw "
        "memory-provider credentials."
    ),
)


# The external MCP contract stays backwards-compatible with the complete
# surface. Native Harness sessions use role-specific profiles so models do
# not pay for overlapping or internal tools.
MCP_TOOL_PROFILES: dict[str, frozenset[str] | None] = {
    "full": None,
    "artifact": frozenset(
        {
            "start_sudarshan_run",
            "get_sudarshan_status",
            "wait_sudarshan",
            "cancel_sudarshan",
            "get_sudarshan_artifact",
            "get_sudarshan_dag",
            "get_sudarshan_trajectory",
        }
    ),
    "specialist": frozenset(
        {
            "start_sudarshan_run",
            "get_sudarshan_status",
            "wait_sudarshan",
            "cancel_sudarshan",
            "get_sudarshan_artifact",
            "get_sudarshan_dag",
            "get_sudarshan_trajectory",
            "list_sudarshan_skills",
            "get_sudarshan_skill",
        }
    ),
    "operator": frozenset(
        {
            "start_sudarshan_run",
            "get_sudarshan_status",
            "wait_sudarshan",
            "resume_sudarshan",
            "cancel_sudarshan",
            "get_sudarshan_artifact",
            "get_sudarshan_usage",
            "get_sudarshan_observability",
            "get_sudarshan_trajectory",
            "get_sudarshan_dag",
            "get_sudarshan_health",
        }
    ),
    "reviewer": frozenset(
        {
            "get_sudarshan_status",
            "wait_sudarshan",
            "get_sudarshan_artifact",
            "get_sudarshan_dag",
            "get_sudarshan_trajectory",
            "resume_sudarshan",
        }
    ),
}


def _call(operation: str, *args: Any, **kwargs: Any) -> Any:
    """Route MCP requests through the replaceable application boundary."""

    return get_harness_adapter().call(operation, *args, **kwargs)  # type: ignore[arg-type]


def configure_mcp_tool_profile(profile: str | None = None) -> str:
    """Apply an allow-listed MCP tool profile before the server starts."""

    selected = (profile or os.getenv("SUDARSHAN_MCP_TOOL_PROFILE", "full")).strip().lower()
    allowed = MCP_TOOL_PROFILES.get(selected)
    if selected not in MCP_TOOL_PROFILES:
        choices = ", ".join(sorted(MCP_TOOL_PROFILES))
        raise ValueError(f"Unknown SUDARSHAN_MCP_TOOL_PROFILE {selected!r}; choose {choices}")
    if allowed is not None:
        for tool in tuple(mcp._tool_manager.list_tools()):
            if tool.name not in allowed:
                mcp.remove_tool(tool.name)
    return selected


@mcp.tool(
    name="run_sudarshan",
    description=(
        "Compatibility synchronous operation. (In native model sessions, "
        "use start_sudarshan_run instead for non-blocking admission)."
    ),
)
def run_sudarshan(
    query: str,
    user_id: str,
    case_id: str,
    task_id: str,
    classification_level: str = "RESTRICTED",
    distribution: str = "Authorized NTRO personnel",
    requested_pipelines: list[str] | None = None,
    operation: str = "create",
    parent_run_id: str | None = None,
    parent_artifact_id: str | None = None,
    revision_instruction: str | None = None,
    revision_scope: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the real application boundary; never synthesize a pipeline result."""

    payload: dict[str, Any] = {
        "query": query,
        "user_id": user_id,
        "case_id": case_id,
        "task_id": task_id,
        "classification_level": classification_level,
        "distribution": distribution,
        "requested_pipelines": requested_pipelines or [],
        "operation": operation,
        "parent_run_id": parent_run_id,
        "parent_artifact_id": parent_artifact_id,
        "revision_instruction": revision_instruction,
        "revision_scope": revision_scope or [],
        "metadata": metadata or {},
    }
    return _call("run", payload)


@mcp.tool(
    name="resume_sudarshan",
    description=(
        "Resume a paused Sudarshan run with a clarification answer or an "
        "authorized approval/revision decision."
    ),
)
def resume_sudarshan(
    run_id: str,
    task_id: str,
    decision: dict[str, Any],
) -> dict[str, Any]:
    """Resume a durable LangGraph checkpoint without exposing raw memory."""

    return _call("resume", run_id, task_id, decision)


@mcp.tool(
    name="cancel_sudarshan",
    description="Request cooperative cancellation of a Sudarshan run.",
)
def cancel_sudarshan(run_id: str, task_id: str) -> dict[str, str]:
    """Cancel an active or paused run and preserve its Task audit event."""

    return _call("cancel", run_id, task_id)


@mcp.tool(
    name="get_sudarshan_status",
    description=(
        "Read frontend-safe status and ordered progress events for a run. "
        "Raw Cognee context and model reasoning are never returned."
    ),
)
def get_sudarshan_status(run_id: str) -> StatusResponse:
    """Return the application status projection for one run."""

    raw = _call("status", run_id)
    if isinstance(raw, StatusResponse):
        return raw
    return StatusResponse.model_validate(raw)


@mcp.tool(
    name="get_sudarshan_artifact",
    description=(
        "Return a verified, frontend-safe manifest and stable download URI for "
        "a generated artifact. Filesystem paths and raw artifact bytes are not returned."
    ),
)
def get_sudarshan_artifact(
    artifact_id: str,
    user_id: str,
    case_id: str,
    task_id: str,
    classification_level: str = "RESTRICTED",
) -> ArtifactResponse:
    """Read one integrity-checked artifact manifest through the application boundary."""

    raw = _call(
        "get_artifact",
        artifact_id,
        classification_level=classification_level,
        user_id=user_id,
        case_id=case_id,
        task_id=task_id,
    )
    if isinstance(raw, ArtifactResponse):
        return raw
    return ArtifactResponse.model_validate(raw)


@mcp.tool(
    name="prepare_sudarshan_request",
    description="Propose a structured request and return an idempotent preparation handle.",
)
def prepare_sudarshan_request(
    query: str,
    user_id: str,
    case_id: str,
    task_id: str,
    idempotency_key: str,
    classification_level: str = "RESTRICTED",
    distribution: str = "Authorized NTRO personnel",
    requested_pipelines: list[str] | None = None,
    constraints: dict[str, Any] | None = None,
    evidence_refs: list[dict[str, Any]] | None = None,
) -> PreparationResponse:
    raw = _call(
        "prepare",
        {
            "query": query,
            "user_id": user_id,
            "case_id": case_id,
            "task_id": task_id,
            "idempotency_key": idempotency_key,
            "classification_level": classification_level,
            "distribution": distribution,
            "requested_pipelines": requested_pipelines or [],
            "constraints": constraints or {},
            "evidence_refs": evidence_refs or [],
        },
        operator_id=user_id,
    )
    if isinstance(raw, PreparationResponse):
        return raw
    return PreparationResponse.model_validate(raw)


@mcp.tool(
    name="start_sudarshan_run",
    description=(
        "Canonical admission: Start an asynchronous Sudarshan operation and return its run handle. "
        "Use wait_sudarshan or get_sudarshan_status for progress."
    ),
)
def start_sudarshan_run(
    query: str,
    user_id: str,
    case_id: str,
    task_id: str,
    classification_level: str = "RESTRICTED",
    distribution: str = "Authorized NTRO personnel",
    requested_pipelines: list[str] | None = None,
    operation: str = "create",
    parent_run_id: str | None = None,
    parent_artifact_id: str | None = None,
    revision_instruction: str | None = None,
    revision_scope: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    preparation_id: str | None = None,
    idempotency_key: str | None = None,
) -> StartRunResponse:
    """Validate and enqueue an operation without blocking the Harness call."""

    raw = _call(
        "submit",
        {
            "query": query,
            "user_id": user_id,
            "case_id": case_id,
            "task_id": task_id,
            "classification_level": classification_level,
            "distribution": distribution,
            "requested_pipelines": requested_pipelines or [],
            "operation": operation,
            "parent_run_id": parent_run_id,
            "parent_artifact_id": parent_artifact_id,
            "revision_instruction": revision_instruction,
            "revision_scope": revision_scope or [],
            "metadata": metadata or {},
            "preparation_id": preparation_id,
            "idempotency_key": idempotency_key,
        },
        operator_id=user_id,
    )
    if isinstance(raw, StartRunResponse):
        return raw
    return StartRunResponse.model_validate(raw)


@mcp.tool(
    name="wait_sudarshan",
    description="Wait for a bounded period for completion or required user action.",
)
def wait_sudarshan(
    run_id: str,
    timeout_ms: int = 30_000,
    after_sequence: int = 0,
) -> WaitResponse:
    """Return a safe status projection and only events after the cursor."""

    raw = _call(
        "wait",
        run_id,
        timeout_ms=timeout_ms,
        after_sequence=after_sequence,
    )
    if isinstance(raw, WaitResponse):
        return raw
    return WaitResponse.model_validate(raw)


@mcp.tool(
    name="get_sudarshan_health",
    description="Get system operational status, memory connection, and registered pipelines."
)
def get_sudarshan_health() -> dict[str, Any]:
    """Operational health check."""
    return _call("health")


@mcp.tool(
    name="cleanup_sudarshan_lifecycle",
    description="Preview or execute safe retention cleanup for expired derived data.",
)
def cleanup_sudarshan_lifecycle(dry_run: bool = True, older_than_seconds: int = 86400) -> dict[str, Any]:
    return _call(
        "cleanup_lifecycle",
        dry_run=dry_run,
        older_than_seconds=older_than_seconds,
    )


@mcp.tool(
    name="get_sudarshan_usage",
    description="Read safe token, tool, wall-time, cost, and concurrency budget counters for a skill run.",
)
def get_sudarshan_usage(run_id: str) -> dict[str, Any]:
    return _call("usage", run_id)


@mcp.tool(
    name="get_sudarshan_observability",
    description=(
        "Operator-only safe execution trace. Shows lifecycle events for the run, "
        "including Cognee recall/remember start, completion, counts, timing, "
        "backend, query hash, and trace ID. Never returns prompts, raw memory, "
        "provider payloads, or model reasoning."
    ),
)
def get_sudarshan_observability(
    run_id: str,
    operator_id: str,
    limit: int = 500,
) -> ObservabilityResponse:
    raw = _call("observability_events", run_id, operator_id=operator_id, limit=limit)
    if isinstance(raw, ObservabilityResponse):
        return raw
    return ObservabilityResponse.model_validate(raw)


@mcp.tool(
    name="get_sudarshan_trajectory",
    description=(
        "Read the safe, ordered execution trajectory for a run. It includes "
        "recorded lifecycle steps and parallel lane summaries for child skills, "
        "memory, cache, quality, fallback, and provider events. It never returns "
        "prompts, raw memory, provider payloads, credentials, or hidden reasoning. "
        "The durable DAG remains the source of truth for dependencies."
    ),
)
def get_sudarshan_trajectory(
    run_id: str,
    operator_id: str,
    limit: int = 500,
) -> TrajectoryResponse:
    raw = _call("trajectory", run_id, operator_id=operator_id, limit=limit)
    if isinstance(raw, TrajectoryResponse):
        return raw
    return TrajectoryResponse.model_validate(raw)


@mcp.tool(
    name="list_sudarshan_skills",
    description=(
        "List canonical Sudarshan skills and their safe capabilities. Use this "
        "before selecting a specialist; unavailable skills are discovery-only."
    ),
)
def list_sudarshan_skills() -> list[dict[str, Any]]:
    return _call("list_skills")


@mcp.tool(
    name="get_sudarshan_skill",
    description="Get the versioned manifest and output contract for one Sudarshan skill.",
)
def get_sudarshan_skill(skill_id: str) -> dict[str, Any]:
    return _call("get_skill", skill_id)


@mcp.tool(
    name="invoke_sudarshan_skill",
    description=(
        "Invoke one available specialist locally through the typed SkillRuntime. "
        "Use this for a bounded child skill; do not recursively call run_sudarshan."
    ),
)
def invoke_sudarshan_skill(
    skill_id: str,
    parent_run_id: str,
    parent_node_id: str,
    user_id: str,
    case_id: str,
    task_id: str,
    query: str,
    classification_level: str = "RESTRICTED",
    distribution: str = "Authorized NTRO personnel",
    metadata: dict[str, Any] | None = None,
) -> SkillInvokeResponse:
    raw = _call(
        "invoke_a2a",
        {
            "skill_id": skill_id,
            "parent_run_id": parent_run_id,
            "parent_node_id": parent_node_id,
            "user_id": user_id,
            "case_id": case_id,
            "task_id": task_id,
            "query": query,
            "classification_level": classification_level,
            "distribution": distribution,
            "metadata": metadata or {},
        },
        operator_id=user_id,
    )
    if isinstance(raw, SkillInvokeResponse):
        return raw
    # Keep the public MCP response stable while the internal child handoff is
    # now the same A2A envelope used by the HTTP transport.
    return SkillInvokeResponse(
        status=str(raw.get("status", "failed")),
        run_id=str(raw.get("run_id", parent_run_id)),
        task_id=task_id,
        skill_id=skill_id,
        artifacts=list(raw.get("artifacts") or []),
        quality_status=str((raw.get("quality_receipts") or [{}])[0].get("status", "partial")),
        lineage=raw.get("lineage"),
        result=dict(raw.get("result") or {}),
    )


@mcp.tool(
    name="start_sudarshan_skill",
    description=(
        "Start one available canonical skill as a durable background job. "
        "Use wait_sudarshan or get_sudarshan_status with the returned run handle."
    ),
)
def start_sudarshan_skill(
    skill_id: str,
    query: str,
    user_id: str,
    case_id: str,
    task_id: str,
    classification_level: str = "RESTRICTED",
    distribution: str = "Authorized NTRO personnel",
    metadata: dict[str, Any] | None = None,
) -> StartRunResponse:
    raw = _call(
        "submit_skill",
        {
            "skill_id": skill_id,
            "query": query,
            "user_id": user_id,
            "case_id": case_id,
            "task_id": task_id,
            "classification_level": classification_level,
            "distribution": distribution,
            "metadata": metadata or {},
        },
        operator_id=user_id,
    )
    if isinstance(raw, StartRunResponse):
        return raw
    return StartRunResponse.model_validate(raw)


@mcp.tool(
    name="list_sudarshan_pipelines",
    description="List all available generative pipelines registered in the backend."
)
def list_sudarshan_pipelines() -> list[str]:
    """Discover available pipelines."""
    return _call("list_pipelines")


@mcp.tool(
    name="remember_sudarshan_context",
    description="Persist User/Case-scoped session context into the memory system."
)
def remember_sudarshan_context(user_id: str, case_id: str, context: str) -> str:
    """Store session memory."""
    _call("remember_context", user_id, case_id, context)
    return "Session context saved successfully."


@mcp.tool(
    name="recall_sudarshan_context",
    description="Load bounded User/Case context from the memory system for Harness-level routing."
)
def recall_sudarshan_context(user_id: str, case_id: str, query: str) -> str:
    """Recall session memory."""
    return _call("recall_session_context", user_id, case_id, query)


@mcp.tool(
    name="search_sudarshan_text_evidence",
    description="Search scoped text, PDF-page, and PPTX-slide evidence without re-ingesting the source.",
)
def search_sudarshan_text_evidence(
    query: str,
    user_id: str,
    case_id: str,
    task_id: str | None = None,
    top_k: int = 10,
    classification_level: str = "RESTRICTED",
) -> list[dict[str, Any]]:
    return _call(
        "search_text_evidence",
        query,
        user_id=user_id,
        case_id=case_id,
        task_id=task_id,
        top_k=top_k,
        classification_level=classification_level,
    )


@mcp.tool(
    name="search_sudarshan_visual_evidence",
    description="Search scoped image and video visual evidence with provenance and locations.",
)
def search_sudarshan_visual_evidence(
    query: str,
    user_id: str,
    case_id: str,
    task_id: str | None = None,
    top_k: int = 10,
    classification_level: str = "RESTRICTED",
) -> list[dict[str, Any]]:
    return _call(
        "search_visual_evidence",
        query,
        user_id=user_id,
        case_id=case_id,
        task_id=task_id,
        top_k=top_k,
        classification_level=classification_level,
    )


@mcp.tool(
    name="search_sudarshan_table_evidence",
    description="Search scoped table evidence and return source-linked records.",
)
def search_sudarshan_table_evidence(
    query: str,
    user_id: str,
    case_id: str,
    task_id: str | None = None,
    top_k: int = 10,
    classification_level: str = "RESTRICTED",
) -> list[dict[str, Any]]:
    return _call(
        "search_table_evidence",
        query,
        user_id=user_id,
        case_id=case_id,
        task_id=task_id,
        top_k=top_k,
        classification_level=classification_level,
    )


@mcp.tool(
    name="search_sudarshan_video_segment",
    description="Search scoped timestamped video scenes, ASR, and OCR evidence.",
)
def search_sudarshan_video_segment(
    query: str,
    user_id: str,
    case_id: str,
    task_id: str | None = None,
    top_k: int = 10,
    classification_level: str = "RESTRICTED",
) -> list[dict[str, Any]]:
    return _call(
        "search_video_segment_evidence",
        query,
        user_id=user_id,
        case_id=case_id,
        task_id=task_id,
        top_k=top_k,
        classification_level=classification_level,
    )


@mcp.tool(
    name="get_sudarshan_evidence",
    description="Fetch one authorized evidence block with provenance and relationships.",
)
def get_sudarshan_evidence(
    evidence_id: str,
    user_id: str,
    case_id: str,
    task_id: str | None = None,
    classification_level: str = "RESTRICTED",
) -> dict[str, Any]:
    return _call(
        "get_evidence",
        evidence_id,
        user_id=user_id,
        case_id=case_id,
        task_id=task_id,
        classification_level=classification_level,
    )


@mcp.tool(
    name="get_sudarshan_dag",
    description=(
        "Return the public DAG projection for a run. "
        "Shows node statuses, dependencies, progress, lanes, and timing for all tasks "
        "in the execution graph. Use after_revision to poll for updates efficiently: "
        "pass the revision from the last response to receive only when something changed. "
        "Returns {status: 'not_changed'} when the graph has not advanced past after_revision."
    ),
)
def get_sudarshan_dag(
    run_id: str,
    operator_id: str,
    after_revision: int = 0,
    include_failure_details: bool = False,
) -> DAGResponse:
    """Read the public DAG for *run_id* through the application boundary."""
    from integrations.deepseek_harness.application import get_application

    try:
        raw = get_application().get_dag(
            run_id,
            operator_id,
            after_revision=after_revision,
            include_failure_details=include_failure_details,
        )
        if isinstance(raw, DAGResponse):
            return raw
        return DAGResponse.model_validate(raw)
    except PermissionError as exc:
        return DAGResponse(status="forbidden", run_id=run_id, updated_at=str(exc))
    except KeyError:
        return DAGResponse(status="not_found", run_id=run_id)


if __name__ == "__main__":
    configure_mcp_tool_profile()
    mcp.run(transport="stdio")
