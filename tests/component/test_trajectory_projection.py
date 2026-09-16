from integrations.deepseek_harness.application import SudarshanApplication
from integrations.deepseek_harness.mcp_server import MCP_TOOL_PROFILES


class _ApplicationForTrajectory(SudarshanApplication):
    def __init__(self) -> None:
        pass

    def observability_events(self, run_id: str, *, operator_id=None, limit=500):
        return {
            "status": "ready",
            "run_id": run_id,
            "event_count": 3,
            "events": [
                {"event_id": "one", "lane_id": "main", "status": "running", "stage": "request"},
                {"event_id": "two", "lane_id": "child-a", "status": "succeeded", "stage": "skill.completed"},
                {"event_id": "three", "lane_id": "child-a", "status": "succeeded", "stage": "quality"},
            ],
        }


def test_trajectory_groups_recorded_events_into_parallel_lanes():
    result = _ApplicationForTrajectory().trajectory("run-1", operator_id="operator-1")

    assert result["event_count"] == 3
    assert [lane["lane_id"] for lane in result["lanes"]] == ["main", "child-a"]
    assert result["lanes"][1]["event_count"] == 2
    assert result["lanes"][1]["last_stage"] == "quality"


def test_trajectory_tool_is_available_to_safe_harness_profiles():
    assert "get_sudarshan_trajectory" in MCP_TOOL_PROFILES["artifact"]
    assert "get_sudarshan_trajectory" in MCP_TOOL_PROFILES["specialist"]
    assert "get_sudarshan_trajectory" in MCP_TOOL_PROFILES["operator"]
