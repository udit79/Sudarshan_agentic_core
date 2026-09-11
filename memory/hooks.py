"""Non-blocking lifecycle hooks for lessons and profile updates."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from threading import Event, Thread, Timer
from typing import Any


class MemoryLifecycleHooks:
    """Dispatch safe lifecycle observations without delaying the run.

    The callback should perform its own bounded network work. A failing hook is
    isolated from the agent run and reported through ``on_error``.
    """

    def __init__(
        self,
        remember: Callable[[str, Mapping[str, Any]], Any] | None = None,
        *,
        on_error: Callable[[Exception], Any] | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.remember = remember
        self.on_error = on_error
        self.timeout_seconds = timeout_seconds

    def emit(self, event_type: str, payload: Mapping[str, Any]) -> None:
        if self.remember is None:
            return
        worker = Thread(target=self._run, args=(event_type, dict(payload)), daemon=True)
        worker.start()

    def session_start(self, payload: Mapping[str, Any]) -> None:
        self.emit("session_start", payload)

    def tool_complete(self, payload: Mapping[str, Any]) -> None:
        self.emit("tool_complete", payload)

    def compaction(self, payload: Mapping[str, Any]) -> None:
        self.emit("compaction", payload)

    def session_end(self, payload: Mapping[str, Any]) -> None:
        self.emit("session_end", payload)

    def _run(self, event_type: str, payload: Mapping[str, Any]) -> None:
        finished = Event()

        def timeout() -> None:
            if not finished.is_set() and self.on_error is not None:
                self.on_error(TimeoutError(f"memory hook timed out: {event_type}"))

        timer = Timer(self.timeout_seconds, timeout)
        timer.daemon = True
        timer.start()
        try:
            self.remember(event_type, payload)
        except Exception as exc:  # hooks are observability, never a run gate
            if self.on_error is not None:
                self.on_error(exc)
        finally:
            finished.set()
            timer.cancel()


__all__ = ["MemoryLifecycleHooks"]
