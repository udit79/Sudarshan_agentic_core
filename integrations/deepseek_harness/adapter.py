"""Replaceable application boundary used by Harness-facing transports."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal


HarnessOperation = Literal[
    "run", "resume", "cancel", "status", "get_artifact", "submit", "wait",
    "health", "cleanup_lifecycle", "usage", "list_skills", "get_skill",
    "invoke_skill", "submit_skill", "list_pipelines", "remember_context",
    "recall_session_context", "search_text_evidence", "search_visual_evidence",
    "search_table_evidence", "search_video_segment_evidence", "get_evidence",
]

_ALLOWED_OPERATIONS = frozenset(HarnessOperation.__args__)


class SudarshanHarnessAdapter:
    """Delegate approved transport operations to the application service."""

    def __init__(self, application_factory: Callable[[], Any] | None = None) -> None:
        self._application_factory = application_factory

    def call(self, operation: HarnessOperation, *args: Any, **kwargs: Any) -> Any:
        if operation not in _ALLOWED_OPERATIONS:
            raise ValueError(f"unsupported Harness operation: {operation}")
        return getattr(self._application(), operation)(*args, **kwargs)

    def _application(self) -> Any:
        if self._application_factory is not None:
            return self._application_factory()
        from integrations.deepseek_harness.application import get_application

        return get_application()


_adapter = SudarshanHarnessAdapter()


def get_harness_adapter() -> SudarshanHarnessAdapter:
    """Return the process-local adapter without creating another orchestrator."""

    return _adapter


__all__ = ["HarnessOperation", "SudarshanHarnessAdapter", "get_harness_adapter"]
