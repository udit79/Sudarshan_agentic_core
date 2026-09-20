from types import SimpleNamespace

from integrations.deepseek_harness.application import SudarshanApplication


class _MemoryBackend:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def recall(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


def _app_with_memory_backend(backend):
    app = object.__new__(SudarshanApplication)
    app.orchestrator = SimpleNamespace(memory_manager=backend)
    return app


def test_memory_health_probe_is_opt_in_and_does_not_call_backend(monkeypatch):
    monkeypatch.delenv("SUDARSHAN_HEALTH_PROBE_MEMORY", raising=False)
    backend = _MemoryBackend()

    result = _app_with_memory_backend(backend)._memory_health_probe()

    assert result == {"status": "not_run", "reason": "opt_in_required"}
    assert backend.calls == []


def test_memory_health_probe_reports_reachability_without_raw_memory(monkeypatch):
    monkeypatch.setenv("SUDARSHAN_HEALTH_PROBE_MEMORY", "true")
    backend = _MemoryBackend(
        response=SimpleNamespace(
            results=(SimpleNamespace(content="private memory must not be returned"),),
        )
    )

    result = _app_with_memory_backend(backend)._memory_health_probe()

    assert result["status"] == "reachable"
    assert result["result_count"] == 1
    assert "private memory" not in str(result)
    assert backend.calls[0]["context"].user_id == "health-probe"
    assert backend.calls[0]["context"].case_id == "health-probe"
    assert backend.calls[0]["token_budget"] == 256


def test_memory_health_probe_reports_failure_as_degraded_safe_metadata(monkeypatch):
    monkeypatch.setenv("SUDARSHAN_HEALTH_PROBE_MEMORY", "1")
    backend = _MemoryBackend(error=TimeoutError("raw provider timeout must not leak"))

    result = _app_with_memory_backend(backend)._memory_health_probe()

    assert result["status"] == "unreachable"
    assert result["error_code"] == "TimeoutError"
    assert "raw provider timeout" not in str(result)


def test_health_marks_unreachable_memory_as_degraded(monkeypatch):
    monkeypatch.setenv("SUDARSHAN_HEALTH_PROBE_MEMORY", "true")
    app = _app_with_memory_backend(_MemoryBackend(error=TimeoutError()))
    app.control_plane_mode = "sqlite"
    app.control_plane = None
    app.scheduler = SimpleNamespace(metrics=lambda: {})
    app.ingestion_scheduler = SimpleNamespace(metrics=lambda: {})
    app.orchestrator.registry = {}

    result = app.health()

    assert result["status"] == "degraded"
    assert result["memory_probe"]["status"] == "unreachable"
