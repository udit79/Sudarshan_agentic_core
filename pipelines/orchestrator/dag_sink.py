"""DAGProjectionSink protocol — the write boundary for NP-08 public DAG projections.

Any component that needs to record DAG transitions or enqueue intents
implements this protocol. The default implementation is ``DependencyDAG``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pipelines.orchestrator.contracts import DAGTransitionIntent, RunEnqueueIntent


@runtime_checkable
class DAGProjectionSink(Protocol):
    """Write-only projection interface for the public DAG store.

    Implementations must be thread-safe and transactional per call.
    """

    def apply_transition(self, intent: DAGTransitionIntent) -> int:
        """Apply a state transition and return the new local revision number."""
        ...

    def apply_enqueue(self, intent: RunEnqueueIntent) -> int:
        """Persist an enqueue intent to the outbox and return the outbox row id.

        The implementation must assign ``intent.created_at`` if it is ``None``.
        """
        ...
