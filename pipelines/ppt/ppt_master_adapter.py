"""Optional, bounded bridge to a user-managed local PPT Master checkout.

PPT Master is not hosted, downloaded, or provisioned by Sudarshan. The caller
must install/self-host the reference runtime and set
``SUDARSHAN_PPT_MASTER_ROOT`` to that checkout. Sudarshan owns the request,
evidence, authorization, budgets, cancellation, and artifact gate; this module
only validates a prepared workspace and invokes the local exporter.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event


class PptMasterAdapterError(RuntimeError):
    """Raised when a PPT Master workspace or invocation is unsafe."""


@dataclass(frozen=True, slots=True)
class PptMasterConfig:
    root: Path | None = None
    python_executable: str = sys.executable
    timeout_seconds: float = 300.0
    renderer_version: str = "ppt-master@local"

    @classmethod
    def from_env(cls) -> "PptMasterConfig":
        root_value = os.getenv("SUDARSHAN_PPT_MASTER_ROOT", "").strip()
        timeout = float(os.getenv("SUDARSHAN_PPT_MASTER_TIMEOUT_SECONDS", "300"))
        if timeout <= 0 or timeout > 3600:
            raise ValueError("SUDARSHAN_PPT_MASTER_TIMEOUT_SECONDS must be between 1 and 3600")
        return cls(
            root=Path(root_value).expanduser() if root_value else None,
            python_executable=os.getenv("SUDARSHAN_PPT_MASTER_PYTHON", sys.executable),
            timeout_seconds=timeout,
            renderer_version=os.getenv("SUDARSHAN_PPT_MASTER_RENDERER_VERSION", "ppt-master@local"),
        )


@dataclass(frozen=True, slots=True)
class PptMasterExportResult:
    status: str
    output_path: str | None = None
    quality_report_path: str | None = None
    svg_quality_report_path: str | None = None
    renderer_version: str = "ppt-master@local"
    failure_code: str | None = None
    slide_count: int | None = None


class PptMasterAdapter:
    """Invoke the deterministic exporter from an explicitly configured local checkout."""

    renderer_id = "presentation.ppt-master"

    def __init__(self, config: PptMasterConfig | None = None) -> None:
        self.config = config or PptMasterConfig.from_env()

    @property
    def script_path(self) -> Path | None:
        if self.config.root is None:
            return None
        return self.config.root / "skills" / "ppt-master" / "scripts" / "svg_to_pptx.py"

    @property
    def available(self) -> bool:
        script = self.script_path
        return script is not None and script.is_file()

    @property
    def availability_reason(self) -> str | None:
        """Explain why the local bridge cannot run, without probing a service."""

        if self.config.root is None:
            return (
                "PPT Master is not hosted by Sudarshan; install or self-host a "
                "local checkout and set SUDARSHAN_PPT_MASTER_ROOT"
            )
        script = self.script_path
        if script is None or not script.is_file():
            return f"PPT Master exporter script was not found under {self.config.root}"
        return None

    def build_command(
        self,
        project_path: str | Path,
        output_path: str | Path,
        *,
        roundtrip: bool = False,
    ) -> list[str]:
        script = self.script_path
        if script is None or not script.is_file():
            raise PptMasterAdapterError(self.availability_reason or "PPT Master exporter is unavailable")

        project = Path(project_path).expanduser().resolve()
        if not project.is_dir():
            raise PptMasterAdapterError("PPT Master project workspace does not exist")
        if not (project / "svg_output").is_dir():
            raise PptMasterAdapterError("PPT Master workspace must contain svg_output")

        output = Path(output_path).expanduser().resolve()
        try:
            output.relative_to(project)
        except ValueError as exc:
            raise PptMasterAdapterError("PPTX output must remain inside the project workspace") from exc
        output.parent.mkdir(parents=True, exist_ok=True)

        command = [
            self.config.python_executable,
            str(script.resolve()),
            str(project),
            "-o",
            str(output),
        ]
        if roundtrip:
            command.append("--roundtrip")
        return command

    def export(
        self,
        project_path: str | Path,
        output_path: str | Path,
        *,
        roundtrip: bool = False,
        cancel_event: Event | None = None,
    ) -> PptMasterExportResult:
        """Run export with a deadline and cooperative process cancellation."""

        if cancel_event is not None and cancel_event.is_set():
            return self._cancelled()
        command = self.build_command(project_path, output_path, roundtrip=roundtrip)
        project = Path(project_path).expanduser().resolve()
        output = Path(output_path).expanduser().resolve()
        try:
            process = subprocess.Popen(
                command,
                cwd=str(self.config.root),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
        except OSError as exc:
            return self._failed("PPT_MASTER_START_FAILED", str(exc))

        started = time.monotonic()
        while process.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                self._stop(process)
                return self._cancelled()
            if time.monotonic() - started >= self.config.timeout_seconds:
                self._stop(process)
                return self._failed("PPT_MASTER_TIMEOUT", "PPT Master export exceeded its deadline")
            time.sleep(0.05)

        if process.returncode != 0:
            return self._failed("PPT_MASTER_EXPORT_FAILED", "PPT Master exporter returned a non-zero exit code")

        quality_report = project / "validation" / f"{output.stem}.report.json"
        svg_quality_report = project / "validation" / "svg_quality_report.json"
        if not output.is_file() or output.stat().st_size == 0:
            return self._failed("PPT_MASTER_OUTPUT_MISSING", "PPT Master did not produce a non-empty PPTX")
        if not quality_report.is_file() or not svg_quality_report.is_file():
            return self._failed(
                "PPT_MASTER_QUALITY_REPORT_MISSING",
                "PPT Master export completed without both required quality reports",
            )
        try:
            from pptx import Presentation

            slide_count = len(Presentation(str(output)).slides)
        except Exception as exc:
            return self._failed("PPT_MASTER_READBACK_FAILED", f"PPTX read-back failed: {exc}")
        return PptMasterExportResult(
            status="succeeded",
            output_path=str(output),
            quality_report_path=str(quality_report),
            svg_quality_report_path=str(svg_quality_report),
            renderer_version=self.config.renderer_version,
            slide_count=slide_count,
        )

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

    def _cancelled(self) -> PptMasterExportResult:
        return PptMasterExportResult(
            status="cancelled",
            renderer_version=self.config.renderer_version,
            failure_code="CANCELLED",
        )

    def _failed(self, code: str, message: str) -> PptMasterExportResult:
        return PptMasterExportResult(
            status="failed",
            renderer_version=self.config.renderer_version,
            failure_code=f"{code}:{message}",
        )


__all__ = [
    "PptMasterAdapter",
    "PptMasterAdapterError",
    "PptMasterConfig",
    "PptMasterExportResult",
]
