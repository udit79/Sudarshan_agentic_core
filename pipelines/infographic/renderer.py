"""Python boundary for the AntV Infographic Node SSR renderer."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


class AntVInfographicRenderer:
    """Render validated AntV syntax to SVG through a small Node subprocess."""

    def __init__(
        self,
        *,
        node_binary: str | None = None,
        renderer_script: str | Path | None = None,
        output_dir: str | Path = "artifacts/infographics",
        width: int = 1200,
        height: int = 675,
        timeout_seconds: int | None = None,
        ssr_timeout_ms: int | None = None,
    ) -> None:
        base_dir = Path(__file__).resolve().parent
        self.node_binary = node_binary or os.getenv("ANTV_NODE_BINARY", "node")
        self.renderer_script = Path(renderer_script or base_dir / "antv_renderer" / "render.mjs")
        self.output_dir = Path(output_dir)
        self.width = width
        self.height = height
        self.ssr_timeout_ms = ssr_timeout_ms or int(os.getenv("ANTV_SSR_TIMEOUT_MS", "5000"))
        if self.ssr_timeout_ms < 100:
            raise ValueError("ssr_timeout_ms must be at least 100 milliseconds")
        self.last_render_mode = "unknown"
        self.last_render_warning: str | None = None
        if timeout_seconds is None:
            raw_timeout = os.getenv("ANTV_RENDER_TIMEOUT_SECONDS", "60")
            try:
                timeout_seconds = int(raw_timeout)
            except ValueError as exc:
                raise ValueError("ANTV_RENDER_TIMEOUT_SECONDS must be an integer") from exc
        if timeout_seconds < 1:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds

    def __call__(self, syntax: str, *, artifact_name: str) -> str:
        if not syntax.lstrip().startswith("infographic"):
            raise ValueError("AntV renderer requires infographic syntax")
        payload = json.dumps({
            "syntax": syntax,
            "outputDir": str(self.output_dir.resolve()),
            "artifactName": artifact_name,
            "width": self.width,
            "height": self.height,
            "ssrTimeoutMs": self.ssr_timeout_ms,
        })
        try:
            completed = subprocess.run(
                [self.node_binary, str(self.renderer_script)],
                input=payload,
                text=True,
                capture_output=True,
                check=True,
                timeout=self.timeout_seconds,
                cwd=str(self.renderer_script.parent),
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "AntV renderer failed").strip()
            raise RuntimeError(detail[-2000:]) from exc
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"AntV renderer unavailable: {exc}") from exc
        try:
            result: Any = json.loads(completed.stdout)
            path = result["path"]
            self.last_render_mode = str(result.get("renderer", "antv"))
            warning = result.get("warning")
            self.last_render_warning = str(warning) if warning else None
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise RuntimeError("AntV renderer returned an invalid result") from exc
        if not isinstance(path, str) or not Path(path).exists():
            raise RuntimeError("AntV renderer did not create an SVG artifact")
        return path
