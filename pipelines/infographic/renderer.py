"""Python boundary for the AntV Infographic Node SSR renderer."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from threading import Event
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
        # AntV documents a materially slower cold start on Windows. Keep the
        # outer process deadline bounded, but do not force normal cold starts
        # into the fallback renderer.
        self.ssr_timeout_ms = ssr_timeout_ms or int(os.getenv("ANTV_SSR_TIMEOUT_MS", "30000"))
        if self.ssr_timeout_ms < 100:
            raise ValueError("ssr_timeout_ms must be at least 100 milliseconds")
        self.last_render_mode = "unknown"
        self.last_render_warning: str | None = None
        self.renderer_version = os.getenv("ANTV_RENDERER_VERSION", "antv-infographic@0.2.20")
        if timeout_seconds is None:
            raw_timeout = os.getenv("ANTV_RENDER_TIMEOUT_SECONDS", "60")
            try:
                timeout_seconds = int(raw_timeout)
            except ValueError as exc:
                raise ValueError("ANTV_RENDER_TIMEOUT_SECONDS must be an integer") from exc
        if timeout_seconds < 1:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds

    def __call__(
        self,
        syntax: str,
        *,
        artifact_name: str,
        cancel_event: Event | None = None,
    ) -> str:
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
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("AntV renderer cancelled before start")
        try:
            process = subprocess.Popen(
                [self.node_binary, str(self.renderer_script)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(self.renderer_script.parent),
            )
            if process.stdin is not None:
                process.stdin.write(payload.encode("utf-8"))
                process.stdin.close()
            started = time.monotonic()
            while process.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    self._stop(process)
                    raise RuntimeError("AntV renderer cancelled")
                if time.monotonic() - started >= self.timeout_seconds:
                    self._stop(process)
                    raise RuntimeError("AntV renderer exceeded its deadline")
                time.sleep(0.05)
            stdout = process.stdout.read() if process.stdout is not None else b""
            stderr = process.stderr.read() if process.stderr is not None else b""
        except OSError as exc:
            raise RuntimeError(f"AntV renderer unavailable: {exc}") from exc
        if process.returncode != 0:
            detail = (stderr or stdout or b"AntV renderer failed").decode("utf-8", errors="replace").strip()
            raise RuntimeError(detail[-2000:])
        try:
            result: Any = json.loads(stdout.decode("utf-8"))
            path = result["path"]
            self.last_render_mode = str(result.get("renderer", "antv"))
            warning = result.get("warning")
            self.last_render_warning = str(warning) if warning else None
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise RuntimeError("AntV renderer returned an invalid result") from exc
        if not isinstance(path, str) or not Path(path).exists():
            raise RuntimeError("AntV renderer did not create an SVG artifact")
        return path

    @staticmethod
    def _stop(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
