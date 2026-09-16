"""Native video skills used by the Sudarshan video pipeline.

These are application-owned skills, not provider wrappers.  The storyboard
skill produces a provider-neutral ``VideoPackage`` and the render skill turns
that package into a durable native media bundle.  External workers may be
mounted behind an explicit compatibility adapter, but they are not part of
the default skill path.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from threading import Event
from typing import Any, Mapping

from pipelines.common.contracts import AdvisoryRequest
from pipelines.video.contracts import VideoPackage
from pipelines.video.native_generator import NativeVideoGenerator, NativeVideoResult, scenes_from_package, scenes_from_script
from pipelines.video.planner import OpenAIVideoPlanner
from pipelines.video.renderers import MoneyPrinterCompatibleRenderer


class NativeVideoStoryboardSkill:
    """Create or validate a provider-neutral storyboard package."""

    skill_id = "video.storyboard"
    version = "2.0"

    def __init__(self, planner: OpenAIVideoPlanner) -> None:
        self.planner = planner

    def prepare(
        self,
        request: AdvisoryRequest,
        *,
        subject: str,
        memory_context: str,
        package_data: Mapping[str, Any] | None = None,
        prefer_query_script: bool = False,
        cancel_event: Event | None = None,
    ) -> tuple[VideoPackage, list[Any]]:
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("video storyboard skill cancelled")
        if isinstance(package_data, Mapping):
            package = VideoPackage.model_validate(package_data)
        else:
            supplied_script = str(request.metadata.get("video_script") or "").strip()[:20_000]
            if prefer_query_script:
                supplied_script = supplied_script or str(memory_context or request.query).strip()[:20_000]
            if supplied_script:
                scenes = scenes_from_script(supplied_script, subject)
                package = VideoPackage(
                    subject=subject,
                    title=subject,
                    script=supplied_script,
                    storyboard=[asdict(scene) if is_dataclass(scene) else scene for scene in scenes],
                )
            else:
                package = self.planner.plan(
                    subject=subject,
                    query=request.query,
                    memory_context=memory_context,
                    prompt_plan=dict(request.metadata.get("prompt_plan") or {}),
                    classification_level=request.classification_level,
                    distribution=request.distribution,
                )
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("video storyboard skill cancelled")
        return package, scenes_from_package(package.model_dump())


class NativeVideoRenderSkill:
    """Render a validated package with native OpenAI/FFmpeg adapters."""

    skill_id = "video.render"
    version = "2.0"

    def __init__(self, generator: NativeVideoGenerator) -> None:
        self.generator = generator
        self.compatible_renderer = MoneyPrinterCompatibleRenderer(generator)

    def render(
        self,
        package: VideoPackage,
        *,
        scenes: list[Any],
        run_id: str,
        attempt_id: str = "1",
        cancel_event: Event | None = None,
        authorization_scope: Mapping[str, Any] | None = None,
    ) -> NativeVideoResult:
        renderer = self.compatible_renderer if package.provider_options.renderer_id == "video.moneyprinter-compatible" else self.generator
        if renderer is self.compatible_renderer:
            return renderer.render(
                package,
                scenes,
                attempt_id=attempt_id,
                run_id=run_id,
                cancel_event=cancel_event,
                authorization_scope=authorization_scope,
            )
        return renderer.generate(
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


__all__ = ["NativeVideoRenderSkill", "NativeVideoStoryboardSkill"]
