"""Focused application-memory behaviour matrix.

These tests use the MemoryBackend seam rather than a live Cognee tenant.  That
keeps scope, lifecycle, provenance, and failure behaviour deterministic while
still exercising the application abstraction used by Cognee in production.
"""

from __future__ import annotations

from datetime import timedelta
import re

import pytest

from memory import (
    AccessContext,
    KnowledgeUnit,
    MemoryLifecycle,
    MemoryManager,
    MemoryType,
    ScopeType,
    Source,
    SourceType,
)
from memory.model import utc_now


class RecordingBackend:
    """Small deterministic Cognee substitute for application-level tests."""

    def __init__(self) -> None:
        self.writes: list[dict] = []
        self.forced_results: list[dict] | None = None
        self.fail_remember = False
        self.fail_recall = False

    def remember(self, **kwargs):
        if self.fail_remember:
            raise RuntimeError("memory provider unavailable")
        self.writes.append(kwargs)
        return {"status": "accepted"}

    def recall(self, *, query, node_sets, dataset_name, top_k, session_id=None):
        if self.fail_recall:
            raise RuntimeError("memory provider unavailable")
        if self.forced_results is not None:
            return self.forced_results[:top_k]
        query_terms = set(re.findall(r"[a-z0-9]{3,}", query.casefold()))
        matches = []
        for item in self.writes:
            if not set(node_sets).intersection(item["node_sets"]):
                continue
            content_terms = set(re.findall(r"[a-z0-9]{3,}", item["content"].casefold()))
            if query_terms.intersection(content_terms):
                matches.append({
                    "content": item["content"],
                    "metadata": item["metadata"],
                    "score": 1.0,
                })
        return matches[:top_k]


def unit(
    unit_id: str,
    content: str,
    *,
    source_type: SourceType = SourceType.TEXT,
    reference: str | None = None,
    provenance: dict | None = None,
) -> KnowledgeUnit:
    return KnowledgeUnit(
        unit_id=unit_id,
        content=content,
        source=Source(unit_id, source_type, reference or f"test://{unit_id}"),
        provenance=provenance or {"fixture": "memory-behaviour-matrix"},
    )


def setup_memory():
    backend = RecordingBackend()
    return MemoryManager(backend), backend


def test_user_preference_is_explicit_user_profile() -> None:
    """User preference: durable profile data belongs to USER, not a case."""
    manager, _backend = setup_memory()
    context = AccessContext(user_id="user-pink", case_id="case-a")

    receipt = manager.remember_profile(
        {"visual_palette": "pink", "version": "1"}, context
    )
    response = manager.recall("pink", AccessContext(user_id="user-pink"))

    assert receipt.memory.scope.scope_type is ScopeType.USER
    assert receipt.memory.memory_type is MemoryType.PROFILE
    assert len(response.context.items) == 1
    assert "pink" in response.context.items[0].content


def test_case_information_is_available_only_inside_that_case() -> None:
    """Case fact: it may be inherited by tasks in the same case."""
    manager, _backend = setup_memory()
    case_context = AccessContext(user_id="user-a", case_id="case-horizon")
    manager.remember(unit("case-fact", "case-horizon threat level amber"), case_context)

    response = manager.recall(
        "case-horizon threat", AccessContext(user_id="user-a", case_id="case-horizon")
    )
    other_case = manager.recall(
        "case-horizon threat", AccessContext(user_id="user-a", case_id="case-other")
    )

    assert response.context.items
    assert other_case.context.items == ()


def test_task_information_is_available_only_inside_that_task() -> None:
    """Task event: narrow operational context must not become case-wide."""
    manager, _backend = setup_memory()
    task_context = AccessContext(user_id="user-a", case_id="case-a", task_id="task-orion")
    manager.remember(
        unit("task-event", "task-orion operator checkpoint complete"),
        task_context,
        scope_type=ScopeType.TASK,
        memory_type=MemoryType.EVENT,
    )

    in_task = manager.recall("task-orion checkpoint", task_context)
    in_case_only = manager.recall(
        "task-orion checkpoint", AccessContext(user_id="user-a", case_id="case-a")
    )

    assert in_task.context.items
    assert in_case_only.context.items == ()


def test_temporary_task_memory_expires() -> None:
    """Temporary memory is task-scoped and has an explicit expiry."""
    manager, _backend = setup_memory()
    context = AccessContext(user_id="user-a", case_id="case-a", task_id="task-temp")
    receipt = manager.remember(
        unit("temporary", "temporary staging token"),
        context,
        scope_type=ScopeType.TASK,
        memory_type=MemoryType.EVENT,
        expires_at=utc_now() + timedelta(seconds=1),
    )

    manager.expire_due(now=utc_now() + timedelta(minutes=1))

    assert manager.store.get_memory(receipt.memory.id).lifecycle is MemoryLifecycle.EXPIRED
    assert manager.recall("temporary staging", context).context.items == ()


def test_permanent_user_information_is_an_explicit_lesson() -> None:
    """Permanent user-level information requires an explicit helper call."""
    manager, _backend = setup_memory()
    context = AccessContext(user_id="user-a")

    receipt = manager.remember_lesson("user-a permanently prefers concise summaries", context)
    response = manager.recall("concise summaries", context)

    assert receipt.memory.scope.scope_type is ScopeType.USER
    assert receipt.memory.memory_type is MemoryType.LESSON
    assert receipt.memory.expires_at is None
    assert response.context.items


def test_generated_artifact_is_not_written_as_factual_memory() -> None:
    """Generated output is a summary pending review; source fact is separate."""
    manager, backend = setup_memory()
    context = AccessContext(user_id="user-a", case_id="case-a")

    manager.remember(
        unit("generated-slide", "generated slide says risk is low", source_type=SourceType.INFOGRAPHIC),
        context,
        memory_type=MemoryType.SUMMARY,
        lifecycle=MemoryLifecycle.PENDING_REVIEW,
    )
    manager.remember(
        unit("source-fact", "source report says risk is high", source_type=SourceType.PDF),
        context,
        memory_type=MemoryType.FACT,
    )

    artifact_write, fact_write = backend.writes
    assert artifact_write["metadata"]["memory_type"] == MemoryType.SUMMARY.value
    assert artifact_write["metadata"]["lifecycle"] == MemoryLifecycle.PENDING_REVIEW.value
    assert fact_write["metadata"]["memory_type"] == MemoryType.FACT.value
    recalled = manager.recall("risk", context).context.text
    assert "source report says risk is high" in recalled
    assert "generated slide says risk is low" not in recalled


def test_pending_review_is_the_current_memory_write_approval_boundary() -> None:
    """The current approval mechanism is lifecycle gating, not an approval API."""
    manager, _backend = setup_memory()
    context = AccessContext(user_id="user-a", case_id="case-a")
    receipt = manager.remember(
        unit("unapproved", "unapproved candidate fact"),
        context,
        lifecycle=MemoryLifecycle.PENDING_REVIEW,
    )

    assert receipt.memory.lifecycle is MemoryLifecycle.PENDING_REVIEW
    assert manager.recall("candidate fact", context).results == ()


def test_relevant_memory_is_ranked_and_recalled() -> None:
    manager, _backend = setup_memory()
    context = AccessContext(user_id="user-a", case_id="case-a")
    manager.remember(unit("relevant", "pink visual palette is preferred"), context)

    response = manager.recall("visual palette", context)

    assert response.context.items[0].memory_id
    assert "pink visual palette" in response.context.text


def test_clearly_irrelevant_zero_score_memory_is_not_injected() -> None:
    manager, backend = setup_memory()
    context = AccessContext(user_id="user-a", case_id="case-a")
    backend.forced_results = [
        {
            "content": "visual palette is pink",
            "score": 0.9,
            "metadata": {"scope_type": "case", "scope_id": "case-a", "memory_id": "m-relevant"},
        },
        {
            "content": "unrelated satellite launch schedule",
            "score": 0.0,
            "metadata": {"scope_type": "case", "scope_id": "case-a", "memory_id": "m-irrelevant"},
        },
    ]

    response = manager.recall("visual palette", context)

    assert [item.memory_id for item in response.context.items] == ["m-relevant"]
    assert "satellite" not in response.context.text


def test_other_user_memory_is_not_recalled() -> None:
    manager, _backend = setup_memory()
    manager.remember(unit("u1", "user-a private codename"), AccessContext(user_id="user-a"), scope_type=ScopeType.USER)
    manager.remember(unit("u2", "user-b private codename"), AccessContext(user_id="user-b"), scope_type=ScopeType.USER)

    response = manager.recall("private codename", AccessContext(user_id="user-a"))

    assert all("user-b" not in item.content for item in response.context.items)
    assert all(item.scope_id == "user-a" for item in response.context.items)


def test_other_case_memory_is_not_recalled() -> None:
    manager, _backend = setup_memory()
    manager.remember(unit("c1", "case-alpha restricted detail"), AccessContext(user_id="user-a", case_id="case-alpha"))
    manager.remember(unit("c2", "case-beta restricted detail"), AccessContext(user_id="user-a", case_id="case-beta"))

    response = manager.recall("restricted detail", AccessContext(user_id="user-a", case_id="case-alpha"))

    assert all("case-beta" not in item.content for item in response.context.items)
    assert all(item.scope_id in {"user-a", "case-alpha"} for item in response.context.items)


def test_other_task_memory_is_not_recalled() -> None:
    manager, _backend = setup_memory()
    manager.remember(
        unit("t1", "task-one restricted handoff"),
        AccessContext(user_id="user-a", case_id="case-a", task_id="task-one"),
        scope_type=ScopeType.TASK,
        memory_type=MemoryType.EVENT,
    )
    manager.remember(
        unit("t2", "task-two restricted handoff"),
        AccessContext(user_id="user-a", case_id="case-a", task_id="task-two"),
        scope_type=ScopeType.TASK,
        memory_type=MemoryType.EVENT,
    )

    response = manager.recall(
        "restricted handoff",
        AccessContext(user_id="user-a", case_id="case-a", task_id="task-one"),
    )

    assert all("task-two" not in item.content for item in response.context.items)
    assert all(item.scope_id in {"task-one"} for item in response.context.items)


def test_duplicate_memory_is_idempotent_locally_and_deduplicated_in_context() -> None:
    manager, _backend = setup_memory()
    context = AccessContext(user_id="user-a", case_id="case-a")
    same_unit = unit("duplicate", "same evidence repeated")

    first = manager.remember(same_unit, context)
    second = manager.remember(same_unit, context)
    response = manager.recall("same evidence", context)

    assert first.memory.id == second.memory.id
    assert len(manager.store.list()) == 1
    assert len(response.context.items) == 1


def test_conflicting_information_requires_explicit_supersession() -> None:
    manager, _backend = setup_memory()
    context = AccessContext(user_id="user-a", case_id="case-a")
    old = manager.remember(unit("old-risk", "risk level amber"), context)
    new = manager.remember(
        unit("new-risk", "risk level red"), context, supersedes=[old.memory.id]
    )

    response = manager.recall("risk level", context)

    assert manager.store.get_memory(old.memory.id).lifecycle is MemoryLifecycle.SUPERSEDED
    assert [item.memory_id for item in response.results] == [new.memory.id]
    assert "amber" not in response.context.text
    assert "red" in response.context.text


def test_updated_information_is_recalled_after_old_version_is_replaced() -> None:
    manager, _backend = setup_memory()
    context = AccessContext(user_id="user-a", case_id="case-a")
    original = manager.remember(unit("v1", "review deadline is Monday"), context)
    updated = manager.remember(
        unit("v2", "review deadline is Friday"), context, supersedes=[original.memory.id]
    )

    response = manager.recall("review deadline", context)

    assert response.results[0].memory_id == updated.memory.id
    assert "Friday" in response.context.text
    assert "Monday" not in response.context.text


def test_stale_provider_memory_is_rejected_even_without_local_store_row() -> None:
    manager, backend = setup_memory()
    backend.forced_results = [{
        "content": "stale case conclusion",
        "score": 1.0,
        "metadata": {
            "scope_type": "case",
            "scope_id": "case-a",
            "expires_at": "2000-01-01T00:00:00+00:00",
            "memory_id": "provider-stale",
        },
    }]

    response = manager.recall("stale conclusion", AccessContext(user_id="user-a", case_id="case-a"))

    assert response.results == ()


def test_memory_outage_fails_closed_without_local_write_or_sensitive_telemetry() -> None:
    backend = RecordingBackend()
    observed: list[tuple[str, dict]] = []
    manager = MemoryManager(backend, operation_observer=lambda name, payload: observed.append((name, dict(payload))))
    context = AccessContext(user_id="user-a", case_id="case-a")
    backend.fail_remember = True

    with pytest.raises(RuntimeError, match="provider unavailable"):
        manager.remember(unit("secret", "sensitive private detail"), context)
    assert manager.store.list() == []

    backend.fail_remember = False
    backend.fail_recall = True
    with pytest.raises(RuntimeError, match="provider unavailable"):
        manager.recall("sensitive private detail", context)

    serialized = repr(observed)
    assert "sensitive private detail" not in serialized
    assert "secret" not in serialized


def test_empty_memory_returns_empty_context() -> None:
    manager, _backend = setup_memory()

    response = manager.recall("anything", AccessContext(user_id="user-a"))

    assert response.results == ()
    assert response.context.items == ()
    assert response.context.text == ""


def test_large_memory_result_is_bounded_but_keeps_provenance() -> None:
    manager, backend = setup_memory()
    content = "large evidence " + ("record " * 2000)
    backend.forced_results = [{
        "content": content,
        "score": 1.0,
        "metadata": {
            "scope_type": "case",
            "scope_id": "case-a",
            "memory_id": "large-memory",
            "source_reference": "report://large#page=1",
            "provenance": {"pipeline": "test-extractor", "page": 1},
        },
    }]

    response = manager.recall(
        "large evidence", AccessContext(user_id="user-a", case_id="case-a"), token_budget=32
    )

    assert response.context.estimated_tokens <= 32
    assert response.context.items[0].memory_id == "large-memory"
    assert response.context.items[0].source_reference == "report://large#page=1"
    assert response.context.items[0].provenance["pipeline"] == "test-extractor"


def test_recalled_memory_preserves_provenance_for_audit() -> None:
    manager, _backend = setup_memory()
    context = AccessContext(user_id="user-a", case_id="case-a")
    manager.remember(
        unit(
            "provenance",
            "provenance evidence finding",
            source_type=SourceType.PDF,
            reference="report.pdf#page=7",
            provenance={"pipeline": "pdf-extractor", "page": 7, "run_id": "run-42"},
        ),
        context,
    )

    response = manager.recall("provenance evidence", context)
    item = response.context.items[0]

    assert item.source_reference == "report.pdf#page=7"
    assert item.provenance["pipeline"] == "pdf-extractor"
    assert item.provenance["page"] == 7
    assert item.provenance["run_id"] == "run-42"
    assert item.memory_id == response.results[0].memory_id
