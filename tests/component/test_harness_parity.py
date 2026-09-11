from __future__ import annotations

from typing import Any

from integrations.deepseek_harness.adapter import SudarshanHarnessAdapter
from integrations.deepseek_harness import mcp_server


class FakeApplication:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _result(self, operation: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((operation, args, kwargs))
        return {
            "operation": operation,
            "run_id": "run-parity",
            "task_id": "task-parity",
            "status": "running" if operation in {"submit", "status", "wait"} else "completed",
            "artifact_id": "artifact-parity" if operation == "get_artifact" else None,
        }

    def run(self, *args: Any, **kwargs: Any) -> dict[str, Any]: return self._result("run", *args, **kwargs)
    def resume(self, *args: Any, **kwargs: Any) -> dict[str, Any]: return self._result("resume", *args, **kwargs)
    def cancel(self, *args: Any, **kwargs: Any) -> dict[str, Any]: return self._result("cancel", *args, **kwargs)
    def status(self, *args: Any, **kwargs: Any) -> dict[str, Any]: return self._result("status", *args, **kwargs)
    def get_artifact(self, *args: Any, **kwargs: Any) -> dict[str, Any]: return self._result("get_artifact", *args, **kwargs)
    def submit(self, *args: Any, **kwargs: Any) -> dict[str, Any]: return self._result("submit", *args, **kwargs)
    def wait(self, *args: Any, **kwargs: Any) -> dict[str, Any]: return self._result("wait", *args, **kwargs)


def test_native_mcp_facade_matches_replaceable_adapter(monkeypatch) -> None:
    native_app = FakeApplication()
    external_app = FakeApplication()
    native_adapter = SudarshanHarnessAdapter(lambda: native_app)
    external_adapter = SudarshanHarnessAdapter(lambda: external_app)
    monkeypatch.setattr(mcp_server, "get_harness_adapter", lambda: native_adapter)

    native = [
        mcp_server.start_sudarshan_run("q", "u", "c", "t"),
        mcp_server.get_sudarshan_status("run-parity"),
        mcp_server.wait_sudarshan("run-parity", timeout_ms=10, after_sequence=2),
        mcp_server.resume_sudarshan("run-parity", "task-parity", {"approved": True}),
        mcp_server.cancel_sudarshan("run-parity", "task-parity"),
        mcp_server.get_sudarshan_artifact("artifact-parity"),
    ]
    external = [
        external_adapter.call("submit", {
            "query": "q", "user_id": "u", "case_id": "c", "task_id": "t",
            "classification_level": "RESTRICTED", "requested_pipelines": [],
            "operation": "create", "parent_run_id": None, "parent_artifact_id": None,
            "revision_instruction": None, "revision_scope": [], "metadata": {},
        }, operator_id="u"),
        external_adapter.call("status", "run-parity"),
        external_adapter.call("wait", "run-parity", timeout_ms=10, after_sequence=2),
        external_adapter.call("resume", "run-parity", "task-parity", {"approved": True}),
        external_adapter.call("cancel", "run-parity", "task-parity"),
        external_adapter.call("get_artifact", "artifact-parity", classification_level="RESTRICTED"),
    ]

    assert [item["operation"] for item in native] == [item["operation"] for item in external]
    for left, right in zip(native, external):
        assert left["run_id"] == right["run_id"]
        assert left["task_id"] == right["task_id"]
        assert left["status"] == right["status"]
        assert left["artifact_id"] == right["artifact_id"]
    assert [call[0] for call in native_app.calls] == [call[0] for call in external_app.calls]
