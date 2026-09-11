"""Small capability registry shared by visual skills and quality gates.

The registry describes renderer ownership and fallback policy. It deliberately
does not instantiate providers or call models; renderers remain ordinary
application adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal


RendererOperation = Literal["render", "export", "inspect", "fallback"]


@dataclass(frozen=True, slots=True)
class RendererCapability:
    renderer_id: str
    version: str
    artifact_kinds: tuple[str, ...]
    operations: frozenset[RendererOperation]
    fallback_renderer_id: str | None = None

    def __post_init__(self) -> None:
        if not self.renderer_id.strip() or not self.version.strip():
            raise ValueError("renderer_id and version are required")
        if not self.artifact_kinds:
            raise ValueError("at least one artifact kind is required")
        if not self.operations:
            raise ValueError("at least one renderer operation is required")
        if self.fallback_renderer_id == self.renderer_id:
            raise ValueError("renderer cannot fall back to itself")


class RendererRegistry:
    """Validated renderer metadata; registration is deterministic and local."""

    def __init__(self, capabilities: Iterable[RendererCapability] = ()) -> None:
        self._capabilities: dict[str, RendererCapability] = {}
        for capability in capabilities:
            self.register(capability)

    def register(self, capability: RendererCapability) -> None:
        if capability.renderer_id in self._capabilities:
            raise ValueError(f"renderer already registered: {capability.renderer_id}")
        self._capabilities[capability.renderer_id] = capability

    def get(self, renderer_id: str) -> RendererCapability:
        try:
            return self._capabilities[renderer_id]
        except KeyError as exc:
            raise KeyError(f"unknown renderer: {renderer_id}") from exc

    def supports(self, renderer_id: str, operation: RendererOperation, artifact_kind: str) -> bool:
        capability = self.get(renderer_id)
        return operation in capability.operations and artifact_kind in capability.artifact_kinds

    def inspect(self, renderer_id: str, path: str | Path, *, required_text: Iterable[str] = ()):
        """Run the shared integrity gate for a registered inspect-capable renderer."""

        capability = self.get(renderer_id)
        if "inspect" not in capability.operations:
            raise ValueError(f"renderer does not support inspection: {renderer_id}")
        from pipelines.common.visual_qa import inspect_visual_artifact

        return inspect_visual_artifact(
            path,
            required_text=required_text,
            renderer_version=f"{capability.renderer_id}@{capability.version}",
        )

    def as_dict(self) -> dict[str, dict[str, object]]:
        return {
            renderer_id: {
                "version": capability.version,
                "artifact_kinds": list(capability.artifact_kinds),
                "operations": sorted(capability.operations),
                "fallback_renderer_id": capability.fallback_renderer_id,
            }
            for renderer_id, capability in sorted(self._capabilities.items())
        }


def default_renderer_registry() -> RendererRegistry:
    """Return the built-in renderer capability set without importing adapters."""

    return RendererRegistry([
        RendererCapability("diagram.native-svg", "1", ("svg",), frozenset({"render", "export", "inspect"})),
        RendererCapability("diagram.pptx", "1", ("pptx",), frozenset({"render", "export", "inspect", "fallback"}), "diagram.native-svg"),
        RendererCapability("infographic.antv", "1", ("svg",), frozenset({"render", "export", "inspect", "fallback"}), "infographic.native-svg"),
        RendererCapability("infographic.native-svg", "1", ("svg",), frozenset({"render", "export", "inspect"})),
        RendererCapability("presentation.pptx", "1", ("pptx",), frozenset({"render", "export", "inspect"})),
        RendererCapability("presentation.ppt-master", "local", ("pptx",), frozenset({"render", "export", "inspect", "fallback"}), "presentation.pptx"),
        RendererCapability("video.ffmpeg", "1", ("video",), frozenset({"render", "export", "inspect"})),
        RendererCapability("video.moneyprinter-compatible", "1", ("video",), frozenset({"render", "export", "inspect", "fallback"}), "video.ffmpeg"),
    ])


__all__ = ["RendererCapability", "RendererOperation", "RendererRegistry", "default_renderer_registry"]
