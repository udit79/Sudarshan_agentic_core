"""Provider-neutral social capability boundary.

Skills submit typed requests here. They never import a social SDK, read
credentials, publish directly, or bypass approval and audit policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event
from time import monotonic
from typing import Any, Literal, Mapping, Protocol
from uuid import uuid4

from integrations.providers.receipts import classify_provider_error


SocialOperation = Literal[
    "fetch_post",
    "fetch_comments",
    "fetch_thread",
    "create_post",
    "create_comment",
    "create_reply",
]
SocialStatus = Literal[
    "draft_only",
    "approval_required",
    "pending",
    "succeeded",
    "failed",
    "cancelled",
]

READ_OPERATIONS = frozenset({"fetch_post", "fetch_comments", "fetch_thread"})
WRITE_OPERATIONS = frozenset({"create_post", "create_comment", "create_reply"})


class SocialCapabilityError(RuntimeError):
    """Stable boundary error returned when a request is not executable."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class SocialRequest:
    operation: SocialOperation
    target_ref: str = ""
    payload: Mapping[str, Any] = field(default_factory=dict)
    provider: str = "manual"
    case_id: str = ""
    run_id: str = ""
    skill_id: str = "linkedin.post"
    approval_id: str | None = None
    idempotency_key: str = ""
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.operation not in READ_OPERATIONS | WRITE_OPERATIONS:
            raise ValueError(f"unsupported social operation: {self.operation}")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 900:
            raise ValueError("timeout_seconds must be between 0 and 900")
        if self.operation in WRITE_OPERATIONS and not self.target_ref and self.operation != "create_post":
            raise ValueError("write operations require target_ref except create_post")

    @property
    def is_write(self) -> bool:
        return self.operation in WRITE_OPERATIONS


@dataclass(frozen=True, slots=True)
class SocialReceipt:
    receipt_id: str
    provider: str
    operation: SocialOperation
    status: SocialStatus
    target_ref: str
    request_id: str | None = None
    provider_request_id: str | None = None
    failure_class: str | None = None
    error_code: str | None = None
    retry_after_seconds: float | None = None
    manual_required: bool = False
    approval_id: str | None = None
    audit_ref: str | None = None
    data: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "provider": self.provider,
            "operation": self.operation,
            "status": self.status,
            "target_ref": self.target_ref,
            "request_id": self.request_id,
            "provider_request_id": self.provider_request_id,
            "failure_class": self.failure_class,
            "error_code": self.error_code,
            "retry_after_seconds": self.retry_after_seconds,
            "manual_required": self.manual_required,
            "approval_id": self.approval_id,
            "audit_ref": self.audit_ref,
            "data": dict(self.data),
            "metadata": dict(self.metadata),
        }


class SocialAdapter(Protocol):
    """Small SDK-free adapter contract implemented by an approved connector."""

    provider: str

    def execute(
        self,
        request: SocialRequest,
        *,
        cancel_event: Event | None = None,
    ) -> Mapping[str, Any]:
        """Return a provider-neutral mapping; do not return credentials."""


class ManualSocialAdapter:
    """Safe default: create drafts and request operator action, never publish."""

    provider = "manual"

    def execute(self, request: SocialRequest, *, cancel_event: Event | None = None) -> Mapping[str, Any]:
        if cancel_event is not None and cancel_event.is_set():
            return {"status": "cancelled"}
        return {
            "status": "draft_only",
            "manual_required": True,
            "target_ref": request.target_ref,
            "message": "No social provider is configured; use the approved manual copy/export path.",
        }


class SocialCapabilityBoundary:
    """Validate policy, dispatch an adapter, and return a safe receipt."""

    def __init__(self, adapters: Mapping[str, SocialAdapter] | None = None) -> None:
        self._adapters: dict[str, SocialAdapter] = {"manual": ManualSocialAdapter()}
        for name, adapter in (adapters or {}).items():
            if not str(name).strip():
                raise ValueError("social adapter name must be non-empty")
            self._adapters[str(name).strip().lower()] = adapter

    def register(self, adapter: SocialAdapter, *, replace: bool = False) -> None:
        provider = str(adapter.provider).strip().lower()
        if not provider:
            raise ValueError("social adapter provider must be non-empty")
        if provider in self._adapters and not replace:
            raise ValueError(f"social adapter '{provider}' is already registered")
        self._adapters[provider] = adapter

    def execute(
        self,
        request: SocialRequest,
        *,
        cancel_event: Event | None = None,
        audit_ref: str | None = None,
    ) -> SocialReceipt:
        receipt_id = f"social-{uuid4()}"
        if cancel_event is not None and cancel_event.is_set():
            return self._receipt(request, receipt_id, "cancelled", audit_ref=audit_ref)
        if request.is_write and not request.approval_id:
            return self._receipt(
                request,
                receipt_id,
                "approval_required",
                audit_ref=audit_ref,
                error_code="SOCIAL_APPROVAL_REQUIRED",
            )

        adapter = self._adapters.get(request.provider.strip().lower())
        if adapter is None:
            return self._receipt(
                request,
                receipt_id,
                "draft_only" if request.is_write else "failed",
                audit_ref=audit_ref,
                error_code="SOCIAL_PROVIDER_UNAVAILABLE",
                manual_required=True,
            )

        started = monotonic()
        try:
            result = dict(adapter.execute(request, cancel_event=cancel_event) or {})
        except Exception as error:  # adapters are untrusted provider boundaries
            failure_class = classify_provider_error(error)
            return self._receipt(
                request,
                receipt_id,
                "draft_only" if request.is_write and failure_class in {"auth", "quota_exhausted", "transient", "timeout"} else "failed",
                audit_ref=audit_ref,
                error_code=f"SOCIAL_{failure_class.upper()}",
                failure_class=failure_class,
                retry_after_seconds=None,
                manual_required=request.is_write,
            )

        elapsed = monotonic() - started
        if cancel_event is not None and cancel_event.is_set():
            return self._receipt(request, receipt_id, "cancelled", audit_ref=audit_ref)
        if elapsed > request.timeout_seconds:
            return self._receipt(
                request,
                receipt_id,
                "draft_only" if request.is_write else "failed",
                audit_ref=audit_ref,
                error_code="SOCIAL_TIMEOUT",
                failure_class="timeout",
                manual_required=request.is_write,
            )

        status = str(result.pop("status", "succeeded"))
        if status not in {"draft_only", "pending", "succeeded", "failed", "cancelled"}:
            status = "failed"
        return self._receipt(
            request,
            receipt_id,
            status,  # type: ignore[arg-type]
            audit_ref=audit_ref,
            request_id=_safe_string(result.pop("request_id", None)),
            provider_request_id=_safe_string(result.pop("provider_request_id", None)),
            manual_required=bool(result.pop("manual_required", False)),
            data=result.pop("data", {}) if isinstance(result.get("data", {}), Mapping) else {},
            metadata={key: value for key, value in result.items() if key in {"source", "provenance", "retry_after_seconds", "scope"}},
        )

    @staticmethod
    def _receipt(request: SocialRequest, receipt_id: str, status: SocialStatus, **kwargs: Any) -> SocialReceipt:
        return SocialReceipt(
            receipt_id=receipt_id,
            provider=request.provider,
            operation=request.operation,
            status=status,
            target_ref=request.target_ref,
            approval_id=request.approval_id,
            **kwargs,
        )


def _safe_string(value: Any) -> str | None:
    return str(value).strip()[:200] if value is not None and str(value).strip() else None


def _safe_number(value: Mapping[str, Any] | None, key: str) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value.get(key)))
    except (TypeError, ValueError):
        return None


__all__ = [
    "ManualSocialAdapter",
    "READ_OPERATIONS",
    "SocialAdapter",
    "SocialCapabilityBoundary",
    "SocialCapabilityError",
    "SocialOperation",
    "SocialReceipt",
    "SocialRequest",
    "SocialStatus",
    "WRITE_OPERATIONS",
]
