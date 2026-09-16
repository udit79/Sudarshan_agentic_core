"""Acceptance tests for NP-04 preparation semantics and NP-11 A2A parity."""

from __future__ import annotations

from threading import Lock
from types import SimpleNamespace

from integrations.deepseek_harness.a2a import (
    A2AResponseEnvelope,
    A2ATaskEnvelope,
    invoke_local_task,
    submit_task,
)
from integrations.deepseek_harness.application import SudarshanApplication
from integrations.deepseek_harness.contracts import PreparationResponse
from pipelines.orchestrator.contracts import ContextPack


class _PreparationStore:
    def __init__(self) -> None:
        self.records: dict[str, dict] = {}

    def preparation_create_if_absent(self, key: str, fingerprint: str, record: dict) -> dict:
        existing = self.records.get(key)
        if existing is not None:
            if existing["request_fingerprint"] != fingerprint:
                from api.control_plane import ControlPlaneConflict

                raise ControlPlaneConflict("different request")
            return existing
        self.records[key] = dict(record)
        return self.records[key]

    def preparation_get(self, key: str):
        return self.records.get(key)


def _preparation_app() -> SudarshanApplication:
    app = object.__new__(SudarshanApplication)
    memory_calls = []

    def recall_context_pack(*args, **kwargs):
        memory_calls.append(args[1])
        return ContextPack(
            pack_id="pack-1",
            run_id=kwargs["run_id"],
            stage_id=kwargs["stage_id"],
            query=args[0],
            retrieval_trace_id="memory-snapshot-1",
            context_text="bounded case context",
        )

    app.orchestrator = SimpleNamespace(
        registry={"presentation": object()},
        memory_manager=SimpleNamespace(
            recall_context_pack=recall_context_pack,
        ),
    )
    app._preparation_memory_calls = memory_calls
    app.scheduler = _PreparationStore()
    app._preparations = {}
    app._preparations_lock = Lock()
    return app


def _request(**overrides):
    payload = {
        "query": "Create a case briefing",
        "user_id": "user-1",
        "case_id": "case-1",
        "task_id": "task-1",
        "idempotency_key": "prep-key-1",
        "requested_pipelines": ["presentation"],
        "constraints": {"slide_count": 2},
    }
    payload.update(overrides)
    return payload


def test_prepare_returns_typed_prepared_response_and_persists_snapshot() -> None:
    app = _preparation_app()
    result = PreparationResponse.model_validate(app.prepare(_request(), operator_id="user-1"))

    assert result.status == "prepared"
    assert result.preparation_id == "prep-prep-key-1"
    assert result.context_pack_id == "pack-1"
    assert result.memory_snapshot_id == "memory-snapshot-1"
    assert result.normalized_request["requested_pipelines"] == ["presentation"]
    assert app.scheduler.preparation_get("prep-key-1")["status"] == "prepared"
    assert app._preparation_memory_calls[0].user_id == "user-1"
    assert app._preparation_memory_calls[0].case_id == "case-1"
    assert app._preparation_memory_calls[0].task_id is None


def test_prepare_exposes_clarification_and_rejection_without_creating_a_run() -> None:
    app = _preparation_app()
    clarification = PreparationResponse.model_validate(
        app.prepare(_request(idempotency_key="clarify-1", requested_pipelines=[]), operator_id="user-1")
    )
    rejected = PreparationResponse.model_validate(
        app.prepare(_request(idempotency_key="reject-1", requested_pipelines=["unknown"]), operator_id="user-1")
    )

    assert clarification.status == "needs_clarification"
    assert clarification.clarification_questions
    assert rejected.status == "rejected"
    assert rejected.rejection_code == "INVALID_REQUEST"


class _A2AApplication:
    def submit(self, payload, *, operator_id):
        return {
            "run_id": "run-remote",
            "task_id": payload["task_id"],
            "status": "queued",
            "lineage": {
                "root_run_id": "run-parent",
                "parent_run_id": "run-parent",
                "parent_node_id": "node-1",
                "lineage_depth": 1,
                "revision_sequence": 0,
                "causal_chain": ["run-parent"],
                "trace_id": "trace-1",
            },
        }

    def invoke_skill(self, payload, **kwargs):
        assert kwargs["operator_id"] == payload["user_id"]
        return {
            "run_id": payload["parent_run_id"],
            "task_id": payload["task_id"],
            "status": "succeeded",
            "lineage": {
                "root_run_id": payload["parent_run_id"],
                "parent_run_id": payload["parent_run_id"],
                "parent_node_id": payload["parent_node_id"],
                "lineage_depth": 1,
                "revision_sequence": 0,
                "causal_chain": [payload["parent_run_id"]],
                "trace_id": "trace-1",
            },
            "artifacts": [{"artifact_id": "artifact-child"}],
            "quality_status": "passed",
            "result": {"accepted": True},
        }


def test_local_and_remote_a2a_use_the_same_envelope_fields() -> None:
    app = _A2AApplication()
    envelope = A2ATaskEnvelope(
        task_id="task-child",
        skill_id="infographic",
        target_pipeline="infographic",
        query="Create the supporting visual",
        user_id="user-1",
        case_id="case-1",
        idempotency_key="child-key-1",
        budget_cap={"max_model_tokens": 500},
        evidence_refs=[{"evidence_id": "e-1"}],
        lineage={
            "root_run_id": "run-parent",
            "parent_run_id": "run-parent",
            "parent_node_id": "node-1",
            "lineage_depth": 1,
            "revision_sequence": 0,
            "causal_chain": ["run-parent"],
            "trace_id": "trace-1",
        },
    )

    local = A2AResponseEnvelope.model_validate(
        invoke_local_task(app, envelope, operator_id="user-1")
    )
    remote = A2AResponseEnvelope.model_validate(
        submit_task(app, envelope, operator_id="user-1")
    )

    for response in (local, remote):
        assert response.task_id == "task-child"
        assert response.lineage is not None
        assert response.evidence_refs == [{"evidence_id": "e-1"}]
        assert response.budget == {"max_model_tokens": 500}
    assert local.artifacts == [{"artifact_id": "artifact-child"}]
    assert remote.status == "queued"
