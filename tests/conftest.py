"""Deterministic test doubles shared by component, pipeline, and system tests."""

from __future__ import annotations

from typing import Any, Sequence
from types import SimpleNamespace

import pytest

from memory import MemoryManager
from pipelines.common.contracts import AdvisoryRequest, PipelineResponse


class RecordingBackend:
    """Small in-memory backend with the same boundary used by MemoryManager."""

    def __init__(self) -> None:
        self.writes: list[dict[str, Any]] = []

    def remember(self, **kwargs: Any) -> dict[str, str]:
        self.writes.append(kwargs)
        return {"status": "accepted", "pipeline_run_id": "test-run"}

    def recall(
        self,
        *,
        query: str,
        node_sets: Sequence[str],
        dataset_name: str,
        top_k: int,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        del query, dataset_name, session_id
        permitted = set(node_sets)
        results: list[dict[str, Any]] = []
        for item in self.writes:
            if not permitted.intersection(item["node_sets"]):
                continue
            results.append({
                "context": item["content"],
                "metadata": item["metadata"],
                "score": 1.0,
            })
        return results[:top_k]


@pytest.fixture
def recording_backend() -> RecordingBackend:
    return RecordingBackend()


@pytest.fixture
def memory_manager(recording_backend: RecordingBackend) -> MemoryManager:
    return MemoryManager(recording_backend)


def make_request(
    pipeline: str | None = None,
    *,
    query: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AdvisoryRequest:
    request_metadata = dict(metadata or {})
    if pipeline is not None:
        request_metadata["pipeline"] = pipeline
    return AdvisoryRequest(
        query=query or f"Run the {pipeline or 'requested'} operation",
        user_id="user-1",
        case_id="case-1",
        task_id="task-1",
        metadata=request_metadata,
    )


def successful_response(request: AdvisoryRequest, pipeline: str) -> PipelineResponse:
    return PipelineResponse(
        status="succeeded",
        pipeline=pipeline,
        task_id=request.task_id,
        run_id=str(request.metadata.get("run_id", "test-run")),
        output={"pipeline": pipeline, "validated": True},
    )


class FakeRecallManager:
    """Orchestrator-only memory double for tests that focus on routing."""

    def __init__(self, text: str = "verified case context") -> None:
        self.text = text
        self.recall_calls: list[dict[str, Any]] = []
        self.remember_calls: list[dict[str, Any]] = []

    def recall(self, **kwargs: Any) -> SimpleNamespace:
        self.recall_calls.append(kwargs)
        return SimpleNamespace(context=SimpleNamespace(text=self.text), results=[])

    def remember(self, *args: Any, **kwargs: Any) -> None:
        self.remember_calls.append({"args": args, "kwargs": kwargs})
