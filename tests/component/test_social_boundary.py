from __future__ import annotations

from threading import Event

from integrations.providers.social import SocialCapabilityBoundary, SocialRequest


def test_manual_mode_never_publishes_and_returns_typed_draft_receipt() -> None:
    receipt = SocialCapabilityBoundary().execute(
        SocialRequest(operation="create_post", payload={"text": "draft"})
    )

    assert receipt.status == "approval_required"
    assert receipt.error_code == "SOCIAL_APPROVAL_REQUIRED"

    approved = SocialCapabilityBoundary().execute(
        SocialRequest(operation="create_post", payload={"text": "draft"}, approval_id="approval-1")
    )
    assert approved.status == "draft_only"
    assert approved.manual_required is True


def test_reads_without_provider_fall_back_to_manual_boundary() -> None:
    receipt = SocialCapabilityBoundary().execute(
        SocialRequest(operation="fetch_thread", target_ref="urn:thread:1")
    )

    assert receipt.status == "draft_only"
    assert receipt.error_code is None
    assert receipt.manual_required is True


def test_cancelled_social_operation_never_calls_provider() -> None:
    cancelled = Event()
    cancelled.set()
    receipt = SocialCapabilityBoundary().execute(
        SocialRequest(operation="fetch_post", target_ref="urn:post:1"),
        cancel_event=cancelled,
    )

    assert receipt.status == "cancelled"
