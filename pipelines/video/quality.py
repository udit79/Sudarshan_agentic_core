"""Deterministic rendered-video integrity checks."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class VideoQualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quality_report_id: str = Field(min_length=1)
    status: str
    checks: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    output_path: str | None = None
    expected_duration_seconds: float | None = None
    actual_duration_seconds: float | None = None


def inspect_video(
    output_path: str | Path,
    *,
    expected_duration_seconds: float | None = None,
    subtitle_path: str | Path | None = None,
) -> VideoQualityReport:
    """Inspect only deterministic media facts; never use a model critic."""

    path = Path(output_path)
    identity = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:20]
    checks: dict[str, Any] = {"exists": path.is_file() and path.stat().st_size > 0 if path.exists() else False}
    warnings: list[str] = []
    failures: list[str] = []
    actual_duration: float | None = None

    if not checks["exists"]:
        failures.append("output_missing_or_empty")
    ffprobe = shutil.which("ffprobe")
    if checks["exists"] and ffprobe:
        try:
            result = subprocess.run(
                [ffprobe, "-v", "quiet", "-show_streams", "-show_format", "-of", "json", str(path)],
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
            )
            payload = json.loads(result.stdout or "{}")
            streams = list(payload.get("streams") or [])
            checks["video_stream"] = any(item.get("codec_type") == "video" for item in streams)
            checks["audio_stream"] = any(item.get("codec_type") == "audio" for item in streams)
            actual_duration = float((payload.get("format") or {}).get("duration") or 0.0) or None
            checks["duration"] = actual_duration is not None
            if not checks["video_stream"]:
                failures.append("video_stream_missing")
            if expected_duration_seconds and actual_duration is not None:
                tolerance = max(0.5, expected_duration_seconds * 0.08)
                checks["duration_within_tolerance"] = abs(actual_duration - expected_duration_seconds) <= tolerance
                if not checks["duration_within_tolerance"]:
                    failures.append("duration_out_of_bounds")
        except Exception:
            failures.append("ffprobe_failed")
    elif checks["exists"]:
        warnings.append("ffprobe_unavailable")

    if subtitle_path is not None:
        subtitle_exists = Path(subtitle_path).is_file()
        checks["subtitle_sidecar"] = subtitle_exists
        if not subtitle_exists:
            warnings.append("subtitle_sidecar_missing")

    status = "failed" if failures else "partial" if warnings else "passed"
    return VideoQualityReport(
        quality_report_id=f"video-quality:{identity}",
        status=status,
        checks=checks,
        warnings=warnings,
        failures=failures,
        output_path=str(path),
        expected_duration_seconds=expected_duration_seconds,
        actual_duration_seconds=actual_duration,
    )


__all__ = ["VideoQualityReport", "inspect_video"]
