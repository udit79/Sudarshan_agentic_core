"""Bounded execution adapters for renderer and validation helpers.

The local adapter is deliberately useful for development and deterministic
tests, but it is not an OS sandbox. Production should select the container
adapter through configuration. Both adapters implement the same small
protocol, so renderer and validator contracts do not depend on Docker, a
future runtime, or the Harness UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from threading import Event
import time
from typing import Iterable, Mapping, Protocol, Sequence


class SandboxViolation(ValueError):
    """Raised when a sandbox request exceeds its declared policy."""


@dataclass(frozen=True, slots=True)
class SandboxPolicy:
    """Small, explicit policy shared by renderer and validation jobs."""

    allowed_commands: frozenset[str] = frozenset()
    timeout_seconds: float = 60.0
    max_output_bytes: int = 64_000
    max_workspace_bytes: int = 256 * 1024 * 1024
    memory_limit_mb: int = 512
    cpu_limit: float = 1.0
    max_processes: int = 64
    environment: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.allowed_commands:
            raise ValueError("sandbox requires at least one allowed command")
        if (
            self.timeout_seconds <= 0
            or self.max_output_bytes <= 0
            or self.max_workspace_bytes <= 0
            or self.memory_limit_mb <= 0
            or self.cpu_limit <= 0
            or self.max_processes <= 0
        ):
            raise ValueError("sandbox limits must be positive")


@dataclass(frozen=True, slots=True)
class SandboxArtifact:
    path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class SandboxResult:
    command: str
    returncode: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    cancelled: bool = False
    artifacts: tuple[SandboxArtifact, ...] = ()

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0 and not self.timed_out and not self.cancelled


class SandboxAdapter(Protocol):
    def execute(
        self,
        command: str,
        args: Sequence[str] = (),
        *,
        input_text: str = "",
        expected_outputs: Iterable[str] = (),
        cancel_event: Event | None = None,
    ) -> SandboxResult:
        """Run one bounded, allow-listed renderer or validator command."""


_SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|token|secret|password)\s*([:=])\s*([^\s,;]+)"
)


def _safe_text(value: bytes, limit: int) -> str:
    text = value[:limit].decode("utf-8", errors="replace")
    if len(value) > limit:
        text += "\n[output truncated]"
    return _SECRET_PATTERN.sub(r"\1\2[redacted]", text)


def _validate_request(policy: SandboxPolicy, command: str, args: Sequence[str]) -> str:
    command_key = str(command).strip()
    if command_key not in policy.allowed_commands:
        raise SandboxViolation(f"sandbox command is not allow-listed: {command_key}")
    if any("\x00" in str(value) for value in args):
        raise SandboxViolation("sandbox arguments cannot contain NUL bytes")
    return command_key


def _collect_outputs(
    policy: SandboxPolicy,
    workspace: Path,
    expected_outputs: Iterable[str],
) -> tuple[SandboxArtifact, ...]:
    collected: list[SandboxArtifact] = []
    for relative in expected_outputs:
        candidate = (workspace / str(relative)).resolve()
        if candidate != workspace and workspace not in candidate.parents:
            raise SandboxViolation("expected output escapes the sandbox workspace")
        if not candidate.is_file():
            raise SandboxViolation(f"expected sandbox output is missing: {relative}")
        size = candidate.stat().st_size
        if size > policy.max_workspace_bytes:
            raise SandboxViolation(f"sandbox output exceeds workspace limit: {relative}")
        digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        collected.append(SandboxArtifact(str(relative), digest, size))
    return tuple(collected)


def _environment(policy: SandboxPolicy, workspace: Path) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", ""),
        "TEMP": str(workspace),
        "TMP": str(workspace),
        "TMPDIR": str(workspace),
        **{str(key): str(value) for key, value in policy.environment.items()},
    }


def _container_environment(policy: SandboxPolicy) -> dict[str, str]:
    return {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "TEMP": "/workspace",
        "TMP": "/workspace",
        "TMPDIR": "/workspace",
        **{str(key): str(value) for key, value in policy.environment.items()},
    }


def _communicate_with_controls(
    process: subprocess.Popen[bytes],
    *,
    input_bytes: bytes,
    timeout_seconds: float,
    cancel_event: Event | None,
) -> tuple[bytes, bytes, bool, bool]:
    """Capture output while observing the deadline and cancellation event."""

    started = time.perf_counter()
    pending_input: bytes | None = input_bytes
    while True:
        if cancel_event is not None and cancel_event.is_set():
            process.terminate()
            try:
                stdout, stderr = process.communicate(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
            return stdout, stderr, False, True
        remaining = timeout_seconds - (time.perf_counter() - started)
        if remaining <= 0:
            process.kill()
            stdout, stderr = process.communicate()
            return stdout, stderr, True, False
        try:
            stdout, stderr = process.communicate(input=pending_input, timeout=min(0.1, remaining))
            return stdout, stderr, False, False
        except subprocess.TimeoutExpired:
            # Popen permits communicate() to be called again after a timeout;
            # the next call drains the same pipes without sending stdin twice.
            pending_input = None


class LocalSandboxAdapter:
    """Run approved commands in a temporary, contained workspace.

    The adapter intentionally accepts an executable key rather than a shell
    command string. It is suitable for local development and deterministic
    tests. Deployment should replace it with a container/Harness sandbox
    implementation without changing renderer contracts.
    """

    def __init__(self, policy: SandboxPolicy, *, root: str | Path | None = None) -> None:
        self.policy = policy
        self.root = Path(root or tempfile.gettempdir()).resolve() / "sudarshan-sandbox"
        self.root.mkdir(parents=True, exist_ok=True)

    def execute(
        self,
        command: str,
        args: Sequence[str] = (),
        *,
        input_text: str = "",
        expected_outputs: Iterable[str] = (),
        cancel_event: Event | None = None,
    ) -> SandboxResult:
        command_key = _validate_request(self.policy, command, args)

        workspace = Path(tempfile.mkdtemp(prefix="job-", dir=self.root))
        started = time.perf_counter()
        process: subprocess.Popen[bytes] | None = None
        timed_out = False
        cancelled = False
        try:
            executable = shutil.which(command_key) or command_key
            environment = _environment(self.policy, workspace)
            process = subprocess.Popen(
                [executable, *[str(value) for value in args]],
                cwd=workspace,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
            )
            stdout, stderr, timed_out, cancelled = _communicate_with_controls(
                process,
                input_bytes=input_text.encode("utf-8"),
                timeout_seconds=self.policy.timeout_seconds,
                cancel_event=cancel_event,
            )
        except KeyboardInterrupt:
            raise
        finally:
            if process is not None and cancel_event is not None and cancel_event.is_set() and process.poll() is None:
                cancelled = True
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
        artifacts = _collect_outputs(self.policy, workspace, expected_outputs)
        duration_ms = int((time.perf_counter() - started) * 1000)
        return SandboxResult(
            command=command_key,
            returncode=process.returncode if process is not None else None,
            stdout=_safe_text(stdout, self.policy.max_output_bytes),
            stderr=_safe_text(stderr, self.policy.max_output_bytes),
            duration_ms=duration_ms,
            timed_out=timed_out,
            cancelled=cancelled,
            artifacts=artifacts,
        )



def _runtime_token(value: str, label: str) -> str:
    token = str(value).strip()
    if not token or any(character in token for character in "\x00\r\n\t "):
        raise SandboxViolation(f"{label} must be one executable token")
    return token


class ContainerSandboxAdapter:
    """Run an allow-listed command in a short-lived, network-disabled container.

    The host exposes only a temporary workspace. The container root is
    read-only, all Linux capabilities are dropped, and resource limits are
    applied before the image entrypoint is invoked. This is an adapter seam,
    not a promise that every container runtime has identical isolation; the
    deployment must still run a trusted/rootless runtime and image policy.
    """

    def __init__(
        self,
        policy: SandboxPolicy,
        *,
        image: str,
        runtime: str = "docker",
        root: str | Path | None = None,
    ) -> None:
        self.policy = policy
        self.image = _runtime_token(image, "sandbox image")
        self.runtime = _runtime_token(runtime, "sandbox runtime")
        self.root = Path(root or tempfile.gettempdir()).resolve() / "sudarshan-sandbox"
        self.root.mkdir(parents=True, exist_ok=True)

    def command_argv(self, command: str, args: Sequence[str] = (), *, workspace: Path) -> list[str]:
        """Build a shell-free runtime argv for testing and controlled execution."""

        command_key = _validate_request(self.policy, command, args)
        workspace = workspace.resolve()
        argv = [
            self.runtime,
            "run",
            "--rm",
            "--init",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            str(self.policy.max_processes),
            "--memory",
            f"{self.policy.memory_limit_mb}m",
            "--cpus",
            str(self.policy.cpu_limit),
            "--workdir",
            "/workspace",
            "--volume",
            f"{workspace}:/workspace:rw",
        ]
        for key, value in _container_environment(self.policy).items():
            if not key or any(character in key for character in "=\x00\r\n"):
                raise SandboxViolation("sandbox environment keys must be valid names")
            argv.extend(("--env", f"{key}={value}"))
        return [*argv, self.image, command_key, *[str(value) for value in args]]

    def execute(
        self,
        command: str,
        args: Sequence[str] = (),
        *,
        input_text: str = "",
        expected_outputs: Iterable[str] = (),
        cancel_event: Event | None = None,
    ) -> SandboxResult:
        command_key = _validate_request(self.policy, command, args)
        if cancel_event is not None and cancel_event.is_set():
            return SandboxResult(command_key, None, "", "", 0, cancelled=True)

        workspace = Path(tempfile.mkdtemp(prefix="job-", dir=self.root))
        started = time.perf_counter()
        process: subprocess.Popen[bytes] | None = None
        stdout = b""
        stderr = b""
        timed_out = False
        cancelled = False
        try:
            process = subprocess.Popen(
                self.command_argv(command_key, args, workspace=workspace),
                cwd=workspace,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
            )
            stdout, stderr, timed_out, cancelled = _communicate_with_controls(
                process,
                input_bytes=input_text.encode("utf-8"),
                timeout_seconds=self.policy.timeout_seconds,
                cancel_event=cancel_event,
            )
        except FileNotFoundError as exc:
            raise SandboxViolation(f"sandbox runtime is unavailable: {self.runtime}") from exc
        finally:
            if process is not None and cancel_event is not None and cancel_event.is_set() and process.poll() is None:
                cancelled = True
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
        artifacts = _collect_outputs(self.policy, workspace, expected_outputs)
        return SandboxResult(
            command=command_key,
            returncode=process.returncode if process is not None else None,
            stdout=_safe_text(stdout, self.policy.max_output_bytes),
            stderr=_safe_text(stderr, self.policy.max_output_bytes),
            duration_ms=int((time.perf_counter() - started) * 1000),
            timed_out=timed_out,
            cancelled=cancelled,
            artifacts=artifacts,
        )


def sandbox_adapter_from_environment(
    policy: SandboxPolicy,
    *,
    environ: Mapping[str, str] | None = None,
) -> SandboxAdapter:
    """Create the deployment-selected adapter without changing pipeline code.

    Local execution is an explicit development opt-in. Production defaults
    to the container adapter and fails clearly when its runtime is invoked but
    unavailable, rather than silently falling back to a host subprocess.
    """

    values = dict(os.environ if environ is None else environ)
    mode = values.get("SUDARSHAN_SANDBOX_MODE", "container").strip().lower()
    if mode == "local":
        if values.get("SUDARSHAN_ALLOW_LOCAL_SANDBOX", "false").strip().lower() not in {"1", "true", "yes", "on"}:
            raise SandboxViolation(
                "local sandbox mode requires the explicit opt-in "
                "SUDARSHAN_ALLOW_LOCAL_SANDBOX=true"
            )
        return LocalSandboxAdapter(policy)
    if mode != "container":
        raise SandboxViolation(f"unsupported sandbox mode: {mode}")
    return ContainerSandboxAdapter(
        policy,
        image=values.get("SUDARSHAN_SANDBOX_CONTAINER_IMAGE", "python:3.12-slim"),
        runtime=values.get("SUDARSHAN_SANDBOX_RUNTIME", "docker"),
    )


__all__ = [
    "ContainerSandboxAdapter",
    "LocalSandboxAdapter",
    "SandboxAdapter",
    "SandboxArtifact",
    "SandboxPolicy",
    "SandboxResult",
    "SandboxViolation",
    "sandbox_adapter_from_environment",
]
