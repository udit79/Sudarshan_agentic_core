"""Application-owned CrewAI Flow persistence configuration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, TypeVar

from crewai.flow.persistence import FlowPersistence, SQLiteFlowPersistence, persist


_FlowTarget = TypeVar("_FlowTarget")

if TYPE_CHECKING:
    def typed_persist(
        persistence: FlowPersistence | None = None,
        verbose: bool = False,
    ) -> Callable[[_FlowTarget], _FlowTarget]:
        """Typing shim for CrewAI's class-or-method decorator overload."""

        raise NotImplementedError
else:
    def typed_persist(
        persistence: FlowPersistence | None = None,
        verbose: bool = False,
    ) -> Callable[..., Any]:
        """Runtime wrapper preserving CrewAI's persistence behavior."""

        return persist(persistence, verbose)


def flow_persistence() -> SQLiteFlowPersistence:
    """Build the durable Flow state store used by all Sudarshan pipelines.

    CrewAI's implicit default points at a user-global cache location. That is
    unsuitable for a deployable application: it can be read-only, shared by
    unrelated projects, and impossible to back up with the application state.
    Keep the path configurable, but make the repository-local default explicit
    for local development and the first deployment.
    """

    configured = os.getenv("CREWAI_FLOW_DB_PATH", "artifacts/.state/flow_states.db").strip()
    if not configured:
        raise ValueError("CREWAI_FLOW_DB_PATH must not be empty")
    db_path = Path(configured).expanduser()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return SQLiteFlowPersistence(str(db_path))
