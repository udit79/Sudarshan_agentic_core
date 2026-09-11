"""Persisted dependency DAG for typed skill and rendering nodes.

This is the graph-admission layer for T11. It does not execute providers or
threads; it persists node state, identifies safe parallel work, blocks failed
descendants, and bounds repair loops. A worker or the durable scheduler can
claim the returned nodes and call ``complete_node`` when execution finishes.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Iterable, Literal, Mapping

from api.control_plane import ControlPlane, ControlPlaneConflict, LeaseToken, StaleLeaseError, new_worker_id
from pipelines.orchestrator.contracts import NodeSpec


NodeStatus = Literal[
    "pending",
    "ready",
    "running",
    "succeeded",
    "waiting",
    "failed",
    "blocked",
    "cancelled",
]


class DAGError(ValueError):
    """A malformed graph or invalid state transition."""


@dataclass(frozen=True, slots=True)
class DAGNodeState:
    run_id: str
    node_id: str
    skill_id: str
    status: NodeStatus
    dependencies: tuple[str, ...]
    repair_attempts: int = 0
    max_repairs: int = 0
    failure_code: str | None = None
    failure_reason: str | None = None
    output_ref: str | None = None


@dataclass(frozen=True, slots=True)
class DAGRunState:
    run_id: str
    status: str
    node_count: int
    completed_count: int
    failed_count: int
    created_at: str
    updated_at: str


EventSink = Callable[[str, Mapping[str, Any]], None]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DependencyDAG:
    """Thread-safe SQLite-backed graph admission and node state store."""

    def __init__(
        self,
        db_path: str | Path = "artifacts/.state/dag.db",
        *,
        event_sink: EventSink | None = None,
        control_plane: ControlPlane | None = None,
        lease_ms: int = 900_000,
    ) -> None:
        if lease_ms < 1:
            raise DAGError("lease_ms must be positive")
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = RLock()
        self._event_sink = event_sink
        self._control_plane = control_plane
        self._lease_seconds = lease_ms / 1000
        self._owner = new_worker_id("dag")
        self._node_leases: dict[tuple[str, str], LeaseToken] = {}
        self._remote_revisions: dict[str, int] = {}
        self._create_schema()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def create_run(self, run_id: str, nodes: Iterable[NodeSpec]) -> DAGRunState:
        if not run_id.strip():
            raise DAGError("run_id must be non-empty")
        specs = tuple(nodes)
        self._validate_specs(specs)
        remote_snapshot = self._read_remote_snapshot(run_id)
        if remote_snapshot is not None:
            self._validate_remote_specs(remote_snapshot, specs)
            self._apply_remote_snapshot(remote_snapshot)
            return self.get_run(run_id)
        now = _now()
        with self._lock, self._connection:
            try:
                self._connection.execute(
                    "INSERT INTO dag_runs(run_id, status, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (run_id, "queued", now, now),
                )
            except sqlite3.IntegrityError as error:
                raise DAGError(f"run '{run_id}' already exists") from error
            for spec in specs:
                self._connection.execute(
                    """INSERT INTO dag_nodes(
                        run_id, node_id, skill_id, spec_json, dependencies_json,
                        status, repair_attempts, max_repairs
                    ) VALUES (?, ?, ?, ?, ?, ?, 0, ?)""",
                    (
                        run_id,
                        spec.node_id,
                        spec.skill_id,
                        json.dumps(spec.model_dump(mode="json"), sort_keys=True),
                        json.dumps(list(spec.dependencies)),
                        "pending",
                        self._max_repairs(spec),
                    ),
                )
            self._refresh_ready_locked(run_id)
            self._update_run_status_locked(run_id)
        if self._control_plane is not None:
            for spec in specs:
                try:
                    self._control_plane.admit(
                        self._resource_key(run_id, spec.node_id),
                        self._spec_hash(spec),
                        {
                            "run_id": run_id,
                            "node_id": spec.node_id,
                            "skill_id": spec.skill_id,
                        },
                        queue="dag-state",
                    )
                except ControlPlaneConflict as error:
                    raise DAGError(f"shared DAG node '{spec.node_id}' was admitted differently") from error
        if self._supports_remote_snapshots():
            with self._lock:
                snapshot = self._snapshot_payload_locked(run_id)
            try:
                revision = self._control_plane.dag_snapshot_put(run_id, snapshot)  # type: ignore[union-attr]
            except ControlPlaneConflict:
                remote_snapshot = self._read_remote_snapshot(run_id)
                if remote_snapshot is None:
                    raise DAGError(f"shared DAG snapshot for '{run_id}' disappeared")
                self._validate_remote_specs(remote_snapshot, specs)
                self._apply_remote_snapshot(remote_snapshot)
                return self.get_run(run_id)
            self._remote_revisions[run_id] = revision
        self._emit("dag.created", run_id, node_count=len(specs))
        return self.get_run(run_id)

    def admit_ready_nodes(self, run_id: str) -> list[DAGNodeState]:
        """Re-evaluate dependencies and return all currently ready nodes."""

        self._sync_remote(run_id)
        with self._lock, self._connection:
            self._require_run_locked(run_id)
            changed = self._refresh_ready_locked(run_id)
            self._update_run_status_locked(run_id)
            rows = self._connection.execute(
                "SELECT * FROM dag_nodes WHERE run_id = ? AND status = 'ready' ORDER BY node_id",
                (run_id,),
            ).fetchall()
            changed_ids = [node.node_id for node in changed]
        self._publish_node_changes(run_id, changed_ids)
        if changed:
            for node in changed:
                self._emit("node.ready", run_id, node_id=node.node_id, skill_id=node.skill_id)
        return [self._node_from_row(row) for row in rows]

    def claim_ready_nodes(self, run_id: str, *, limit: int) -> list[DAGNodeState]:
        """Atomically claim a bounded set of ready nodes for parallel workers."""

        if limit < 1:
            raise DAGError("claim limit must be positive")
        ready = self.admit_ready_nodes(run_id)
        selected = ready[:limit]
        if self._control_plane is not None:
            leased: list[DAGNodeState] = []
            for node in selected:
                lease = self._control_plane.claim(
                    self._resource_key(run_id, node.node_id),
                    owner=self._owner,
                    lease_seconds=self._lease_seconds,
                )
                if lease is not None:
                    leased.append(node)
                    self._node_leases[(run_id, node.node_id)] = lease
            selected = leased
        with self._lock, self._connection:
            before = self._node_payloads_locked(run_id)
            for node in selected:
                self._connection.execute(
                    "UPDATE dag_nodes SET status = 'running' WHERE run_id = ? AND node_id = ? AND status = 'ready'",
                    (run_id, node.node_id),
                )
            self._update_run_status_locked(run_id)
            changed_ids = [
                node_id
                for node_id, payload in self._node_payloads_locked(run_id).items()
                if before.get(node_id) != payload
            ]
        self._publish_node_changes(run_id, changed_ids)
        for node in selected:
            self._emit("node.started", run_id, node_id=node.node_id, skill_id=node.skill_id)
        return [self.get_node(run_id, node.node_id) for node in selected]

    def complete_node(
        self,
        run_id: str,
        node_id: str,
        *,
        status: Literal["succeeded", "waiting", "failed", "cancelled"],
        output_ref: str | None = None,
        failure_code: str | None = None,
        failure_reason: str | None = None,
        repair: bool = False,
    ) -> DAGNodeState:
        """Persist a worker result and advance or block dependent nodes."""

        if status == "succeeded" and (failure_code or failure_reason):
            raise DAGError("successful nodes cannot contain failure details")
        emitted: list[tuple[str, dict[str, Any]]] = []
        self._sync_remote(run_id)
        lease = self._node_leases.get((run_id, node_id))
        with self._lock:
            current = str(self._get_node_row_locked(run_id, node_id)["status"])
            before = self._node_payloads_locked(run_id)
        if current not in {"ready", "running"}:
            raise DAGError(f"node '{node_id}' cannot complete from status '{current}'")
        if self._control_plane is not None:
            if lease is None:
                raise DAGError(f"node '{node_id}' has no active shared lease")
            try:
                if status == "failed" and repair:
                    self._control_plane.schedule_retry(
                        lease,
                        retry_at=time.time(),
                        error=failure_reason or failure_code or "DAG repair requested",
                    )
                else:
                    self._control_plane.transition(
                        lease,
                        status=status,
                        result={
                            "output_ref": output_ref,
                            "failure_code": failure_code,
                            "failure_reason": failure_reason,
                        },
                    )
            except StaleLeaseError as error:
                raise DAGError(f"stale shared lease for node '{node_id}'") from error
        with self._lock, self._connection:
            row = self._get_node_row_locked(run_id, node_id)
            current = str(row["status"])
            if current not in {"ready", "running"}:
                raise DAGError(f"node '{node_id}' cannot complete from status '{current}'")
            if status == "failed" and repair and int(row["repair_attempts"]) < int(row["max_repairs"]):
                next_attempt = int(row["repair_attempts"]) + 1
                self._connection.execute(
                    """UPDATE dag_nodes
                    SET status = 'pending', repair_attempts = ?, failure_code = ?, failure_reason = ?
                    WHERE run_id = ? AND node_id = ?""",
                    (next_attempt, failure_code or "REPAIR_REQUESTED", failure_reason, run_id, node_id),
                )
                emitted.append(("node.repairing", {
                    "node_id": node_id,
                    "skill_id": row["skill_id"],
                    "repair_attempt": next_attempt,
                    "max_repairs": row["max_repairs"],
                }))
            else:
                self._connection.execute(
                    """UPDATE dag_nodes
                    SET status = ?, output_ref = ?, failure_code = ?, failure_reason = ?
                    WHERE run_id = ? AND node_id = ?""",
                    (status, output_ref, failure_code, failure_reason, run_id, node_id),
                )
                event_name = {
                    "succeeded": "node.succeeded",
                    "waiting": "node.waiting",
                    "failed": "node.failed",
                    "cancelled": "node.cancelled",
                }[status]
                emitted.append((event_name, {
                    "node_id": node_id,
                    "skill_id": row["skill_id"],
                    "failure_code": failure_code,
                }))
                if status in {"failed", "cancelled"}:
                    self._block_descendants_locked(run_id, node_id, emitted)
            newly_ready = self._refresh_ready_locked(run_id)
            emitted.extend(("node.ready", {
                "node_id": node.node_id,
                "skill_id": node.skill_id,
            }) for node in newly_ready)
            self._update_run_status_locked(run_id)
            result = self._node_from_row(self._get_node_row_locked(run_id, node_id))
            changed_ids = [
                changed_node_id
                for changed_node_id, payload in self._node_payloads_locked(run_id).items()
                if before.get(changed_node_id) != payload
            ]
        self._publish_node_changes(run_id, changed_ids)
        self._node_leases.pop((run_id, node_id), None)
        for event_name, fields in emitted:
            self._emit(event_name, run_id, **fields)
        return result

    def get_node(self, run_id: str, node_id: str) -> DAGNodeState:
        self._sync_remote(run_id)
        with self._lock:
            return self._node_from_row(self._get_node_row_locked(run_id, node_id))

    def list_nodes(self, run_id: str) -> list[DAGNodeState]:
        self._sync_remote(run_id)
        with self._lock:
            self._require_run_locked(run_id)
            rows = self._connection.execute(
                "SELECT * FROM dag_nodes WHERE run_id = ? ORDER BY node_id", (run_id,)
            ).fetchall()
        return [self._node_from_row(row) for row in rows]

    def get_run(self, run_id: str) -> DAGRunState:
        self._sync_remote(run_id)
        with self._lock:
            row = self._connection.execute(
                """SELECT r.*, COUNT(n.node_id) AS node_count,
                    SUM(CASE WHEN n.status IN ('succeeded', 'failed', 'blocked', 'cancelled') THEN 1 ELSE 0 END) AS completed_count,
                    SUM(CASE WHEN n.status IN ('failed', 'blocked') THEN 1 ELSE 0 END) AS failed_count
                    FROM dag_runs r LEFT JOIN dag_nodes n ON n.run_id = r.run_id
                    WHERE r.run_id = ? GROUP BY r.run_id""",
                (run_id,),
            ).fetchone()
            if row is None:
                raise DAGError(f"run '{run_id}' does not exist")
            return DAGRunState(
                run_id=row["run_id"],
                status=row["status"],
                node_count=int(row["node_count"] or 0),
                completed_count=int(row["completed_count"] or 0),
                failed_count=int(row["failed_count"] or 0),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS dag_runs (
                    run_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS dag_nodes (
                    run_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    skill_id TEXT NOT NULL,
                    spec_json TEXT NOT NULL,
                    dependencies_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    repair_attempts INTEGER NOT NULL DEFAULT 0,
                    max_repairs INTEGER NOT NULL DEFAULT 0,
                    failure_code TEXT,
                    failure_reason TEXT,
                    output_ref TEXT,
                    PRIMARY KEY (run_id, node_id),
                    FOREIGN KEY (run_id) REFERENCES dag_runs(run_id)
                );
                CREATE INDEX IF NOT EXISTS idx_dag_nodes_ready ON dag_nodes(run_id, status);
                """
            )

    def _supports_remote_snapshots(self) -> bool:
        return self._control_plane is not None and all(
            callable(getattr(self._control_plane, name, None))
            for name in ("dag_snapshot", "dag_snapshot_put", "dag_snapshot_patch")
        )

    def _read_remote_snapshot(self, run_id: str) -> dict[str, Any] | None:
        if not self._supports_remote_snapshots():
            return None
        snapshot = self._control_plane.dag_snapshot(run_id)  # type: ignore[union-attr]
        return dict(snapshot) if snapshot is not None else None

    def _sync_remote(self, run_id: str) -> None:
        snapshot = self._read_remote_snapshot(run_id)
        if snapshot is None:
            return
        revision = int(snapshot.get("revision", 0))
        if revision <= self._remote_revisions.get(run_id, 0):
            return
        self._apply_remote_snapshot(snapshot)

    def _apply_remote_snapshot(self, snapshot: Mapping[str, Any]) -> None:
        run_id = str(snapshot.get("run_id", "")).strip()
        nodes = snapshot.get("nodes")
        if not run_id or not isinstance(nodes, Mapping):
            raise DAGError("shared DAG snapshot is invalid")
        with self._lock, self._connection:
            run_row = self._connection.execute(
                "SELECT run_id FROM dag_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            created_at = str(snapshot.get("created_at") or _now())
            updated_at = str(snapshot.get("updated_at") or _now())
            if run_row is None:
                self._connection.execute(
                    "INSERT INTO dag_runs(run_id, status, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (run_id, str(snapshot.get("status") or "queued"), created_at, updated_at),
                )
            else:
                self._connection.execute(
                    "UPDATE dag_runs SET status = ?, updated_at = ? WHERE run_id = ?",
                    (str(snapshot.get("status") or "queued"), updated_at, run_id),
                )
            for node_id, raw_node in nodes.items():
                if not isinstance(raw_node, Mapping):
                    raise DAGError("shared DAG node snapshot is invalid")
                node = dict(raw_node)
                dependencies = list(node.get("dependencies") or [])
                spec_json = str(node.get("spec_json") or json.dumps({
                    "node_id": str(node_id),
                    "skill_id": str(node.get("skill_id", "")),
                    "dependencies": dependencies,
                }, sort_keys=True))
                values = (
                    run_id,
                    str(node_id),
                    str(node.get("skill_id", "")),
                    spec_json,
                    json.dumps(dependencies),
                    str(node.get("status", "pending")),
                    int(node.get("repair_attempts", 0)),
                    int(node.get("max_repairs", 0)),
                    node.get("failure_code"),
                    node.get("failure_reason"),
                    node.get("output_ref"),
                )
                existing = self._connection.execute(
                    "SELECT 1 FROM dag_nodes WHERE run_id = ? AND node_id = ?",
                    (run_id, str(node_id)),
                ).fetchone()
                if existing is None:
                    self._connection.execute(
                        """INSERT INTO dag_nodes(
                        run_id, node_id, skill_id, spec_json, dependencies_json,
                        status, repair_attempts, max_repairs, failure_code,
                        failure_reason, output_ref
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        values,
                    )
                else:
                    self._connection.execute(
                        """UPDATE dag_nodes SET skill_id = ?, spec_json = ?,
                        dependencies_json = ?, status = ?, repair_attempts = ?,
                        max_repairs = ?, failure_code = ?, failure_reason = ?,
                        output_ref = ? WHERE run_id = ? AND node_id = ?""",
                        (
                            values[2], values[3], values[4], values[5], values[6],
                            values[7], values[8], values[9], values[10], values[0], values[1],
                        ),
                    )
            self._update_run_status_locked(run_id)
        self._remote_revisions[run_id] = int(snapshot.get("revision", 0))

    def _snapshot_payload_locked(self, run_id: str) -> dict[str, Any]:
        run = self._connection.execute(
            "SELECT * FROM dag_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if run is None:
            raise DAGError(f"run '{run_id}' does not exist")
        return {
            "run_id": run_id,
            "status": str(run["status"]),
            "created_at": str(run["created_at"]),
            "updated_at": str(run["updated_at"]),
            "nodes": self._node_payloads_locked(run_id),
        }

    def _node_payloads_locked(self, run_id: str) -> dict[str, dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT * FROM dag_nodes WHERE run_id = ? ORDER BY node_id", (run_id,)
        ).fetchall()
        return {str(row["node_id"]): self._node_payload_from_row(row) for row in rows}

    @staticmethod
    def _node_payload_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "run_id": str(row["run_id"]),
            "node_id": str(row["node_id"]),
            "skill_id": str(row["skill_id"]),
            "spec_json": str(row["spec_json"]),
            "dependencies": list(json.loads(row["dependencies_json"])),
            "status": str(row["status"]),
            "repair_attempts": int(row["repair_attempts"]),
            "max_repairs": int(row["max_repairs"]),
            "failure_code": row["failure_code"],
            "failure_reason": row["failure_reason"],
            "output_ref": row["output_ref"],
        }

    def _publish_node_changes(self, run_id: str, node_ids: Iterable[str]) -> None:
        if not self._supports_remote_snapshots():
            return
        selected = {str(node_id) for node_id in node_ids}
        if not selected:
            return
        with self._lock:
            payloads = self._node_payloads_locked(run_id)
        changes = {node_id: payloads[node_id] for node_id in selected if node_id in payloads}
        if not changes:
            return
        revision = self._control_plane.dag_snapshot_patch(run_id, changes)  # type: ignore[union-attr]
        self._remote_revisions[run_id] = revision

    @staticmethod
    def _validate_remote_specs(snapshot: Mapping[str, Any], specs: tuple[NodeSpec, ...]) -> None:
        nodes = snapshot.get("nodes")
        if not isinstance(nodes, Mapping) or set(nodes) != {spec.node_id for spec in specs}:
            raise DAGError("shared DAG run was admitted with a different node set")
        for spec in specs:
            remote = nodes.get(spec.node_id)
            if not isinstance(remote, Mapping):
                raise DAGError("shared DAG node snapshot is invalid")
            if str(remote.get("skill_id")) != spec.skill_id:
                raise DAGError(f"shared DAG node '{spec.node_id}' was admitted differently")
            if tuple(remote.get("dependencies") or ()) != tuple(spec.dependencies):
                raise DAGError(f"shared DAG node '{spec.node_id}' dependencies differ")

    @staticmethod
    def _validate_specs(specs: tuple[NodeSpec, ...]) -> None:
        identifiers = [spec.node_id for spec in specs]
        if len(set(identifiers)) != len(identifiers):
            raise DAGError("node IDs must be unique")
        known = set(identifiers)
        for spec in specs:
            unknown = set(spec.dependencies) - known
            if unknown:
                raise DAGError(f"node '{spec.node_id}' depends on unknown nodes: {', '.join(sorted(unknown))}")
        edges = {spec.node_id: set(spec.dependencies) for spec in specs}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise DAGError("node dependencies contain a cycle")
            if node_id in visited:
                return
            visiting.add(node_id)
            for dependency in edges[node_id]:
                visit(dependency)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in edges:
            visit(node_id)

    @staticmethod
    def _max_repairs(spec: NodeSpec) -> int:
        raw = spec.retry_policy.get("max_repairs", 0)
        try:
            value = int(raw)
        except (TypeError, ValueError) as error:
            raise DAGError(f"node '{spec.node_id}' max_repairs must be an integer") from error
        if value < 0 or value > 5:
            raise DAGError(f"node '{spec.node_id}' max_repairs must be between 0 and 5")
        return value

    @staticmethod
    def _resource_key(run_id: str, node_id: str) -> str:
        return f"dag:{run_id}:{node_id}"

    @staticmethod
    def _spec_hash(spec: NodeSpec) -> str:
        import hashlib

        encoded = json.dumps(spec.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _refresh_ready_locked(self, run_id: str) -> list[DAGNodeState]:
        changed: list[DAGNodeState] = []
        rows = self._connection.execute(
            "SELECT * FROM dag_nodes WHERE run_id = ? ORDER BY node_id", (run_id,)
        ).fetchall()
        statuses = {row["node_id"]: row["status"] for row in rows}
        for row in rows:
            if row["status"] != "pending":
                continue
            dependencies = json.loads(row["dependencies_json"])
            dependency_statuses = [statuses[dependency] for dependency in dependencies]
            if any(status in {"failed", "blocked", "cancelled"} for status in dependency_statuses):
                self._connection.execute(
                    "UPDATE dag_nodes SET status = 'blocked', failure_code = ?, failure_reason = ? WHERE run_id = ? AND node_id = ?",
                    ("DEPENDENCY_FAILED", "A required dependency did not succeed", run_id, row["node_id"]),
                )
                changed.append(self._node_from_row(self._get_node_row_locked(run_id, row["node_id"])))
            elif all(status == "succeeded" for status in dependency_statuses):
                self._connection.execute(
                    "UPDATE dag_nodes SET status = 'ready', failure_code = NULL, failure_reason = NULL WHERE run_id = ? AND node_id = ?",
                    (run_id, row["node_id"]),
                )
                changed.append(self._node_from_row(self._get_node_row_locked(run_id, row["node_id"])))
        return changed

    def _block_descendants_locked(self, run_id: str, node_id: str, emitted: list[tuple[str, dict[str, Any]]]) -> None:
        rows = self._connection.execute(
            "SELECT * FROM dag_nodes WHERE run_id = ? AND status IN ('pending', 'ready')", (run_id,)
        ).fetchall()
        blocked = {node_id}
        changed = True
        while changed:
            changed = False
            for row in rows:
                if row["node_id"] in blocked or row["status"] not in {"pending", "ready"}:
                    continue
                dependencies = set(json.loads(row["dependencies_json"]))
                if dependencies & blocked:
                    self._connection.execute(
                        "UPDATE dag_nodes SET status = 'blocked', failure_code = ?, failure_reason = ? WHERE run_id = ? AND node_id = ?",
                        ("DEPENDENCY_FAILED", f"Dependency '{node_id}' failed", run_id, row["node_id"]),
                    )
                    blocked.add(row["node_id"])
                    emitted.append(("node.blocked", {
                        "node_id": row["node_id"],
                        "skill_id": row["skill_id"],
                        "failure_code": "DEPENDENCY_FAILED",
                    }))
                    changed = True

    def _update_run_status_locked(self, run_id: str) -> None:
        rows = self._connection.execute(
            "SELECT status FROM dag_nodes WHERE run_id = ?", (run_id,)
        ).fetchall()
        statuses = [row["status"] for row in rows]
        if not statuses:
            status = "succeeded"
        elif any(item == "waiting" for item in statuses):
            status = "waiting"
        elif any(item in {"failed", "blocked"} for item in statuses):
            status = "failed"
        elif all(item in {"succeeded", "cancelled"} for item in statuses):
            status = "succeeded" if all(item == "succeeded" for item in statuses) else "cancelled"
        elif any(item == "running" for item in statuses):
            status = "running"
        else:
            status = "queued"
        self._connection.execute(
            "UPDATE dag_runs SET status = ?, updated_at = ? WHERE run_id = ?",
            (status, _now(), run_id),
        )

    def _require_run_locked(self, run_id: str) -> None:
        row = self._connection.execute("SELECT 1 FROM dag_runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise DAGError(f"run '{run_id}' does not exist")

    def _get_node_row_locked(self, run_id: str, node_id: str) -> sqlite3.Row:
        row = self._connection.execute(
            "SELECT * FROM dag_nodes WHERE run_id = ? AND node_id = ?", (run_id, node_id)
        ).fetchone()
        if row is None:
            raise DAGError(f"node '{node_id}' does not exist in run '{run_id}'")
        return row

    @staticmethod
    def _node_from_row(row: sqlite3.Row) -> DAGNodeState:
        return DAGNodeState(
            run_id=row["run_id"],
            node_id=row["node_id"],
            skill_id=row["skill_id"],
            status=row["status"],
            dependencies=tuple(json.loads(row["dependencies_json"])),
            repair_attempts=int(row["repair_attempts"]),
            max_repairs=int(row["max_repairs"]),
            failure_code=row["failure_code"],
            failure_reason=row["failure_reason"],
            output_ref=row["output_ref"],
        )

    def _emit(self, name: str, run_id: str, **fields: Any) -> None:
        if self._event_sink is None:
            return
        self._event_sink(name, {"run_id": run_id, **fields})
