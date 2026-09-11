"""OpenAI-native video generation boundary with optional legacy compatibility."""

from pipelines.video.pipeline import VideoPipeline
from pipelines.video.contracts import (
    MediaUsageRecord,
    MusicTrack,
    SubtitleTrack,
    VideoAsset,
    VideoPackage,
    VideoScene,
    VideoRunManifest,
    VideoSceneManifest,
)
from pipelines.video.planner import OpenAIVideoPlanner, VideoPlanningError
from pipelines.video.skills import NativeVideoRenderSkill, NativeVideoStoryboardSkill
from pipelines.video.quality import VideoQualityReport, inspect_video
from pipelines.video.evaluation import VideoBenchmarkObservation, VideoBenchmarkReport, benchmark_video_observations
from pipelines.video.renderers import MoneyPrinterCompatibleRenderer, VideoRenderer
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
    "VideoAsset",
    "SubtitleTrack",
    "MusicTrack",
    "MediaUsageRecord",
    "VideoRunManifest",
    "VideoSceneManifest",
    "NativeVideoRenderSkill",
    "NativeVideoStoryboardSkill",
    "OpenAIVideoPlanner",
    "VideoPlanningError",
    "VideoQualityReport",
    "inspect_video",
    "VideoBenchmarkObservation",
    "VideoBenchmarkReport",
    "benchmark_video_observations",
    "MoneyPrinterCompatibleRenderer",
    "VideoRenderer",
]
