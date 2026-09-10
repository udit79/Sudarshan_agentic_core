"""Production HTTP boundary for the MoneyPrinterTurbo worker.

MoneyPrinterTurbo is deliberately not imported into Sudarshan.  Its FastAPI
application owns MoviePy, FFmpeg, TTS, media providers, and worker state.  The
Sudarshan side submits a validated task, polls the documented task endpoint,
and returns the worker's real artifact references.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from threading import Event
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


JsonTransport = Callable[[str, str, Mapping[str, Any] | None, float], Mapping[str, Any]]


class MoneyPrinterTurboError(RuntimeError):
    """Raised when the external video worker is unavailable or rejects a job."""


@dataclass(frozen=True, slots=True)
class VideoJobResult:
    status: str
    provider_task_id: str
    data: Mapping[str, Any]
    error: str | None = None


def _default_transport(
    method: str,
    url: str,
    payload: Mapping[str, Any] | None,
    timeout: float,
    headers: Mapping[str, str] | None = None,
) -> Mapping[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(url, data=body, method=method.upper())
    request.add_header("Accept", "application/json")
    if payload is not None:
        request.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urlopen(request, timeout=timeout) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise MoneyPrinterTurboError(f"MoneyPrinterTurbo request failed: {exc}") from exc
    if not isinstance(decoded, Mapping):
        raise MoneyPrinterTurboError("MoneyPrinterTurbo returned a non-object JSON response")
    return decoded


class MoneyPrinterTurboClient:
    """Submit and monitor one upstream MoneyPrinterTurbo task.

    ``transport`` is an internal seam for deterministic protocol tests only.
    Production construction leaves it unset and uses the real HTTP transport.
    No media file is synthesized by this client.
    """

    def __init__(
        self,
        base_url: str | None = None,
        *,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
        max_wait_seconds: float | None = None,
        wait_for_completion: bool | None = None,
        transport: JsonTransport | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("MONEYPRINTERTURBO_BASE_URL", "")).strip().rstrip("/")
        self.api_key = api_key or os.getenv("MONEYPRINTERTURBO_API_KEY", "").strip()
        self.timeout_seconds = timeout_seconds or float(os.getenv("MONEYPRINTERTURBO_TIMEOUT_SECONDS", "30"))
        self.poll_interval_seconds = poll_interval_seconds or float(os.getenv("MONEYPRINTERTURBO_POLL_INTERVAL_SECONDS", "2"))
        self.max_wait_seconds = max_wait_seconds or float(os.getenv("MONEYPRINTERTURBO_MAX_WAIT_SECONDS", "1800"))
        configured_wait = os.getenv("MONEYPRINTERTURBO_WAIT_FOR_COMPLETION", "true").lower()
        self.wait_for_completion = wait_for_completion if wait_for_completion is not None else configured_wait in {"1", "true", "yes"}
        self._transport = transport

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def _request(self, method: str, path: str, payload: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        if not self.base_url:
            raise MoneyPrinterTurboError(
                "MONEYPRINTERTURBO_BASE_URL is not configured; start the external MoneyPrinterTurbo service "
                "and set its base URL before enabling the video pipeline."
            )
        url = f"{self.base_url}{path if path.startswith('/') else '/' + path}"
        headers = {"X-Task-ID": str(payload.get("task_id", "sudarshan-video")) if payload else "sudarshan-video"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        if self._transport is not None:
            return self._transport(method, url, payload, self.timeout_seconds)
        return _default_transport(method, url, payload, self.timeout_seconds, headers)

    @staticmethod
    def _data(response: Mapping[str, Any]) -> Mapping[str, Any]:
        data = response.get("data", response)
        if not isinstance(data, Mapping):
            raise MoneyPrinterTurboError("MoneyPrinterTurbo response data is not an object")
        return data

    def submit(self, payload: Mapping[str, Any]) -> VideoJobResult:
        data = self._data(self._request("POST", "/api/v1/videos", payload))
        provider_task_id = str(data.get("task_id", "")).strip()
        if not provider_task_id:
            raise MoneyPrinterTurboError("MoneyPrinterTurbo did not return a task_id")
        return VideoJobResult(status="pending", provider_task_id=provider_task_id, data=data)

    def status(self, provider_task_id: str) -> VideoJobResult:
        data = self._data(self._request("GET", f"/api/v1/tasks/{provider_task_id}"))
        error = data.get("error") or data.get("message")
        videos = data.get("combined_videos") or data.get("videos")
        failed = bool(data.get("failed_stage")) or data.get("state") in {-1, "failed", "error"}
        if failed:
            return VideoJobResult("failed", provider_task_id, data, str(error or "video worker failed"))
        if isinstance(videos, list) and videos:
            return VideoJobResult("succeeded", provider_task_id, data)
        return VideoJobResult("pending", provider_task_id, data)

    def generate(
        self,
        *,
        subject: str,
        script: str = "",
        options: Mapping[str, Any] | None = None,
        cancel_event: Event | None = None,
    ) -> VideoJobResult:
        payload: dict[str, Any] = {
            "video_subject": subject[:500],
            "video_script": script[:20000],
            "video_count": 1,
        }
        if options:
            payload.update(dict(options))
        submitted = self.submit(payload)
        if not self.wait_for_completion:
            return submitted
        deadline = time.monotonic() + self.max_wait_seconds
        latest = submitted
        while time.monotonic() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                return VideoJobResult(
                    status="cancelled",
                    provider_task_id=submitted.provider_task_id,
                    data=latest.data,
                    error="video generation cancelled cooperatively",
                )
            wait_seconds = max(0.1, self.poll_interval_seconds)
            if cancel_event is not None:
                if cancel_event.wait(wait_seconds):
                    return VideoJobResult(
                        status="cancelled",
                        provider_task_id=submitted.provider_task_id,
                        data=latest.data,
                        error="video generation cancelled cooperatively",
                    )
            else:
                time.sleep(wait_seconds)
            latest = self.status(submitted.provider_task_id)
            if latest.status != "pending":
                return latest
        return VideoJobResult(
            status="pending",
            provider_task_id=submitted.provider_task_id,
            data=latest.data,
            error=f"video generation is still running after {self.max_wait_seconds:g} seconds",
        )
