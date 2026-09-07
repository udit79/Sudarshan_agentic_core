"""MCP tool server for the DeepSeek Harness.

The Harness invokes this server as a trusted backend tool. It receives only
the public request contract and gets back the normal Sudarshan result. Memory
credentials, Cognee clients, and provider credentials stay in this Python
process and are never exposed as model tools.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import Settings as FastMCPSettings

from integrations.deepseek_harness.application import get_application


# MCP's generic settings model contains a forward reference to FastMCP in its
# ``lifespan`` field. Rebuild it after the package has defined FastMCP and
# before constructing the server, otherwise pydantic-settings emits an
# incomplete-field warning on every process start.
FastMCPSettings.model_rebuild()


mcp = FastMCP(
    "sudarshan-agentic-core",
    instructions=(
        "Use run_sudarshan for NTRO case operations. Use "
        "get_sudarshan_status for frontend-safe progress, "
        "resume_sudarshan for clarification or approval decisions, and "
        "cancel_sudarshan for cooperative cancellation. The tools route "
        "through the application orchestrator and return validated output "
        "or an actionable state. Do not request or expose memory-provider "
        "credentials."
    ),
)


@mcp.tool(
    name="run_sudarshan",
    description=(
        "Run one Sudarshan operation. The backend owns memory, routing, "
        "pipeline execution, revisions, and provider adapters."
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
    return get_application().run(payload)


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

    return get_application().resume(run_id, task_id, decision)


@mcp.tool(
    name="cancel_sudarshan",
    description="Request cooperative cancellation of a Sudarshan run.",
)
def cancel_sudarshan(run_id: str, task_id: str) -> dict[str, str]:
    """Cancel an active or paused run and preserve its Task audit event."""

    return get_application().cancel(run_id, task_id)


@mcp.tool(
    name="get_sudarshan_status",
    description=(
        "Read frontend-safe status and ordered progress events for a run. "
        "Raw Cognee context and model reasoning are never returned."
    ),
)
def get_sudarshan_status(run_id: str) -> dict[str, Any]:
    """Return the application status projection for one run."""

    return get_application().status(run_id)


@mcp.tool(
    name="get_sudarshan_health",
    description="Get system operational status, memory connection, and registered pipelines."
)
def get_sudarshan_health() -> dict[str, Any]:
    """Operational health check."""
    return get_application().health()


@mcp.tool(
    name="list_sudarshan_pipelines",
    description="List all available generative pipelines registered in the backend."
)
def list_sudarshan_pipelines() -> list[str]:
    """Discover available pipelines."""
    return get_application().list_pipelines()


@mcp.tool(
    name="remember_sudarshan_context",
    description="Persist User/Case-scoped session context into the memory system."
)
def remember_sudarshan_context(user_id: str, case_id: str, context: str) -> str:
    """Store session memory."""
    get_application().remember_context(user_id, case_id, context)
    return "Session context saved successfully."


@mcp.tool(
    name="recall_sudarshan_context",
    description="Load bounded User/Case context from the memory system for Harness-level routing."
)
def recall_sudarshan_context(user_id: str, case_id: str, query: str) -> str:
    """Recall session memory."""
    return get_application().recall_session_context(user_id, case_id, query)


if __name__ == "__main__":
    mcp.run(transport="stdio")
