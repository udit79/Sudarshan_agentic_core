"""Bridge persisted DAG nodes to the durable LocalRunScheduler."""

from __future__ import annotations

from threading import Event, Lock
from typing import Any, Callable, Mapping

from api.control_plane import ControlPlane
from api.scheduler import LocalRunScheduler
from pipelines.orchestrator.contracts import NodeSpec
from pipelines.orchestrator.dag import DAGNodeState, DependencyDAG


NodeExecutor = Callable[[DAGNodeState, Mapping[str, Any], Event], Mapping[str, Any]]


class DAGSchedulerBridge:
    """Admit ready DAG nodes as leased jobs and advance dependent nodes."""

    def __init__(
        self,
        dag: DependencyDAG,
        execute_node: NodeExecutor,
        *,
        queue_db_path: str = "artifacts/.state/dag_queue.db",
        max_workers: int = 2,
        lease_ms: int = 900_000,
        control_plane: ControlPlane | None = None,
    ) -> None:
        self.dag = dag
        self.execute_node = execute_node
        self.max_workers = max_workers
        self._contexts: dict[str, tuple[dict[str, Any], str]] = {}
        self._context_lock = Lock()
        self.scheduler = LocalRunScheduler(
            self._execute_job,
            db_path=queue_db_path,
            max_workers=max_workers,
            lease_ms=lease_ms,
            control_plane=control_plane,
            queue_name="dag",
        )

    def start_run(
        self,
        run_id: str,
        nodes: list[NodeSpec],
        payload: Mapping[str, Any],
        *,
        operator_id: str,
    ) -> dict[str, Any]:
        """Persist a graph and submit its initially ready nodes."""

        self.dag.create_run(run_id, nodes)
        with self._context_lock:
            self._contexts[run_id] = (dict(payload), operator_id)
        self._submit_ready(run_id)
        return self.status(run_id)

    def status(self, run_id: str) -> dict[str, Any]:
        run = self.dag.get_run(run_id)
        return {
            "run_id": run.run_id,
            "status": run.status,
            "node_count": run.node_count,
            "completed_count": run.completed_count,
            "failed_count": run.failed_count,
            "nodes": [node.__dict__ if hasattr(node, "__dict__") else {
                "run_id": node.run_id,
                "node_id": node.node_id,
                "skill_id": node.skill_id,
                "status": node.status,
                "dependencies": list(node.dependencies),
                "repair_attempts": node.repair_attempts,
                "max_repairs": node.max_repairs,
                "failure_code": node.failure_code,
                "failure_reason": node.failure_reason,
                "output_ref": node.output_ref,
            } for node in self.dag.list_nodes(run_id)],
            "scheduler": self.scheduler.metrics(),
        }

    def _submit_ready(
        self,
        run_id: str,
        *,
        fallback_context: tuple[dict[str, Any], str] | None = None,
    ) -> None:
        with self._context_lock:
            context = self._contexts.get(run_id)
        if context is None:
            context = fallback_context
        if context is None:
            return
        base_payload, operator_id = context
        nodes = self.dag.claim_ready_nodes(run_id, limit=self.max_workers)
        for node in nodes:
            job_id = self._job_id(run_id, node)
            payload = dict(base_payload)
            payload["task_id"] = f"{base_payload.get('task_id', run_id)}:{node.node_id}"
            payload["requested_pipelines"] = [node.skill_id]
            metadata = dict(payload.get("metadata") or {})
            metadata.update({
                "dag_run_id": run_id,
                "dag_node_id": node.node_id,
                "dag_node_repair_attempt": node.repair_attempts,
                "dag_base_task_id": str(base_payload.get("task_id", run_id)),
            })
            payload["metadata"] = metadata
            try:
                self.scheduler.submit(job_id, payload, operator_id=operator_id)
            except Exception as error:
                self.dag.complete_node(
                    run_id,
                    node.node_id,
                    status="failed",
                    failure_code="DAG_JOB_ADMISSION_FAILED",
                    failure_reason=str(error)[:1000],
                )

    def _execute_job(
        self,
        payload: Mapping[str, Any],
        *,
        operator_id: str,
        cancel_event: Event,
    ) -> Mapping[str, Any]:
        metadata = dict(payload.get("metadata") or {})
        run_id = str(metadata.get("dag_run_id", ""))
        node_id = str(metadata.get("dag_node_id", ""))
        if not run_id or not node_id:
            return {"status": "failed", "error": "DAG node metadata is missing"}
        node = self.dag.get_node(run_id, node_id)
        try:
            result = dict(self.execute_node(node, payload, cancel_event))
        except Exception as error:
            result = {
                "status": "failed",
                "error": str(error)[:1000],
                "failure_code": "DAG_NODE_EXCEPTION",
            }
        raw_status = str(result.get("status", "failed"))
        status = raw_status if raw_status in {"succeeded", "waiting", "failed", "cancelled"} else "failed"
        self.dag.complete_node(
            run_id,
            node_id,
            status=status,
            output_ref=result.get("output_ref"),
            failure_code=result.get("failure_code") or ("DAG_NODE_FAILED" if status == "failed" else None),
            failure_reason=result.get("error") or result.get("failure_reason"),
            repair=bool(result.get("repair", False)),
        )
        # A successful node can unlock more work; a repairable failure may also
        # put the same node back into ready state. DAG locking makes concurrent
        # completion callbacks safe and prevents duplicate claims.
        # The in-memory context is intentionally not the source of truth. If
        # this worker belongs to a bridge recreated after a process restart,
        # recover the base request from the durable job payload so dependent
        # nodes can still be admitted.
        fallback_payload = dict(payload)
        base_task_id = str(metadata.get("dag_base_task_id", "")).strip()
        if base_task_id:
            fallback_payload["task_id"] = base_task_id
        self._submit_ready(
            run_id,
            fallback_context=(fallback_payload, operator_id),
        )
        return {
            "status": "pending" if status == "waiting" else status,
            "error": result.get("error") if status == "failed" else None,
            "node_id": node_id,
        }

    @staticmethod
    def _job_id(run_id: str, node: DAGNodeState) -> str:
        return f"{run_id}::node::{node.node_id}::repair-{node.repair_attempts}"

    def close(self) -> None:
        self.scheduler.close()
        self.dag.close()


__all__ = ["DAGSchedulerBridge", "NodeExecutor"]
