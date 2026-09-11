"""Renderer-neutral deterministic checks for delivered visual artifacts.

This is deliberately a conservative gate: it validates that a renderer emitted
an intact artifact and that required, already-approved text is present. It does
not claim that an image is aesthetically good; model/human review remains a
separate signal.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Literal
from zipfile import BadZipFile, ZipFile

from pydantic import BaseModel, ConfigDict, Field


ArtifactKind = Literal["svg", "png", "jpg", "jpeg", "pdf", "pptx", "video", "other"]


class VisualArtifactReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool
    path: str
    kind: ArtifactKind
    renderer_version: str = "unknown"
    issues: list[str] = Field(default_factory=list)
    required_text: list[str] = Field(default_factory=list)
    width: int | None = None
    height: int | None = None
    byte_size: int = 0


class RendererPromotionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool
    renderer_version: str
    artifact_count: int = Field(ge=0)
    failed_artifacts: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


def inspect_visual_artifact(
    path: str | Path,
    *,
    kind: ArtifactKind | None = None,
    required_text: Iterable[str] = (),
    renderer_version: str = "unknown",
) -> VisualArtifactReport:
    """Inspect one renderer output without invoking a model or a shell."""

    artifact = Path(path)
    resolved_kind = kind or _kind_from_suffix(artifact.suffix)
    required = [str(value) for value in required_text]
    issues: list[str] = []
    width = height = None
    size = artifact.stat().st_size if artifact.is_file() else 0

    if not artifact.is_file():
        issues.append("artifact is missing")
    elif size == 0:
        issues.append("artifact is empty")
    elif resolved_kind == "svg":
        from pipelines.infographic.quality import inspect_svg

        report = inspect_svg(artifact, required_text=tuple(required), renderer_mode=renderer_version)
        issues.extend(report.issues)
        width, height = report.width, report.height
    elif resolved_kind in {"png", "jpg", "jpeg"}:
        width, height = _inspect_raster(artifact, issues)
        _check_required_text(required, "", issues)
    elif resolved_kind == "pptx":
        _inspect_pptx(artifact, required, issues)
    elif resolved_kind == "pdf":
        _inspect_pdf(artifact, required, issues)
    elif resolved_kind == "video":
        # A non-empty file is the portable baseline. Codec/duration checks are
        # renderer-specific and should be supplied by the video adapter.
        pass

    return VisualArtifactReport(
        approved=not issues,
        path=str(artifact),
        kind=resolved_kind,
        renderer_version=renderer_version,
        issues=issues,
        required_text=required,
        width=width,
        height=height,
        byte_size=size,
    )


def evaluate_renderer_promotion(
    reports: Iterable[VisualArtifactReport],
    *,
    renderer_version: str,
) -> RendererPromotionReport:
    """Promote a renderer only when every staged artifact passes the gate."""

    items = list(reports)
    failed = [item.path for item in items if not item.approved]
    issues = [f"{item.path}: {issue}" for item in items for issue in item.issues]
    if not items:
        issues.append("no staged visual artifacts were supplied")
    return RendererPromotionReport(
        approved=bool(items) and not failed,
        renderer_version=renderer_version,
        artifact_count=len(items),
        failed_artifacts=failed,
        issues=issues,
    )


def _kind_from_suffix(suffix: str) -> ArtifactKind:
    return {
        ".svg": "svg",
        ".png": "png",
        ".jpg": "jpg",
        ".jpeg": "jpeg",
        ".pdf": "pdf",
        ".pptx": "pptx",
        ".mp4": "video",
        ".webm": "video",
        ".mov": "video",
    }.get(suffix.lower(), "other")  # type: ignore[return-value]


def _inspect_raster(path: Path, issues: list[str]) -> tuple[int | None, int | None]:
    try:
        from PIL import Image

        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            return int(image.width), int(image.height)
    except ImportError:
        issues.append("Pillow is required for raster integrity checks")
    except Exception as exc:  # pragma: no cover - codec-specific error text
        issues.append(f"raster integrity check failed: {exc}")
    return None, None


def _inspect_pptx(path: Path, required: list[str], issues: list[str]) -> None:
    try:
        with ZipFile(path) as archive:
            names = set(archive.namelist())
            if "[Content_Types].xml" not in names or "ppt/presentation.xml" not in names:
                issues.append("PPTX package is missing required presentation parts")
            text = "\n".join(
                archive.read(name).decode("utf-8", errors="ignore")
                for name in names
                if name.startswith("ppt/slides/slide") and name.endswith(".xml")
            )
            _check_required_text(required, text, issues)
    except (BadZipFile, OSError) as exc:
        issues.append(f"PPTX package is unreadable: {exc}")


def _inspect_pdf(path: Path, required: list[str], issues: list[str]) -> None:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        if not reader.pages:
            issues.append("PDF has no pages")
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        _check_required_text(required, text, issues)
    except ImportError:
        issues.append("pypdf is required for PDF integrity checks")
    except Exception as exc:  # pragma: no cover - parser-specific error text
        issues.append(f"PDF integrity check failed: {exc}")


def _check_required_text(required: list[str], text: str, issues: list[str]) -> None:
    for value in required:
        if value not in text:
            issues.append(f"required visible text is missing: {value}")


__all__ = [
    "RendererPromotionReport",
    "VisualArtifactReport",
    "evaluate_renderer_promotion",
    "inspect_visual_artifact",
]
