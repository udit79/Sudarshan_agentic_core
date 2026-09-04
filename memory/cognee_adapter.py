"""Cognee REST adapter.

The adapter is the only module that knows Cognee's HTTP payloads. It uses the
documented ``remember`` endpoint for ingestion/build and ``recall`` for
retrieval, while Sudarshan keeps ownership of scope and provenance semantics.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import time
import uuid
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class CogneeError(RuntimeError):
    """Base error for adapter failures."""


class CogneeRequestError(CogneeError):
    def __init__(self, status: int | None, message: str) -> None:
        self.status = status
        super().__init__(message)


def load_env_file(path: str = ".env") -> None:
    """Load simple KEY=VALUE pairs without overwriting process variables.

    This keeps the core package dependency-free while supporting the local
    workflow requested for Cognee credentials. Production process variables
    always win, and values are never logged by this module.
    """

    env_path = Path(path)
    if not env_path.is_file():
        return
    assignment = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        match = assignment.match(line)
        if not match or match.group(1) in os.environ:
            continue
        value = match.group(2)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ[match.group(1)] = value


@dataclass(frozen=True, slots=True)
class CogneeConfig:
    base_url: str = "http://localhost:8011"
    api_key: str | None = None
    tenant_id: str | None = None
    dataset_name: str = "sudarshan_memory"
    timeout_seconds: float = 30.0
    max_retries: int = 2
    write_max_retries: int = 0
    retry_backoff_seconds: float = 0.5

    @classmethod
    def from_env(cls) -> "CogneeConfig":
        load_env_file()
        def number(name: str, default: str, cast: type) -> Any:
            try:
                return cast(os.getenv(name, default))
            except ValueError as exc:
                raise ValueError(f"{name} must be numeric") from exc

        base_url = os.getenv("COGNEE_BASE_URL", cls.base_url).strip().rstrip("/")
        dataset_name = os.getenv("COGNEE_DATASET_NAME", cls.dataset_name).strip()
        tenant_id = os.getenv("COGNEE_TENANT_ID") or None
        if not base_url or not dataset_name:
            raise ValueError("COGNEE_BASE_URL and COGNEE_DATASET_NAME must be non-empty")
        host = urlparse(base_url).hostname or ""
        if host.endswith("cognee.ai") and not tenant_id:
            raise ValueError("COGNEE_TENANT_ID is required for Cognee Cloud")
        return cls(
            base_url=base_url,
            api_key=os.getenv("COGNEE_API_KEY") or None,
            tenant_id=tenant_id,
            dataset_name=dataset_name,
            timeout_seconds=number("COGNEE_TIMEOUT_SECONDS", "30", float),
            max_retries=number("COGNEE_MAX_RETRIES", "2", int),
            write_max_retries=number("COGNEE_WRITE_MAX_RETRIES", "0", int),
            retry_backoff_seconds=number("COGNEE_RETRY_BACKOFF_SECONDS", "0.5", float),
        )


class MemoryBackend(Protocol):
    def remember(self, *, memory_id: str, content: str, node_sets: Sequence[str],
                 metadata: Mapping[str, Any], dataset_name: str, run_in_background: bool) -> Mapping[str, Any]: ...

    def recall(self, *, query: str, node_sets: Sequence[str], dataset_name: str,
               top_k: int, session_id: str | None = None) -> Sequence[Any]: ...


class CogneeHttpAdapter:
    def __init__(self, config: CogneeConfig | None = None) -> None:
        self.config = config or CogneeConfig.from_env()

    def _headers(self, content_type: str | None = None) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if content_type:
            headers["Content-Type"] = content_type
        if self.config.api_key:
            headers["X-Api-Key"] = self.config.api_key
        if self.config.tenant_id:
            headers["X-Tenant-Id"] = self.config.tenant_id
        return headers

    def _request(self, method: str, path: str, body: bytes | None,
                 content_type: str | None, *, retry: bool,
                 max_retries: int | None = None) -> Any:
        attempts = (self.config.max_retries if max_retries is None else max_retries) if retry else 0
        for attempt in range(attempts + 1):
            request = Request(self.config.base_url + path, data=body,
                              headers=self._headers(content_type), method=method)
            try:
                with urlopen(request, timeout=self.config.timeout_seconds) as response:
                    raw = response.read()
                if not raw:
                    return {}
                return json.loads(raw.decode("utf-8"))
            except HTTPError as exc:
                raw = exc.read().decode("utf-8", errors="replace")
                if exc.code not in (408, 429) and not 500 <= exc.code <= 599:
                    raise CogneeRequestError(exc.code, f"Cognee request failed ({exc.code}): {raw[:500]}") from exc
                if attempt >= attempts:
                    raise CogneeRequestError(exc.code, f"Cognee request failed after retries ({exc.code})") from exc
                self._sleep_before_retry(attempt, exc.headers.get("Retry-After"))
            except (URLError, TimeoutError) as exc:
                if attempt >= attempts:
                    raise CogneeRequestError(None, f"Cognee is unreachable: {exc}") from exc
                self._sleep_before_retry(attempt, None)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise CogneeRequestError(None, "Cognee returned invalid JSON") from exc
        raise AssertionError("unreachable")

    def _sleep_before_retry(self, attempt: int, retry_after: str | None) -> None:
        delay: float | None = None
        if retry_after:
            try:
                delay = max(0.0, float(retry_after))
            except ValueError:
                try:
                    delay = max(0.0, (parsedate_to_datetime(retry_after).timestamp() - time.time()))
                except (TypeError, ValueError, OverflowError):
                    delay = None
        if delay is None:
            delay = self.config.retry_backoff_seconds * (2 ** attempt)
        time.sleep(delay)

    @staticmethod
    def _multipart(fields: Mapping[str, str], file_name: str, file_content: str,
                   repeated: Mapping[str, Sequence[str]]) -> tuple[bytes, str]:
        boundary = "----SudarshanMemory" + uuid.uuid4().hex
        chunks: list[bytes] = []
        for name, value in fields.items():
            chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
        for name, values in repeated.items():
            for value in values:
                chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
        chunks.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"data\"; filename=\"{file_name}\"\r\n"
                       f"Content-Type: text/plain; charset=utf-8\r\n\r\n{file_content}\r\n").encode("utf-8"))
        chunks.append(f"--{boundary}--\r\n".encode())
        return b"".join(chunks), f"multipart/form-data; boundary={boundary}"

    def remember(self, *, memory_id: str, content: str, node_sets: Sequence[str],
                 metadata: Mapping[str, Any], dataset_name: str,
                 run_in_background: bool = True) -> Mapping[str, Any]:
        # Cognee's REST remember endpoint accepts files. Metadata is also
        # included in the document so it survives graph/vector processing.
        document = json.dumps({"sudarshan_memory_id": memory_id,
                               "metadata": dict(metadata), "content": content},
                              ensure_ascii=False, separators=(",", ":"))
        body, content_type = self._multipart(
            {"datasetName": dataset_name, "run_in_background": str(run_in_background).lower()},
            f"{memory_id}.json", document, {"node_set": list(node_sets)},
        )
        # A remember retry can duplicate a document because the public REST
        # contract has no idempotency-key parameter. Keep write retries opt-in.
        return self._request("POST", "/api/v1/remember", body, content_type,
                             retry=self.config.write_max_retries > 0,
                             max_retries=self.config.write_max_retries)

    def recall(self, *, query: str, node_sets: Sequence[str], dataset_name: str,
               top_k: int, session_id: str | None = None) -> Sequence[Any]:
        payload: dict[str, Any] = {
            "query": query,
            "datasets": [dataset_name],
            "node_name": list(node_sets),
            "top_k": top_k,
            "only_context": True,
            "verbose": True,
        }
        if session_id:
            payload["session_id"] = session_id
        result = self._request("POST", "/api/v1/recall", json.dumps(payload).encode(),
                               "application/json", retry=True)
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and isinstance(result.get("results"), list):
            return result["results"]
        return [result]
