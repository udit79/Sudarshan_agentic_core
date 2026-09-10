"""OpenAI-native video generation boundary with optional legacy compatibility."""

from pipelines.video.pipeline import VideoPipeline
from pipelines.video.contracts import VideoPackage, VideoScene, VideoRunManifest, VideoSceneManifest
from pipelines.video.planner import OpenAIVideoPlanner, VideoPlanningError
from pipelines.video.skills import NativeVideoRenderSkill, NativeVideoStoryboardSkill
from integrations.providers.moneyprinterturbo.client import (
    MoneyPrinterTurboClient,
    MoneyPrinterTurboError,
    VideoJobResult,
)

__all__ = [
    "MoneyPrinterTurboClient",
    "MoneyPrinterTurboError",
    "VideoJobResult",
    "VideoPipeline",
    "VideoPackage",
    "VideoScene",
    "VideoRunManifest",
    "VideoSceneManifest",
    "NativeVideoRenderSkill",
    "NativeVideoStoryboardSkill",
    "OpenAIVideoPlanner",
    "VideoPlanningError",
]
