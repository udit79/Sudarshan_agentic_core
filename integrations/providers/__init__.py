"""External provider integrations used by Sudarshan pipelines.

Provider modules are intentionally loaded lazily.  Receipts depend on core
orchestrator contracts, so eager package-level imports would recreate the
orchestrator/provider cycle during startup.
"""

from typing import Any

__all__ = ["ManualSocialAdapter", "SocialCapabilityBoundary", "SocialReceipt", "SocialRequest"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from integrations.providers.social import (
            ManualSocialAdapter,
            SocialCapabilityBoundary,
            SocialReceipt,
            SocialRequest,
        )

        return {
            "ManualSocialAdapter": ManualSocialAdapter,
            "SocialCapabilityBoundary": SocialCapabilityBoundary,
            "SocialReceipt": SocialReceipt,
            "SocialRequest": SocialRequest,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
