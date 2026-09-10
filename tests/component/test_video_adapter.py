from __future__ import annotations

import threading
from typing import Any, Mapping

import pytest

from pipelines.common.contracts import AdvisoryRequest
from integrations.providers.moneyprinterturbo import (
    MoneyPrinterTurboClient,
    MoneyPrinterTurboError,
)
from pipelines.video import VideoPipeline


class RecordingMemory:
    """Memory boundary double; it records units but never fabricates provider media."""

    def __init__(self) -> None:
        self.writes: list[dict[str, Any]] = []

    def recall(self, **kwargs: Any) -> Any:
        del kwargs
        return type("Recall", (), {"context": type("Context", (), {"text": "verified case context"})()})()

    def remember(self, *args: Any, **kwargs: Any) -> None:
        self.writes.append({"args": args, "kwargs": kwargs})


def _request() -> AdvisoryRequest:
    return AdvisoryRequest(
        query="Generate a case-grounded video",
        user_id="user-1",
        case_id="case-1",
        task_id="task-video-1",
        metadata={"video_subject": "Synthetic case briefing"},
    )


def test_moneyprinter_client_uses_documented_task_contract_without_media_fixtures() -> None:
    calls: list[tuple[str, str, Mapping[str, Any] | None]] = []

    def transport(method: str, url: str, payload: Mapping[str, Any] | None, timeout: float) -> Mapping[str, Any]:
        del timeout
        calls.append((method, url, payload))
        if method == "POST":
            return {"data": {"task_id": "mpt-task-1"}}
        return {"data": {"videos": ["https://provider.invalid/video.mp4"]}}

    client = MoneyPrinterTurboClient(
        "http://moneyprinter.test",
        wait_for_completion=True,
        poll_interval_seconds=0,
        max_wait_seconds=1,
        transport=transport,
    )

    result = client.generate(subject="Synthetic briefing", script="Verified facts only.")

    assert result.status == "succeeded"
    assert result.provider_task_id == "mpt-task-1"
    assert calls[0][0:2] == ("POST", "http://moneyprinter.test/api/v1/videos")
    assert calls[0][2] == {
        "video_subject": "Synthetic briefing",
        "video_script": "Verified facts only.",
        "video_count": 1,
    }
    assert calls[1][0:2] == ("GET", "http://moneyprinter.test/api/v1/tasks/mpt-task-1")


def test_moneyprinter_client_reports_provider_failure() -> None:
    def transport(method: str, url: str, payload: Mapping[str, Any] | None, timeout: float) -> Mapping[str, Any]:
        del url, payload, timeout
        if method == "POST":
            return {"data": {"task_id": "mpt-task-failed"}}
        return {"data": {"state": "failed", "message": "worker rejected synthetic job"}}

    client = MoneyPrinterTurboClient(
        "http://moneyprinter.test", transport=transport, max_wait_seconds=1, poll_interval_seconds=0
    )

    result = client.generate(subject="Synthetic briefing")

    assert result.status == "failed"
    assert result.error == "worker rejected synthetic job"


def test_moneyprinter_client_requires_explicit_worker_configuration() -> None:
    client = MoneyPrinterTurboClient(transport=lambda *_args: {})

    with pytest.raises(MoneyPrinterTurboError, match="BASE_URL is not configured"):
        client.generate(subject="Synthetic briefing")


def test_moneyprinter_polling_stops_when_cancelled() -> None:
    cancel_event = threading.Event()
    calls: list[str] = []

    def transport(method: str, url: str, payload: Mapping[str, Any] | None, timeout: float) -> Mapping[str, Any]:
        del url, payload, timeout
        calls.append(method)
        if method == "POST":
            cancel_event.set()
            return {"data": {"task_id": "mpt-task-cancelled"}}
        raise AssertionError("cancelled polling must not issue a status request")

    client = MoneyPrinterTurboClient(
        "http://moneyprinter.test",
        transport=transport,
        wait_for_completion=True,
        poll_interval_seconds=10,
        max_wait_seconds=30,
    )
    result = client.generate(subject="Synthetic briefing", cancel_event=cancel_event)

    assert result.status == "cancelled"
    assert calls == ["POST"]


def test_video_pipeline_writes_task_and_case_memory_for_real_provider_result() -> None:
    memory = RecordingMemory()

    def transport(method: str, url: str, payload: Mapping[str, Any] | None, timeout: float) -> Mapping[str, Any]:
        del url, payload, timeout
        if method == "POST":
            return {"data": {"task_id": "mpt-task-2"}}
        return {"data": {"combined_videos": ["https://provider.invalid/combined.mp4"]}}

    client = MoneyPrinterTurboClient(
        "http://moneyprinter.test", transport=transport, max_wait_seconds=1, poll_interval_seconds=0
    )
    response = VideoPipeline(memory, client=client).run(_request())

    assert response.status == "succeeded"
    assert response.artifact["provider_task_id"] == "mpt-task-2"
    assert response.artifact["combined_videos"] == ["https://provider.invalid/combined.mp4"]
    assert len(memory.writes) == 3
    assert memory.writes[-1]["kwargs"]["scope_type"].value == "case"
