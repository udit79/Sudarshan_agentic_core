"""Bounded, scoped read operations for optional social connectors."""

from __future__ import annotations

import os
from threading import Event
from typing import Any, Mapping

from integrations.providers.social import READ_OPERATIONS, SocialCapabilityBoundary, SocialReceipt, SocialRequest
from integrations.providers.social_cache import (
    SocialReadCache,
    build_social_read_fingerprint,
    sanitize_social_mapping,
)
from integrations.providers.social_config import SocialProviderConfig


class SocialReadLayer:
    """Execute and cache provider-neutral post/comment/thread reads."""

    def __init__(
        self,
        boundary: SocialCapabilityBoundary | None = None,
        *,
        cache: SocialReadCache | None = None,
        config: SocialProviderConfig | None = None,
        skill_version: str = "1.0.0",
        policy_version: str = "1.0.0",
    ) -> None:
        self.config = config or SocialProviderConfig.from_env()
        self.boundary = boundary or SocialCapabilityBoundary(config=self.config)
        self.cache = cache or SocialReadCache(
            os.getenv("SUDARSHAN_LINKEDIN_CACHE_DB_PATH", "artifacts/.state/linkedin_read_cache.db")
        )
        self.skill_version = skill_version
        self.policy_version = policy_version

    def fetch_post(self, target_ref: str, **kwargs: Any) -> SocialReceipt:
        return self._fetch("fetch_post", target_ref, **kwargs)

    def fetch_comments(self, target_ref: str, **kwargs: Any) -> SocialReceipt:
        return self._fetch("fetch_comments", target_ref, **kwargs)

    def fetch_thread(self, target_ref: str, **kwargs: Any) -> SocialReceipt:
        return self._fetch("fetch_thread", target_ref, **kwargs)

    def invalidate(self, target_ref: str, *, provider: str, authorization_scope: Mapping[str, Any]) -> int:
        return self.cache.invalidate(
            provider=provider, target_ref=target_ref, authorization_scope=authorization_scope
        )

    def _fetch(
        self,
        operation: str,
        target_ref: str,
        *,
        provider: str | None = None,
        request_params: Mapping[str, Any] | None = None,
        authorization_scope: Mapping[str, Any] | None = None,
        skill_id: str = "linkedin.post",
        skill_version: str | None = None,
        policy_version: str | None = None,
        cancel_event: Event | None = None,
    ) -> SocialReceipt:
        if operation not in READ_OPERATIONS:
            raise ValueError(f"unsupported social read operation: {operation}")
        if authorization_scope is None:
            return self._error_receipt(operation, target_ref, "SOCIAL_SCOPE_REQUIRED")
        selected_provider = (provider or self.config.effective_provider).strip().lower()
        selected_skill_version = skill_version or self.skill_version
        selected_policy_version = policy_version or self.policy_version
        try:
            fingerprint = build_social_read_fingerprint(
                provider=selected_provider, operation=operation, target_ref=target_ref, request_params=request_params,
                skill_id=skill_id, skill_version=selected_skill_version,
                authorization_scope=authorization_scope, policy_version=selected_policy_version,
            )
        except (TypeError, ValueError) as error:
            return self._error_receipt(operation, target_ref, "SOCIAL_SCOPE_INVALID", str(error))

        cached = self.cache.get(fingerprint)
        if cached is not None:
            return SocialReceipt(
                receipt_id=f"social-cache-{fingerprint[:16]}", provider=cached.provider,
                operation=operation, status="succeeded", target_ref=target_ref, data=cached.data,
                metadata={
                    "cache_hit": True, "untrusted_data": True,
                    "provenance": dict(cached.provenance), "scope_hash": cached.scope_hash,
                    "skill_version": cached.skill_version, "policy_version": cached.policy_version,
                },
            )

        receipt = self.boundary.execute(
            SocialRequest(
                operation=operation, target_ref=target_ref, payload=request_params or {},
                provider=selected_provider, case_id=str(authorization_scope.get("case_id", "")),
                skill_id=skill_id, timeout_seconds=self.config.timeout_seconds,
            ),
            cancel_event=cancel_event,
        )
        if receipt.status != "succeeded":
            return receipt
        provenance = receipt.metadata.get("provenance", {})
        if not isinstance(provenance, Mapping):
            provenance = {}
        try:
            safe_data = sanitize_social_mapping(receipt.data)
            safe_provenance = sanitize_social_mapping(provenance)
            entry = self.cache.put(
                fingerprint=fingerprint, provider=selected_provider, operation=operation,
                target_ref=target_ref, data=safe_data, provenance=safe_provenance,
                authorization_scope=authorization_scope, skill_version=selected_skill_version,
                policy_version=selected_policy_version, ttl_seconds=self.config.cache_ttl_seconds,
            )
        except (TypeError, ValueError):
            return receipt
        metadata = dict(receipt.metadata)
        metadata.update({
            "cache_hit": False, "untrusted_data": True,
            "cache_fingerprint": entry.fingerprint, "scope_hash": entry.scope_hash,
        })
        return SocialReceipt(
            receipt_id=receipt.receipt_id, provider=receipt.provider, operation=receipt.operation,
            status=receipt.status, target_ref=receipt.target_ref, request_id=receipt.request_id,
            provider_request_id=receipt.provider_request_id, failure_class=receipt.failure_class,
            error_code=receipt.error_code, retry_after_seconds=receipt.retry_after_seconds,
            manual_required=receipt.manual_required, approval_id=receipt.approval_id,
            audit_ref=receipt.audit_ref, data=safe_data, metadata=metadata,
        )

    @staticmethod
    def _error_receipt(operation: str, target_ref: str, code: str, detail: str | None = None) -> SocialReceipt:
        return SocialReceipt(
            receipt_id="social-read-error", provider="manual", operation=operation,
            status="failed", target_ref=target_ref, error_code=code,
            metadata={"detail": detail} if detail else {},
        )


__all__ = ["SocialReadLayer"]
