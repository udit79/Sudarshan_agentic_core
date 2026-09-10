"""End-to-end tests for the Harness integration."""

import pytest
from unittest.mock import patch, MagicMock

from pipelines.common.contracts import AdvisoryRequest
from integrations.deepseek_harness.application import SudarshanApplication


@pytest.fixture
def test_app(recording_backend):
    with patch("integrations.deepseek_harness.application.MemoryManager.from_env") as mock_from_env:
        from memory import MemoryManager
        mock_from_env.return_value = MemoryManager(recording_backend)
        yield SudarshanApplication()


def test_harness_e2e_health(test_app):
    health = test_app.health()
    assert health["status"] == "ok"
    assert health["memory_system"] == "connected"
    assert "advisory" in health["pipelines"]


def test_harness_list_pipelines(test_app):
    pipelines = test_app.list_pipelines()
    assert "advisory" in pipelines
    assert "infographic" in pipelines
    assert "linkedin_post" in pipelines
    assert "presentation" in pipelines
    assert "video" in pipelines


def test_harness_memory_roundtrip(test_app):
    user_id = "test_user_1"
    case_id = "test_case_1"
    context = "The primary objective is tracking maritime activity."
    
    # Write memory
    test_app.remember_context(user_id, case_id, context)
    
    # Recall memory
    recalled = test_app.recall_session_context(user_id, case_id, "maritime")
    assert "maritime activity" in recalled


def test_harness_cancellation(test_app):
    # This just tests the routing boundary for cancellation
    result = test_app.cancel("test-run-cancel", "task-cancel")
    assert "status" in result
    assert result["status"] in {"requested", "not_found", "already_terminal", "cancelled"}


def test_harness_bounded_wait_returns_safe_not_found_projection(test_app):
    result = test_app.wait("missing-run", timeout_ms=0)

    assert result["status"] == "not_found"
    assert result["wait_timed_out"] is False
