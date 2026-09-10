"""Persisted dependency DAG for typed skill and rendering nodes.

This is the graph-admission layer for T11. It does not execute providers or
threads; it persists node state, identifies safe parallel work, blocks failed
descendants, and bounds repair loops. A worker or the durable scheduler can
claim the returned nodes and call ``complete_node`` when execution finishes.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Iterable, Literal, Mapping

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

    def __init__(self, db_path: str | Path = "artifacts/.state/dag.db", *, event_sink: EventSink | None = None) -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = RLock()
        self._event_sink = event_sink
        self._create_schema()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def create_run(self, run_id: str, nodes: Iterable[NodeSpec]) -> DAGRunState:
        if not run_id.strip():
            raise DAGError("run_id must be non-empty")
        specs = tuple(nodes)
        self._validate_specs(specs)
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
        self._emit("dag.created", run_id, node_count=len(specs))
        return self.get_run(run_id)

    def admit_ready_nodes(self, run_id: str) -> list[DAGNodeState]:
        """Re-evaluate dependencies and return all currently ready nodes."""

        with self._lock, self._connection:
            self._require_run_locked(run_id)
            changed = self._refresh_ready_locked(run_id)
            self._update_run_status_locked(run_id)
            rows = self._connection.execute(
                "SELECT * FROM dag_nodes WHERE run_id = ? AND status = 'ready' ORDER BY node_id",
                (run_id,),
            ).fetchall()
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
        with self._lock, self._connection:
            for node in selected:
                self._connection.execute(
                    "UPDATE dag_nodes SET status = 'running' WHERE run_id = ? AND node_id = ? AND status = 'ready'",
                    (run_id, node.node_id),
                )
            self._update_run_status_locked(run_id)
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
        for event_name, fields in emitted:
            self._emit(event_name, run_id, **fields)
        return result

    def get_node(self, run_id: str, node_id: str) -> DAGNodeState:
        with self._lock:
            return self._node_from_row(self._get_node_row_locked(run_id, node_id))

    def list_nodes(self, run_id: str) -> list[DAGNodeState]:
        with self._lock:
            self._require_run_locked(run_id)
            rows = self._connection.execute(
                "SELECT * FROM dag_nodes WHERE run_id = ? ORDER BY node_id", (run_id,)
            ).fetchall()
        return [self._node_from_row(row) for row in rows]

    def get_run(self, run_id: str) -> DAGRunState:
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

