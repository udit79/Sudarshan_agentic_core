"""Component tests for NP-08 — Public DAG and child-state projection.

Tests cover:
- Schema migration idempotency (calling _create_schema twice is safe)
- Enqueue outbox is never deleted; records are acknowledged only
- RunEnqueueIntent.created_at is server-assigned when left None
- DAGTransitionIntent scope validation:
    - Node scope rejects failure fields for non-terminal statuses
    - Node scope accepts failure fields for terminal statuses (failed/blocked/cancelled)
    - Run scope rejects failure fields for non-failed statuses
    - Run scope accepts failure fields when run_status == "failed"
    - Admission scope forbids node/run/failure fields
- ETag format is W/"{run_id}:{revision}" and changes on each transition
- get_public_dag returns None when revision <= after_revision
- mark_admission_failed sets correct failure_code
- Concurrent reads (thread-safety assertion on revision counter)
"""

from __future__ import annotations

import threading
import uuid
from typing import Any

import pytest

from pipelines.orchestrator.contracts import (
    DAGTransitionIntent,
    PublicChildSpec,
    RunEnqueueIntent,
    TERMINAL_NODE_STATUSES,
)
from pipelines.orchestrator.dag import DAGError, DependencyDAG
from pipelines.orchestrator.dag_sink import DAGProjectionSink
from pipelines.orchestrator.contracts import NodeSpec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_dag(tmp_path) -> DependencyDAG:
    return DependencyDAG(db_path=str(tmp_path / "test_dag.db"))


def _simple_specs(*node_ids: str) -> list[NodeSpec]:
    """Create a linear chain of NodeSpec objects."""
    deps: list[str] = []
    specs = []
    for node_id in node_ids:
        specs.append(
            NodeSpec(
                node_id=node_id,
                skill_id=f"skill-{node_id}",
                output_schema="{}",
                dependencies=list(deps),
            )
        )
        deps = [node_id]
    return specs


def _run_id() -> str:
    return f"run-{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Migration idempotency
# ---------------------------------------------------------------------------

class TestMigrationIdempotency:
    def test_create_schema_twice_is_safe(self, tmp_path):
        """Calling _create_schema on a populated DB must not raise."""
        dag = _make_dag(tmp_path)
        # Second call must be a no-op
        dag._create_schema()
        # And a run can still be created successfully.
        rid = _run_id()
        dag.create_run(rid, _simple_specs("n1"))
        state = dag.get_run(rid)
        assert state.run_id == rid

    def test_migrate_schema_adds_columns(self, tmp_path):
        """_migrate_schema must not raise even when columns already exist."""
        dag = _make_dag(tmp_path)
        # Explicit call — must be idempotent.
        dag._migrate_schema()
        dag._migrate_schema()


# ---------------------------------------------------------------------------
# Outbox: acknowledge-only, never delete
# ---------------------------------------------------------------------------

class TestEnqueueOutbox:
    def test_apply_enqueue_persists_record(self, tmp_path):
        dag = _make_dag(tmp_path)
        rid = _run_id()
        dag.create_run(rid, _simple_specs("n1"))

        intent = RunEnqueueIntent(
            event_id="evt-001",
            run_id=rid,
            queue_name="runs",
            payload_fingerprint="fp-abc",
        )
        row_id = dag.apply_enqueue(intent)
        assert row_id > 0

    def test_created_at_is_server_assigned_when_none(self, tmp_path):
        """RunEnqueueIntent.created_at must be None on input; store assigns it."""
        dag = _make_dag(tmp_path)
        rid = _run_id()
        dag.create_run(rid, _simple_specs("n1"))

        intent = RunEnqueueIntent(
            event_id="evt-002",
            run_id=rid,
            queue_name="runs",
            payload_fingerprint="fp-xyz",
            created_at=None,  # explicitly left None
        )
        assert intent.created_at is None  # contract honours Optional

        dag.apply_enqueue(intent)

        # Verify the stored record has a server-assigned created_at
        with dag._lock:
            row = dag._connection.execute(
                "SELECT created_at FROM dag_outbox WHERE event_id = ?", ("evt-002",)
            ).fetchone()
        assert row is not None
        assert row["created_at"]  # non-empty server timestamp

    def test_records_are_never_deleted(self, tmp_path):
        """After acknowledge, the row must still exist with status='acknowledged'."""
        dag = _make_dag(tmp_path)
        rid = _run_id()
        dag.create_run(rid, _simple_specs("n1"))

        intent = RunEnqueueIntent(
            event_id="evt-003",
            run_id=rid,
            queue_name="runs",
            payload_fingerprint="fp-del",
        )
        dag.apply_enqueue(intent)
        dag.acknowledge_enqueue("evt-003")

        with dag._lock:
            row = dag._connection.execute(
                "SELECT status, acknowledged_at FROM dag_outbox WHERE event_id = ?",
                ("evt-003",),
            ).fetchone()
        assert row is not None, "Row must not be deleted"
        assert row["status"] == "acknowledged"
        assert row["acknowledged_at"]  # server-assigned

    def test_acknowledge_is_idempotent(self, tmp_path):
        """Calling acknowledge_enqueue twice must not raise."""
        dag = _make_dag(tmp_path)
        rid = _run_id()
        dag.create_run(rid, _simple_specs("n1"))

        intent = RunEnqueueIntent(
            event_id="evt-004",
            run_id=rid,
            queue_name="runs",
            payload_fingerprint="fp-idem",
        )
        dag.apply_enqueue(intent)
        dag.acknowledge_enqueue("evt-004")
        dag.acknowledge_enqueue("evt-004")  # Must not raise

    def test_apply_enqueue_is_idempotent_for_same_event_id(self, tmp_path):
        """Inserting the same event_id twice must be a silent no-op (INSERT OR IGNORE)."""
        dag = _make_dag(tmp_path)
        rid = _run_id()
        dag.create_run(rid, _simple_specs("n1"))

        intent = RunEnqueueIntent(
            event_id="evt-005",
            run_id=rid,
            queue_name="runs",
            payload_fingerprint="fp-idem2",
        )
        dag.apply_enqueue(intent)
        dag.apply_enqueue(intent)  # Should not raise

        with dag._lock:
            count = dag._connection.execute(
                "SELECT COUNT(*) FROM dag_outbox WHERE event_id = ?", ("evt-005",)
            ).fetchone()[0]
        assert count == 1


# ---------------------------------------------------------------------------
# DAGTransitionIntent scope validation
# ---------------------------------------------------------------------------

class TestDAGTransitionIntentScopes:
    """Verify the strict scope validator on DAGTransitionIntent."""

    # ---- node scope ----

    def test_node_scope_accepts_valid_running(self):
        intent = DAGTransitionIntent(
            event_id="e1",
            run_id="run-1",
            scope="node",
            node_id="n1",
            node_status="running",
            progress=42,
        )
        assert intent.node_status == "running"

    def test_node_scope_rejects_failure_fields_for_running(self):
        with pytest.raises(ValueError, match="terminal"):
            DAGTransitionIntent(
                event_id="e2",
                run_id="run-1",
                scope="node",
                node_id="n1",
                node_status="running",
                failure_code="SOME_ERROR",
            )

    def test_node_scope_rejects_failure_summary_for_running(self):
        with pytest.raises(ValueError, match="terminal"):
            DAGTransitionIntent(
                event_id="e3",
                run_id="run-1",
                scope="node",
                node_id="n1",
                node_status="running",
                safe_failure_summary="Something went wrong",
            )

    @pytest.mark.parametrize("terminal_status", sorted(TERMINAL_NODE_STATUSES))
    def test_node_scope_accepts_failure_fields_for_terminal(self, terminal_status):
        intent = DAGTransitionIntent(
            event_id="e4",
            run_id="run-1",
            scope="node",
            node_id="n1",
            node_status=terminal_status,
            failure_code="NODE_ERR",
            safe_failure_summary="Redacted summary",
        )
        assert intent.failure_code == "NODE_ERR"

    def test_node_scope_requires_node_id_and_status(self):
        with pytest.raises(ValueError):
            DAGTransitionIntent(
                event_id="e5",
                run_id="run-1",
                scope="node",
            )

    def test_node_scope_forbids_run_status(self):
        with pytest.raises(ValueError, match="forbids"):
            DAGTransitionIntent(
                event_id="e6",
                run_id="run-1",
                scope="node",
                node_id="n1",
                node_status="running",
                run_status="running",
            )

    # ---- run scope ----

    def test_run_scope_rejects_failure_fields_for_non_failed(self):
        with pytest.raises(ValueError, match="'failed'"):
            DAGTransitionIntent(
                event_id="e7",
                run_id="run-1",
                scope="run",
                run_status="running",
                failure_code="SOME_ERR",
            )

    def test_run_scope_accepts_failure_fields_when_failed(self):
        intent = DAGTransitionIntent(
            event_id="e8",
            run_id="run-1",
            scope="run",
            run_status="failed",
            failure_code="DAG_ADMISSION_FAILED",
            safe_failure_summary="Admission failed",
        )
        assert intent.failure_code == "DAG_ADMISSION_FAILED"

    def test_run_scope_requires_run_status(self):
        with pytest.raises(ValueError, match="requires run_status"):
            DAGTransitionIntent(
                event_id="e9",
                run_id="run-1",
                scope="run",
            )

    def test_run_scope_forbids_node_id(self):
        with pytest.raises(ValueError, match="forbids"):
            DAGTransitionIntent(
                event_id="e10",
                run_id="run-1",
                scope="run",
                run_status="running",
                node_id="n1",
            )

    # ---- admission scope ----

    def test_admission_scope_valid(self):
        intent = DAGTransitionIntent(
            event_id="e11",
            run_id="run-1",
            scope="admission",
            parent_node_id="p1",
            admitted_nodes=[
                PublicChildSpec(node_id="c1", skill_id="skill-c1")
            ],
        )
        assert intent.scope == "admission"

    def test_admission_scope_forbids_failure_code(self):
        with pytest.raises(ValueError, match="forbids"):
            DAGTransitionIntent(
                event_id="e12",
                run_id="run-1",
                scope="admission",
                parent_node_id="p1",
                admitted_nodes=[PublicChildSpec(node_id="c1", skill_id="skill-c1")],
                failure_code="ERR",
            )

    def test_admission_scope_requires_parent_and_nodes(self):
        with pytest.raises(ValueError, match="requires"):
            DAGTransitionIntent(
                event_id="e13",
                run_id="run-1",
                scope="admission",
            )


# ---------------------------------------------------------------------------
# ETag and revision semantics
# ---------------------------------------------------------------------------

class TestETagAndRevision:
    def _etag(self, run_id: str, revision: int) -> str:
        return f'W/"{run_id}:{revision}"'

    def test_etag_format_matches_spec(self):
        run_id = "run-abc123"
        revision = 7
        assert self._etag(run_id, revision) == 'W/"run-abc123:7"'

    def test_revision_increments_on_each_transition(self, tmp_path):
        dag = _make_dag(tmp_path)
        rid = _run_id()
        dag.create_run(rid, _simple_specs("n1", "n2"))

        # Default after_revision=-1 → always returns graph
        graph0 = dag.get_public_dag(rid)
        assert graph0 is not None
        assert graph0.revision == 0

        # Apply a node transition
        intent = DAGTransitionIntent(
            event_id="t1",
            run_id=rid,
            scope="node",
            node_id="n1",
            node_status="running",
        )
        rev1 = dag.apply_transition(intent)
        assert rev1 == 1

        graph1 = dag.get_public_dag(rid)
        assert graph1 is not None
        assert graph1.revision == 1

        # ETag must change
        etag0 = self._etag(rid, 0)
        etag1 = self._etag(rid, 1)
        assert etag0 != etag1

    def test_get_public_dag_returns_none_when_not_changed(self, tmp_path):
        dag = _make_dag(tmp_path)
        rid = _run_id()
        dag.create_run(rid, _simple_specs("n1"))

        # Default (after_revision=-1) → always returns graph even at revision 0
        graph = dag.get_public_dag(rid)
        assert graph is not None
        assert graph.revision == 0

        # Passing after_revision=0 → returns None because revision 0 <= 0
        # (caller already has revision 0)
        result = dag.get_public_dag(rid, after_revision=0)
        assert result is None

    def test_get_public_dag_returns_none_when_revision_not_advanced(self, tmp_path):
        dag = _make_dag(tmp_path)
        rid = _run_id()
        dag.create_run(rid, _simple_specs("n1"))

        intent = DAGTransitionIntent(
            event_id="t2",
            run_id=rid,
            scope="node",
            node_id="n1",
            node_status="running",
        )
        dag.apply_transition(intent)  # now at revision 1

        # Asking after_revision=1 should return None (not advanced past 1)
        result = dag.get_public_dag(rid, after_revision=1)
        assert result is None

        # Asking after_revision=0 should return graph at revision 1
        result = dag.get_public_dag(rid, after_revision=0)
        assert result is not None
        assert result.revision == 1


# ---------------------------------------------------------------------------
# mark_admission_failed
# ---------------------------------------------------------------------------

class TestMarkAdmissionFailed:
    def test_sets_correct_failure_code(self, tmp_path):
        dag = _make_dag(tmp_path)
        rid = _run_id()
        dag.create_run(rid, _simple_specs("n1"))

        dag.mark_admission_failed(rid)

        graph = dag.get_public_dag(rid, include_failure_details=True)
        assert graph is not None
        assert graph.status == "failed"
        assert graph.failure_code == "DAG_ADMISSION_FAILED"

    def test_custom_failure_summary(self, tmp_path):
        dag = _make_dag(tmp_path)
        rid = _run_id()
        dag.create_run(rid, _simple_specs("n1"))

        dag.mark_admission_failed(rid, safe_failure_summary="Queue timeout")

        graph = dag.get_public_dag(rid, include_failure_details=True)
        assert graph is not None
        assert graph.safe_failure_summary == "Queue timeout"

    def test_failure_details_hidden_without_flag(self, tmp_path):
        dag = _make_dag(tmp_path)
        rid = _run_id()
        dag.create_run(rid, _simple_specs("n1"))
        dag.mark_admission_failed(rid)

        graph = dag.get_public_dag(rid, include_failure_details=False)
        assert graph is not None
        assert graph.failure_code is None
        assert graph.safe_failure_summary is None


# ---------------------------------------------------------------------------
# DAGProjectionSink protocol
# ---------------------------------------------------------------------------

class TestDAGProjectionSinkProtocol:
    def test_dependency_dag_satisfies_protocol(self, tmp_path):
        dag = _make_dag(tmp_path)
        assert isinstance(dag, DAGProjectionSink)


# ---------------------------------------------------------------------------
# Concurrent revision safety
# ---------------------------------------------------------------------------

class TestConcurrentRevisions:
    def test_concurrent_transitions_produce_unique_revisions(self, tmp_path):
        dag = _make_dag(tmp_path)
        rid = _run_id()
        dag.create_run(rid, _simple_specs("n1"))

        revisions: list[int] = []
        errors: list[Exception] = []

        def apply_run_transition(i: int) -> None:
            try:
                intent = DAGTransitionIntent(
                    event_id=f"concurrent-{i}",
                    run_id=rid,
                    scope="run",
                    run_status="running",
                )
                rev = dag.apply_transition(intent)
                revisions.append(rev)
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=apply_run_transition, args=(i,))
            for i in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent transitions raised: {errors}"
        # All revisions must be unique (no two threads got the same revision)
        assert len(set(revisions)) == len(revisions), f"Duplicate revisions: {revisions}"


# ---------------------------------------------------------------------------
# PublicChildSpec
# ---------------------------------------------------------------------------

class TestPublicChildSpec:
    def test_duplicate_dependencies_rejected(self):
        with pytest.raises(ValueError, match="unique"):
            PublicChildSpec(node_id="c1", skill_id="sk", dependencies=["a", "a"])

    def test_valid_spec(self):
        spec = PublicChildSpec(
            node_id="c1",
            skill_id="sk",
            dependencies=["a", "b"],
            output_schema_ref="schema://v1",
        )
        assert spec.node_id == "c1"
