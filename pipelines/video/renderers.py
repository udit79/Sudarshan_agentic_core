"""Renderer adapters that preserve Sudarshan's package boundary."""

from __future__ import annotations

from pathlib import Path
from threading import Event
from typing import Mapping, Protocol, Sequence

from pipelines.video.contracts import VideoPackage
from pipelines.video.native_generator import NativeVideoGenerator, NativeVideoResult, VideoScene


class VideoRenderer(Protocol):
    renderer_id: str

    def render(
        self,
        package: VideoPackage,
        scenes: Sequence[VideoScene],
        *,
        run_id: str,
        cancel_event: Event | None = None,
        authorization_scope: Mapping[str, object] | None = None,
    ) -> NativeVideoResult:
        ...


class MoneyPrinterCompatibleRenderer:
    """Use adapted material/subtitle/audio/composition capabilities in-process.

    This is intentionally not MoneyPrinterTurbo's orchestrator or WebUI. The
    Sudarshan package, runtime, budget, and quality boundaries remain in charge.
    """

    renderer_id = "video.moneyprinter-compatible"

    def __init__(self, generator: NativeVideoGenerator | None = None) -> None:
        self.generator = generator or NativeVideoGenerator(renderer_version="moneyprinter-compatible@1")

    def render(
        self,
        package: VideoPackage,
        scenes: Sequence[VideoScene],
        *,
        attempt_id: str = "1",
        run_id: str,
        cancel_event: Event | None = None,
        authorization_scope: Mapping[str, object] | None = None,
    ) -> NativeVideoResult:
        return self.generator.generate(
            subject=package.subject,
            scenes=scenes,
            attempt_id=attempt_id,
            artifact_name=f"video-{run_id}",
            package_dir=Path("artifacts") / "videos" / str(run_id),
            cancel_event=cancel_event,
            authorization_scope=authorization_scope,
            provider_options=package.provider_options.model_dump(exclude_none=True),
            video_source=package.video_source,
        )


__all__ = ["MoneyPrinterCompatibleRenderer", "VideoRenderer"]
