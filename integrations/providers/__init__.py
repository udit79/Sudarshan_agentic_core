"""External provider integrations used by Sudarshan pipelines.

Provider modules are intentionally loaded lazily.  Receipts depend on core
orchestrator contracts, so eager package-level imports would recreate the
orchestrator/provider cycle during startup.
"""

from typing import Any

__all__ = [
    "ManualSocialAdapter",
    "SocialCapabilityBoundary",
    "SocialProviderConfig",
    "SocialReadCache",
    "SocialReadLayer",
    "SocialApprovalStore",
    "SocialReleaseService",
    "SocialScheduleConflict",
    "SocialScheduleRecord",
    "SocialScheduleService",
    "SocialScheduleStore",
    "SocialMonitorConflict",
    "SocialMonitorRecord",
    "SocialMonitorStore",
    "SocialThreadMonitorService",
    "sanitize_social_mapping",
    "SocialReceipt",
    "SocialRequest",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from integrations.providers.social import (
            ManualSocialAdapter,
            SocialCapabilityBoundary,
            SocialReceipt,
            SocialRequest,
        )
        from integrations.providers.social_config import SocialProviderConfig
        from integrations.providers.social_cache import SocialReadCache
        from integrations.providers.social_read import SocialReadLayer
        from integrations.providers.social_cache import sanitize_social_mapping
        from integrations.providers.social_approval import SocialApprovalStore, SocialReleaseService
        from integrations.providers.social_schedule import (
            SocialScheduleConflict,
            SocialScheduleRecord,
            SocialScheduleService,
            SocialScheduleStore,
        )
        from integrations.providers.social_monitor import (
            SocialMonitorConflict,
            SocialMonitorRecord,
            SocialMonitorStore,
            SocialThreadMonitorService,
        )

        return {
            "ManualSocialAdapter": ManualSocialAdapter,
            "SocialCapabilityBoundary": SocialCapabilityBoundary,
            "SocialReceipt": SocialReceipt,
            "SocialRequest": SocialRequest,
            "SocialProviderConfig": SocialProviderConfig,
            "SocialReadCache": SocialReadCache,
            "SocialReadLayer": SocialReadLayer,
            "sanitize_social_mapping": sanitize_social_mapping,
            "SocialApprovalStore": SocialApprovalStore,
            "SocialReleaseService": SocialReleaseService,
            "SocialScheduleConflict": SocialScheduleConflict,
            "SocialScheduleRecord": SocialScheduleRecord,
            "SocialScheduleService": SocialScheduleService,
            "SocialScheduleStore": SocialScheduleStore,
            "SocialMonitorConflict": SocialMonitorConflict,
            "SocialMonitorRecord": SocialMonitorRecord,
            "SocialMonitorStore": SocialMonitorStore,
            "SocialThreadMonitorService": SocialThreadMonitorService,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
