"""Portable A2A task envelopes and specialist agent cards over the Sudarshan application boundary."""

from __future__ import annotations

from typing import Any, Mapping
from pydantic import BaseModel, Field

from integrations.deepseek_harness.contracts import LineageContext


class A2ATaskEnvelope(BaseModel):
    """Standardized task envelope for local and remote A2A handoff."""

    protocol_version: str = "2.0"
    task_id: str
    idempotency_key: str | None = None
    skill_id: str | None = None
    target_pipeline: str | None = None
    query: str
    input_references: list[dict[str, Any]] = Field(default_factory=list)
    lineage: LineageContext | None = None
    user_id: str
    case_id: str
    classification_level: str = "RESTRICTED"
    distribution: str = "Authorized NTRO personnel"
    budget_cap: dict[str, Any] | None = None
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    trace_id: str | None = None
    deadline: str | None = None
    cancellation_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class A2AResponseEnvelope(BaseModel):
    """Standardized response envelope for local and remote A2A handoff."""

    protocol_version: str = "2.0"
    task_id: str
    run_id: str
    status: str
    attempt_id: str | None = None
    lineage: LineageContext | None = None
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    quality_receipts: list[dict[str, Any]] = Field(default_factory=list)
    usage: dict[str, Any] | None = None
    budget: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    result: dict[str, Any] = Field(default_factory=dict)
    cancellation_propagated: bool = False
    failure_code: str | None = None
    failure_message: str | None = None


class A2AHandoffContext(BaseModel):
    """Context wrapper for parent-to-child agent handoffs."""

    parent_run_id: str
    parent_node_id: str
    root_run_id: str
    trace_id: str
    classification_level: str = "RESTRICTED"
    distribution: str = "Authorized NTRO personnel"
    parent_remaining_budget: dict[str, Any] = Field(default_factory=dict)
    authorized_evidence_ids: list[str] = Field(default_factory=list)
    lineage_depth: int = 0
    revision_sequence: int = 0


PIPELINE_DESCRIPTIONS: dict[str, str] = {
    "presentation": "NTRO Briefing and Multi-Slide Presentation Specialist",
    "infographic": "High-Impact Visual Infographic and SVG Layout Specialist",
    "diagram": "Structured System Architecture and Flow Diagram Specialist",
    "advisory": "Policy-Controlled NTRO Advisory Brief and Risk Assessment Specialist",
    "executive_summary": "Executive Decision Brief and Key Findings Specialist",
    "video": "Cinematic Storyboard, Narration, and Video Sequence Specialist",
}


def agent_card(base_url: str = "") -> dict[str, Any]:
    """Return the authoritative orchestrator agent card."""

    url = str(base_url).rstrip("/")
    return {
        "name": "Sudarshan Agentic Core",
        "description": "Policy-controlled NTRO artifact and evidence transformation orchestrator.",
        "url": url,
        "version": "2.0",
        "capabilities": {"streaming": True, "pushNotifications": False},
        "skills": [
            {"id": "sudarshan.run", "name": "Run a bounded transformation"},
            {"id": "sudarshan.status", "name": "Read a safe task projection"},
            {"id": "sudarshan.cancel", "name": "Request cooperative cancellation"},
            {"id": "sudarshan.dag", "name": "Read public execution DAG"},
        ],
        "securitySchemes": {"operator": {"type": "apiKey", "in": "header", "name": "X-Operator-Id"}},
    }


def agent_card_for_pipeline(pipeline_name: str, base_url: str = "") -> dict[str, Any]:
    """Return a specialist agent card pointing to the authoritative orchestrator."""

    key = str(pipeline_name).strip().lower()
    description = PIPELINE_DESCRIPTIONS.get(key, f"Sudarshan Specialist for {key}")
    url = str(base_url).rstrip("/")
    return {
        "name": f"Sudarshan Specialist: {key.capitalize()}",
        "description": description,
        "url": url,
        "version": "2.0",
        "capabilities": {"streaming": True, "pushNotifications": False},
        "pipeline": key,
        "skills": [
            {
                "id": f"sudarshan.specialist.{key}",
                "name": f"Execute {key} pipeline task",
                "description": description,
            },
            {
                "id": f"sudarshan.status.{key}",
                "name": f"Check {key} task status",
            },
        ],
        "securitySchemes": {"operator": {"type": "apiKey", "in": "header", "name": "X-Operator-Id"}},
    }


def submit_task(application: Any, payload: Mapping[str, Any] | A2ATaskEnvelope, *, operator_id: str) -> dict[str, Any]:
    """Admit an A2A task envelope through the unified application boundary."""

    # Keep the original small adapter usable by existing in-process callers;
    # remote callers use the validated envelope below.
    if not isinstance(payload, A2ATaskEnvelope):
        raw_payload = dict(payload)
        if not all(key in raw_payload for key in ("query", "user_id", "case_id")):
            result = application.submit(raw_payload, operator_id=operator_id)
            run_id = str(result.get("run_id") or result.get("task_id") or "")
            return {
                "id": run_id,
                "status": {"state": str(result.get("status", "queued"))},
                "artifacts": list(result.get("artifact_manifests") or []),
                "metadata": {"run_id": run_id, "task_id": result.get("task_id")},
            }

    if isinstance(payload, A2ATaskEnvelope):
        envelope = payload
    else:
        envelope = A2ATaskEnvelope.model_validate(dict(payload))
    if str(envelope.user_id).strip() != str(operator_id).strip():
        raise PermissionError("user_id must match the authenticated operator")

    submit_payload: dict[str, Any] = {
        "query": envelope.query,
        "user_id": envelope.user_id,
        "case_id": envelope.case_id,
        "task_id": envelope.task_id,
        "classification_level": envelope.classification_level,
        "distribution": envelope.distribution,
        "requested_pipelines": [envelope.target_pipeline] if envelope.target_pipeline else [],
        "idempotency_key": envelope.idempotency_key,
        "metadata": dict(envelope.metadata),
    }
    if envelope.lineage is not None:
        submit_payload["parent_run_id"] = envelope.lineage.parent_run_id
        submit_payload["metadata"]["lineage"] = envelope.lineage.model_dump(mode="json")
    if envelope.evidence_refs:
        submit_payload["metadata"]["evidence_refs"] = list(envelope.evidence_refs)
    if envelope.budget_cap:
        submit_payload["metadata"]["budget_cap"] = dict(envelope.budget_cap)

    result = application.submit(submit_payload, operator_id=operator_id)
    run_id = str(result.get("run_id") or result.get("task_id") or "")

    lineage_ctx = result.get("lineage")
    response_lineage = (
        LineageContext.model_validate(lineage_ctx)
        if isinstance(lineage_ctx, Mapping)
        else envelope.lineage
    )

    response = A2AResponseEnvelope(
        task_id=envelope.task_id,
        run_id=run_id,
        status=str(result.get("status", "queued")),
        attempt_id=result.get("attempt_id"),
        lineage=response_lineage,
        artifacts=list(result.get("artifact_manifests") or []),
        quality_receipts=_quality_receipts(result),
        usage=result.get("usage"),
        budget=dict(envelope.budget_cap or {}),
        evidence_refs=list(envelope.evidence_refs),
        result=dict(result.get("result") or result.get("skill_result") or {}),
        cancellation_propagated=str(result.get("status")) == "cancelled",
    )
    return response.model_dump(mode="json")


def _quality_receipts(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    receipt = result.get("quality_receipt") or result.get("quality_report")
    if isinstance(receipt, Mapping):
        return [dict(receipt)]
    quality_status = result.get("quality_status")
    return [{"status": str(quality_status)}] if quality_status else []


def invoke_local_task(
    application: Any,
    payload: Mapping[str, Any] | A2ATaskEnvelope,
    *,
    operator_id: str,
    cancel_event: Any = None,
    attempt_id: str | None = None,
    lease_token: str | None = None,
) -> dict[str, Any]:
    """Run the same A2A envelope locally through SkillRuntime.

    Remote POST /a2a/tasks and this local path intentionally share the same
    input/output envelope. Only the transport differs.
    """

    if isinstance(payload, A2ATaskEnvelope):
        envelope = payload
    else:
        raw = dict(payload)
        parent_run_id = str(raw.get("parent_run_id") or "").strip()
        parent_node_id = str(raw.get("parent_node_id") or "harness-skill").strip()
        lineage = raw.get("lineage")
        if lineage is None and parent_run_id:
            lineage = LineageContext(
                root_run_id=parent_run_id,
                parent_run_id=parent_run_id,
                parent_node_id=parent_node_id,
                lineage_depth=1,
                causal_chain=[parent_run_id],
                trace_id=str(raw.get("trace_id") or parent_run_id),
            )
        envelope = A2ATaskEnvelope.model_validate({**raw, "lineage": lineage})
    if str(envelope.user_id).strip() != str(operator_id).strip():
        raise PermissionError("user_id must match the authenticated operator")
    if not envelope.skill_id:
        raise ValueError("skill_id is required for local A2A invocation")
    if envelope.lineage is None or not envelope.lineage.parent_run_id:
        raise ValueError("parent lineage is required for local A2A invocation")

    metadata = dict(envelope.metadata)
    metadata.update(
        {
            "evidence_refs": list(envelope.evidence_refs),
            "input_references": list(envelope.input_references),
            "trace_id": envelope.trace_id,
        }
    )
    result = application.invoke_skill(
        {
            "skill_id": envelope.skill_id,
            "parent_run_id": envelope.lineage.parent_run_id,
            "parent_node_id": envelope.lineage.parent_node_id or "harness-skill",
            "user_id": envelope.user_id,
            "case_id": envelope.case_id,
            "task_id": envelope.task_id,
            "query": envelope.query,
            "classification_level": envelope.classification_level,
            "distribution": envelope.distribution,
            "budget_cap": envelope.budget_cap,
            "metadata": metadata,
        },
        operator_id=operator_id,
        cancel_event=cancel_event,
        attempt_id=attempt_id,
        lease_token=lease_token,
    )
    lineage_raw = result.get("lineage")
    lineage = (
        LineageContext.model_validate(lineage_raw)
        if isinstance(lineage_raw, Mapping)
        else envelope.lineage
    )
    response = A2AResponseEnvelope(
        task_id=envelope.task_id,
        run_id=str(result.get("run_id") or envelope.lineage.parent_run_id),
        status=str(result.get("status", "failed")),
        attempt_id=attempt_id,
        lineage=lineage,
        artifacts=list(result.get("artifacts") or []),
        quality_receipts=_quality_receipts(result),
        usage=result.get("usage"),
        budget=dict(envelope.budget_cap or {}),
        evidence_refs=list(envelope.evidence_refs),
        result=dict(result.get("result") or result.get("skill_result") or {}),
        cancellation_propagated=str(result.get("status")) == "cancelled",
        failure_code=result.get("failure_code"),
        failure_message=result.get("failure_message") or result.get("error"),
    )
    return response.model_dump(mode="json")


def get_task(application: Any, run_id: str, *, operator_id: str | None = None) -> dict[str, Any]:
    """Read A2A task status with mandatory operator authorization check."""

    result = application.status(run_id)
    if result.get("status") == "not_found":
        return {
            "id": str(run_id),
            "status": {"state": "not_found"},
            "artifacts": [],
            "metadata": {"run_id": str(run_id)},
        }

    # Verify operator authorization
    task_owner = result.get("user_id") or (
        result.get("authorized_user_id") if isinstance(result.get("authorized_user_id"), str) else None
    )
    # Check against run contexts if not top-level
    if not task_owner and hasattr(application, "_run_contexts"):
        ctx = application._run_contexts.get(str(run_id), {})
        task_owner = ctx.get("user_id") or ctx.get("operator_id")

    if not operator_id and (task_owner or hasattr(application, "_run_contexts")):
        raise PermissionError("operator_id is required to read task status")
    if task_owner and str(task_owner).strip() != str(operator_id).strip():
        raise PermissionError("operator_id does not match the task owner")

    return {
        "id": str(run_id),
        "status": {"state": str(result.get("status", "not_found"))},
        "artifacts": list(result.get("artifact_manifests") or []),
        "metadata": {
            "run_id": str(run_id),
            "event_cursor": result.get("event_cursor", 0),
            "wait_reason": result.get("wait_reason"),
        },
        "result": result.get("result") or result.get("responses"),
    }


def cancel_task(application: Any, run_id: str, *, task_id: str, operator_id: str | None = None) -> dict[str, Any]:
    """Request cancellation of an A2A task."""

    if operator_id is None:
        result = application.cancel(run_id, task_id)
    else:
        result = application.cancel(run_id, task_id, operator_id=operator_id)
    return {"id": str(run_id), "status": {"state": str(result.get("status", "cancelled"))}}


__all__ = [
    "A2AHandoffContext",
    "A2AResponseEnvelope",
    "A2ATaskEnvelope",
    "agent_card",
    "agent_card_for_pipeline",
    "cancel_task",
    "get_task",
    "invoke_local_task",
    "submit_task",
]
