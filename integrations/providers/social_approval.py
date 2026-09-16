"""Durable approval and idempotent release for social write operations."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from threading import Lock
from time import time
from typing import Any, Callable, Literal, Mapping
from uuid import uuid4

from integrations.providers.social import WRITE_OPERATIONS, SocialCapabilityBoundary, SocialReceipt, SocialRequest
from integrations.providers.social_cache import sanitize_social_mapping


class SocialApprovalConflict(RuntimeError):
    """Raised when an approval or idempotency transition is unsafe."""


@dataclass(frozen=True, slots=True)
class SocialApprovalRecord:
    approval_id: str
    operation: str
    provider: str
    target_ref: str
    payload_hash: str
    scope_hash: str
    actor_id: str
    policy_decision: str
    idempotency_key: str
    status: str
    provider_request_id: str | None
    receipt: Mapping[str, Any] | None
    created_at: float
    updated_at: float


class SocialApprovalStore:
    """SQLite-backed approval ledger with atomic release claims."""

    def __init__(self, db_path: str = "artifacts/.state/social_approvals.db") -> None:
        self.db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = Lock()
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS social_approvals (
                approval_id TEXT PRIMARY KEY,
                operation TEXT NOT NULL,
                provider TEXT NOT NULL,
                target_ref TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                scope_hash TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                policy_decision TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                status TEXT NOT NULL,
                provider_request_id TEXT,
                receipt_json TEXT,
                lease_owner TEXT,
                lease_expires_at REAL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE(scope_hash, idempotency_key)
            );
            """
        )
        self._connection.commit()

    @classmethod
    def from_env(cls) -> "SocialApprovalStore":
        return cls(os.getenv("SUDARSHAN_LINKEDIN_APPROVAL_DB_PATH", "artifacts/.state/social_approvals.db"))

    def create_pending(
        self,
        request: SocialRequest,
        *,
        authorization_scope: Mapping[str, Any],
        actor_id: str,
        policy_decision: str = "pending",
    ) -> SocialApprovalRecord:
        _validate_write_request(request)
        scope_hash = _scope_hash(authorization_scope)
        payload_hash = _request_payload_hash(request)
        idempotency_key = _required_text(request.idempotency_key, "idempotency_key", 200)
        actor = _required_text(actor_id, "actor_id", 200)
        now = time()
        with self._lock:
            existing = self._connection.execute(
                "SELECT * FROM social_approvals WHERE scope_hash = ? AND idempotency_key = ?",
                (scope_hash, idempotency_key),
            ).fetchone()
            if existing is not None:
                record = _row_to_record(existing)
                _ensure_same_action(record, request, payload_hash, scope_hash)
                return record
            approval_id = f"approval-{uuid4().hex}"
            self._connection.execute(
                """
                INSERT INTO social_approvals
                    (approval_id, operation, provider, target_ref, payload_hash, scope_hash,
                     actor_id, policy_decision, idempotency_key, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    approval_id, request.operation, request.provider, request.target_ref,
                    payload_hash, scope_hash, actor, policy_decision, idempotency_key, now, now,
                ),
            )
            self._connection.commit()
            return self._get_locked(approval_id)  # type: ignore[return-value]

    def approve(self, approval_id: str, *, actor_id: str, policy_decision: str = "approved") -> SocialApprovalRecord:
        actor = _required_text(actor_id, "actor_id", 200)
        decision = _required_text(policy_decision, "policy_decision", 80)
        if decision != "approved":
            raise SocialApprovalConflict("approval requires policy_decision=approved")
        with self._lock:
            record = self._get_locked(approval_id)
            if record is None:
                raise SocialApprovalConflict("approval not found")
            if record.status == "approved":
                return record
            if record.status != "pending":
                raise SocialApprovalConflict(f"approval cannot transition from {record.status}")
            now = time()
            self._connection.execute(
                "UPDATE social_approvals SET actor_id = ?, policy_decision = ?, status = 'approved', updated_at = ? WHERE approval_id = ?",
                (actor, decision, now, approval_id),
            )
            self._connection.commit()
            return self._get_locked(approval_id)  # type: ignore[return-value]

    def reject(self, approval_id: str, *, actor_id: str, policy_decision: str = "rejected") -> SocialApprovalRecord:
        actor = _required_text(actor_id, "actor_id", 200)
        decision = _required_text(policy_decision, "policy_decision", 80)
        with self._lock:
            record = self._get_locked(approval_id)
            if record is None:
                raise SocialApprovalConflict("approval not found")
            if record.status == "rejected":
                return record
            if record.status != "pending":
                raise SocialApprovalConflict(f"approval cannot transition from {record.status}")
            now = time()
            self._connection.execute(
                "UPDATE social_approvals SET actor_id = ?, policy_decision = ?, status = 'rejected', updated_at = ? WHERE approval_id = ?",
                (actor, decision, now, approval_id),
            )
            self._connection.commit()
            return self._get_locked(approval_id)  # type: ignore[return-value]

    def cancel(self, approval_id: str, *, actor_id: str) -> SocialApprovalRecord:
        """Cancel an approval before provider release is claimed."""

        actor = _required_text(actor_id, "actor_id", 200)
        with self._lock:
            record = self._get_locked(approval_id)
            if record is None:
                raise SocialApprovalConflict("approval not found")
            if record.status == "cancelled":
                return record
            if record.status not in {"pending", "approved"}:
                raise SocialApprovalConflict(f"approval cannot be cancelled from {record.status}")
            now = time()
            self._connection.execute(
                "UPDATE social_approvals SET actor_id = ?, policy_decision = 'cancelled', status = 'cancelled', updated_at = ? WHERE approval_id = ?",
                (actor, now, approval_id),
            )
            self._connection.commit()
            return self._get_locked(approval_id)  # type: ignore[return-value]

    def claim_release(self, approval_id: str, *, worker_id: str, lease_seconds: float = 300.0) -> SocialApprovalRecord | None:
        worker = _required_text(worker_id, "worker_id", 200)
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        now = time()
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            record = self._get_locked(approval_id)
            if record is None:
                self._connection.rollback()
                raise SocialApprovalConflict("approval not found")
            if record.status in {"succeeded", "failed", "cancelled", "draft_only"}:
                self._connection.commit()
                return record
            if record.status not in {"approved", "provider_pending"} and not (
                record.status == "releasing" and self._lease_expired_locked(approval_id, now)
            ):
                self._connection.commit()
                return None
            self._connection.execute(
                "UPDATE social_approvals SET status = 'releasing', lease_owner = ?, lease_expires_at = ?, updated_at = ? WHERE approval_id = ?",
                (worker, now + lease_seconds, now, approval_id),
            )
            self._connection.commit()
            return self._get_locked(approval_id)

    def save_receipt(self, approval_id: str, *, worker_id: str, receipt: SocialReceipt) -> SocialApprovalRecord:
        safe = receipt.to_dict()
        safe["data"] = sanitize_social_mapping(receipt.data)
        safe["metadata"] = sanitize_social_mapping(receipt.metadata)
        status = receipt.status
        if status == "pending":
            status = "provider_pending"
        with self._lock:
            record = self._get_locked(approval_id)
            if record is None:
                raise SocialApprovalConflict("approval not found")
            if record.status in {"succeeded", "failed", "cancelled", "draft_only"}:
                return record
            if record.status != "releasing":
                raise SocialApprovalConflict(f"approval is not being released: {record.status}")
            row = self._connection.execute(
                "SELECT lease_owner FROM social_approvals WHERE approval_id = ?", (approval_id,)
            ).fetchone()
            if row["lease_owner"] != worker_id:
                raise SocialApprovalConflict("release lease is owned by another worker")
            now = time()
            self._connection.execute(
                "UPDATE social_approvals SET status = ?, provider_request_id = ?, receipt_json = ?, lease_owner = NULL, lease_expires_at = NULL, updated_at = ? WHERE approval_id = ?",
                (status, receipt.provider_request_id, json.dumps(safe, sort_keys=True), now, approval_id),
            )
            self._connection.commit()
            return self._get_locked(approval_id)  # type: ignore[return-value]

    def reconcile_pending(
        self,
        approval_id: str,
        *,
        status: Literal["pending", "succeeded", "failed"],
        receipt: SocialReceipt | None = None,
        next_check_delay: float = 30.0,
    ) -> SocialApprovalRecord:
        with self._lock:
            record = self._get_locked(approval_id)
            if record is None:
                raise SocialApprovalConflict("approval not found")
            if record.status != "provider_pending":
                return record
            now = time()
            target_status = "provider_pending" if status == "pending" else status
            receipt_json = record.receipt
            provider_req_id = record.provider_request_id
            if receipt is not None:
                safe = receipt.to_dict()
                safe["data"] = sanitize_social_mapping(receipt.data)
                safe["metadata"] = sanitize_social_mapping(receipt.metadata)
                receipt_json = safe
                if receipt.provider_request_id:
                    provider_req_id = receipt.provider_request_id

            lease_expires = (now + next_check_delay) if status == "pending" else None
            self._connection.execute(
                """
                UPDATE social_approvals
                SET status = ?,
                    provider_request_id = ?,
                    receipt_json = ?,
                    lease_owner = NULL,
                    lease_expires_at = ?,
                    updated_at = ?
                WHERE approval_id = ?
                """,
                (
                    target_status,
                    provider_req_id,
                    json.dumps(receipt_json, sort_keys=True) if receipt_json is not None else None,
                    lease_expires,
                    now,
                    approval_id,
                ),
            )
            self._connection.commit()
            return self._get_locked(approval_id)  # type: ignore[return-value]

    def get(self, approval_id: str) -> SocialApprovalRecord | None:
        with self._lock:
            return self._get_locked(approval_id)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _get_locked(self, approval_id: str) -> SocialApprovalRecord | None:
        row = self._connection.execute(
            "SELECT * FROM social_approvals WHERE approval_id = ?", (approval_id,)
        ).fetchone()
        return _row_to_record(row) if row is not None else None

    def _lease_expired_locked(self, approval_id: str, now: float) -> bool:
        row = self._connection.execute(
            "SELECT lease_expires_at FROM social_approvals WHERE approval_id = ?", (approval_id,)
        ).fetchone()
        return row is not None and (row["lease_expires_at"] is None or float(row["lease_expires_at"]) <= now)


class SocialReleaseService:
    """Approval-gated social write service with restart-safe idempotency."""

    def __init__(self, boundary: SocialCapabilityBoundary, store: SocialApprovalStore) -> None:
        self.boundary = boundary
        self.store = store

    def submit_post(self, request: SocialRequest, *, authorization_scope: Mapping[str, Any], actor_id: str) -> SocialApprovalRecord:
        return self._submit("create_post", request, authorization_scope=authorization_scope, actor_id=actor_id)

    def submit_comment(self, request: SocialRequest, *, authorization_scope: Mapping[str, Any], actor_id: str) -> SocialApprovalRecord:
        return self._submit("create_comment", request, authorization_scope=authorization_scope, actor_id=actor_id)

    def submit_reply(self, request: SocialRequest, *, authorization_scope: Mapping[str, Any], actor_id: str) -> SocialApprovalRecord:
        return self._submit("create_reply", request, authorization_scope=authorization_scope, actor_id=actor_id)

    def submit_reshare(self, request: SocialRequest, *, authorization_scope: Mapping[str, Any], actor_id: str) -> SocialApprovalRecord:
        return self._submit("create_reshare", request, authorization_scope=authorization_scope, actor_id=actor_id)

    def submit_schedule(self, request: SocialRequest, *, authorization_scope: Mapping[str, Any], actor_id: str) -> SocialApprovalRecord:
        return self._submit("schedule_post", request, authorization_scope=authorization_scope, actor_id=actor_id)

    def approve(self, approval_id: str, *, actor_id: str) -> SocialApprovalRecord:
        return self.store.approve(approval_id, actor_id=actor_id)

    def reject(self, approval_id: str, *, actor_id: str) -> SocialApprovalRecord:
        return self.store.reject(approval_id, actor_id=actor_id)

    def release(
        self,
        approval_id: str,
        request: SocialRequest,
        *,
        authorization_scope: Mapping[str, Any],
        worker_id: str,
        cancel_event: Any = None,
    ) -> SocialReceipt:
        record = self.store.get(approval_id)
        if record is None:
            return _release_error(request, "SOCIAL_APPROVAL_NOT_FOUND", approval_id)
        try:
            _ensure_same_action(record, request, _request_payload_hash(request), _scope_hash(authorization_scope))
        except (TypeError, ValueError, SocialApprovalConflict) as error:
            return _release_error(request, "SOCIAL_APPROVAL_PAYLOAD_MISMATCH", str(error))
        if record.status == "rejected":
            return _release_error(request, "SOCIAL_APPROVAL_REJECTED", approval_id)
        if record.status == "cancelled":
            return _release_error(request, "SOCIAL_APPROVAL_CANCELLED", approval_id)
        if record.status in {"succeeded", "failed", "cancelled", "draft_only"} and record.receipt:
            return _receipt_from_dict(record.receipt)
        if record.status == "releasing":
            return _release_error(request, "SOCIAL_PROVIDER_PENDING", approval_id)
        if record.status not in {"approved", "provider_pending"}:
            return _release_error(request, "SOCIAL_APPROVAL_REQUIRED", approval_id)
        claimed = self.store.claim_release(approval_id, worker_id=worker_id)
        if claimed is None:
            current = self.store.get(approval_id)
            if current and current.receipt:
                return _receipt_from_dict(current.receipt)
            return _release_error(request, "SOCIAL_PROVIDER_PENDING", approval_id)
        # A provider_pending record keeps its last receipt for projection, but
        # that receipt is not terminal: the new release lease must retry the
        # provider. Terminal records return their stored receipt above.
        if claimed.receipt and record.status != "provider_pending":
            return _receipt_from_dict(claimed.receipt)
        receipt = self.boundary.execute(
            replace(request, approval_id=approval_id), cancel_event=cancel_event
        )
        self.store.save_receipt(approval_id, worker_id=worker_id, receipt=receipt)
        return receipt

    def reconcile_provider_pending(
        self,
        approval_id: str,
        *,
        check_fn: Callable[[SocialApprovalRecord], tuple[str, SocialReceipt | None]],
        next_check_delay: float = 30.0,
    ) -> SocialApprovalRecord:
        """Reconcile a provider_pending approval using check_fn without re-releasing the post."""
        record = self.store.get(approval_id)
        if record is None:
            raise SocialApprovalConflict("approval not found")
        if record.status != "provider_pending":
            return record
        provider_status, receipt = check_fn(record)
        if provider_status not in {"pending", "succeeded", "failed"}:
            raise ValueError(f"invalid provider_status from check_fn: {provider_status}")
        return self.store.reconcile_pending(
            approval_id,
            status=provider_status,  # type: ignore[arg-type]
            receipt=receipt,
            next_check_delay=next_check_delay,
        )

    def _submit(self, operation: str, request: SocialRequest, *, authorization_scope: Mapping[str, Any], actor_id: str) -> SocialApprovalRecord:
        if request.operation != operation:
            request = replace(request, operation=operation)  # type: ignore[arg-type]
        return self.store.create_pending(request, authorization_scope=authorization_scope, actor_id=actor_id)


def _validate_write_request(request: SocialRequest) -> None:
    if request.operation not in WRITE_OPERATIONS:
        raise SocialApprovalConflict("approval is only available for social write operations")


def _request_payload_hash(request: SocialRequest) -> str:
    return _hash({
        "operation": request.operation, "provider": request.provider,
        "target_ref": request.target_ref, "payload": request.payload,
        "scheduled_for": request.scheduled_for.isoformat() if request.scheduled_for else None,
    })


def _scope_hash(scope: Mapping[str, Any]) -> str:
    if not scope:
        raise ValueError("authorization scope is required")
    if any("token" in str(key).lower() or "secret" in str(key).lower() for key in scope):
        raise ValueError("authorization scope contains a secret-shaped field")
    return _hash(scope)


def _ensure_same_action(record: SocialApprovalRecord, request: SocialRequest, payload_hash: str, scope_hash: str) -> None:
    if record.operation != request.operation or record.provider != request.provider or record.target_ref != request.target_ref:
        raise SocialApprovalConflict("approval action does not match request")
    if record.payload_hash != payload_hash or record.scope_hash != scope_hash:
        raise SocialApprovalConflict("approved payload or scope does not match request")
    if record.idempotency_key != request.idempotency_key:
        raise SocialApprovalConflict("idempotency key does not match approval")


def _row_to_record(row: sqlite3.Row) -> SocialApprovalRecord:
    raw_receipt = row["receipt_json"]
    receipt = json.loads(raw_receipt) if raw_receipt else None
    return SocialApprovalRecord(
        approval_id=str(row["approval_id"]), operation=str(row["operation"]), provider=str(row["provider"]),
        target_ref=str(row["target_ref"]), payload_hash=str(row["payload_hash"]), scope_hash=str(row["scope_hash"]),
        actor_id=str(row["actor_id"]), policy_decision=str(row["policy_decision"]),
        idempotency_key=str(row["idempotency_key"]), status=str(row["status"]),
        provider_request_id=str(row["provider_request_id"]) if row["provider_request_id"] else None,
        receipt=receipt, created_at=float(row["created_at"]), updated_at=float(row["updated_at"]),
    )


def _receipt_from_dict(value: Mapping[str, Any]) -> SocialReceipt:
    return SocialReceipt(
        receipt_id=str(value.get("receipt_id", "social-replayed")), provider=str(value.get("provider", "unknown")),
        operation=value.get("operation", "create_post"), status=value.get("status", "failed"),
        target_ref=str(value.get("target_ref", "")), request_id=value.get("request_id"),
        provider_request_id=value.get("provider_request_id"), failure_class=value.get("failure_class"),
        error_code=value.get("error_code"), retry_after_seconds=value.get("retry_after_seconds"),
        manual_required=bool(value.get("manual_required", False)), approval_id=value.get("approval_id"),
        audit_ref=value.get("audit_ref"), data=value.get("data") if isinstance(value.get("data"), Mapping) else {},
        metadata=value.get("metadata") if isinstance(value.get("metadata"), Mapping) else {},
    )


def _release_error(request: SocialRequest, code: str, detail: str) -> SocialReceipt:
    return SocialReceipt(
        receipt_id=f"social-release-error-{uuid4().hex}", provider=request.provider,
        operation=request.operation, status="failed", target_ref=request.target_ref,
        error_code=code, approval_id=request.approval_id, metadata={"detail": detail},
    )


def _required_text(value: str, name: str, maximum: int) -> str:
    text = str(value).strip()
    if not text or len(text) > maximum:
        raise ValueError(f"{name} must be 1-{maximum} characters")
    return text


def _hash(value: Any) -> str:
    encoded = json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _canonical(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


__all__ = ["SocialApprovalConflict", "SocialApprovalRecord", "SocialApprovalStore", "SocialReleaseService"]
