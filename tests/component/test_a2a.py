from __future__ import annotations

from integrations.deepseek_harness.a2a import agent_card, cancel_task, get_task, submit_task


class FakeApplication:
    def submit(self, payload, *, operator_id):
        assert operator_id == "operator-1"
        return {"run_id": "run-a2a", "task_id": payload["task_id"], "status": "queued"}

    def status(self, run_id):
        return {"status": "succeeded", "event_cursor": 3, "artifact_manifests": [{"artifact_id": "a-1"}]}

    def cancel(self, run_id, task_id):
        return {"status": "cancelled"}


def test_a2a_preserves_sudarshan_handles_and_safe_state():
    app = FakeApplication()
    submitted = submit_task(app, {"task_id": "task-a2a"}, operator_id="operator-1")
    assert submitted["id"] == "run-a2a"
    assert get_task(app, "run-a2a")["metadata"]["event_cursor"] == 3
    assert cancel_task(app, "run-a2a", task_id="task-a2a")["status"]["state"] == "cancelled"
    assert agent_card()["capabilities"]["streaming"] is True
