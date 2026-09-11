"""Small A2A-compatible task envelope over the Sudarshan application boundary."""

from __future__ import annotations

from typing import Any, Mapping


def agent_card(base_url: str = "") -> dict[str, Any]:
    return {
        "name": "Sudarshan Agentic Core",
        "description": "Policy-controlled NTRO artifact and evidence transformation agent.",
        "url": str(base_url).rstrip("/"),
        "version": "2.0",
        "capabilities": {"streaming": True, "pushNotifications": False},
        "skills": [
            {"id": "sudarshan.run", "name": "Run a bounded transformation"},
            {"id": "sudarshan.status", "name": "Read a safe task projection"},
            {"id": "sudarshan.cancel", "name": "Request cooperative cancellation"},
        ],
        "securitySchemes": {"operator": {"type": "apiKey", "in": "header", "name": "X-Operator-Id"}},
    }


def submit_task(application: Any, payload: Mapping[str, Any], *, operator_id: str) -> dict[str, Any]:
    result = application.submit(dict(payload), operator_id=operator_id)
    run_id = str(result.get("run_id") or result.get("task_id") or "")
    return {
        "id": run_id,
        "status": {"state": str(result.get("status", "queued"))},
        "artifacts": list(result.get("artifact_manifests") or []),
        "metadata": {"run_id": run_id, "task_id": result.get("task_id")},
    }


def get_task(application: Any, run_id: str) -> dict[str, Any]:
    result = application.status(run_id)
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


def cancel_task(application: Any, run_id: str, *, task_id: str) -> dict[str, Any]:
    result = application.cancel(run_id, task_id)
    return {"id": str(run_id), "status": {"state": str(result.get("status", "cancelled"))}}


__all__ = ["agent_card", "cancel_task", "get_task", "submit_task"]
