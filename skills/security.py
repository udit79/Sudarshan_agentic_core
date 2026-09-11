"""Skill package integrity and bounded execution helpers."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Iterable, Sequence


class SkillIntegrityError(ValueError):
    """Raised when a skill package is unsigned or has been modified."""


class SandboxError(RuntimeError):
    """Raised when a skill cannot be run within its execution envelope."""


def package_digest(path: str | Path, *, excluded: Iterable[str] = ("signature.json",)) -> str:
    root = Path(path).resolve()
    if not root.is_dir():
        raise SkillIntegrityError(f"skill package does not exist: {root}")
    excluded_names = {str(item) for item in excluded}
    digest = hashlib.sha256()
    files = sorted(
        item for item in root.rglob("*")
        if item.is_file() and item.name not in excluded_names and ".git" not in item.parts
    )
    for item in files:
        relative = item.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(hashlib.sha256(item.read_bytes()).digest())
    return digest.hexdigest()


def verify_skill_package(
    path: str | Path,
    *,
    trust_tier: str = "builtin",
    signing_key: str | None = None,
    trusted_digests: Iterable[str] = (),
) -> str:
    """Verify builtin, signed-verified, and signed sandboxed packages."""

    digest = package_digest(path)
    if str(trust_tier).lower() == "builtin":
        return digest
    trusted = {str(item).strip().lower() for item in trusted_digests if str(item).strip()}
    signature_path = Path(path) / "signature.json"
    if not signature_path.is_file():
        raise SkillIntegrityError("non-builtin skill package requires signature.json")
    try:
        signature = json.loads(signature_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SkillIntegrityError("skill signature is not valid JSON") from exc
    if str(signature.get("digest", "")).lower() != digest:
        raise SkillIntegrityError("skill package digest does not match signature")
    if digest in trusted:
        return digest
    key = signing_key or os.getenv("SUDARSHAN_SKILL_SIGNING_KEY", "")
    expected = hmac.new(key.encode("utf-8"), digest.encode("ascii"), hashlib.sha256).hexdigest() if key else ""
    if not key or not hmac.compare_digest(str(signature.get("signature", "")), expected):
        raise SkillIntegrityError("skill package signature could not be verified")
    return digest


def sign_skill_package(path: str | Path, signing_key: str) -> dict[str, str]:
    if not signing_key:
        raise ValueError("signing_key must be non-empty")
    digest = package_digest(path)
    signature = {
        "algorithm": "hmac-sha256",
        "digest": digest,
        "signature": hmac.new(signing_key.encode("utf-8"), digest.encode("ascii"), hashlib.sha256).hexdigest(),
    }
    (Path(path) / "signature.json").write_text(json.dumps(signature, indent=2) + "\n", encoding="utf-8")
    return signature


@dataclass(frozen=True, slots=True)
class SandboxPolicy:
    timeout_seconds: float = 30.0
    max_output_bytes: int = 1_000_000
    network: bool = False
    container_image: str | None = None


@dataclass(frozen=True, slots=True)
class SandboxResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    timed_out: bool = False


class SandboxRunner:
    """Run untrusted commands in a container when one is configured."""

    def __init__(self, policy: SandboxPolicy | None = None) -> None:
        self.policy = policy or SandboxPolicy()
        if self.policy.timeout_seconds <= 0 or self.policy.max_output_bytes < 1:
            raise ValueError("sandbox limits must be positive")

    def run(self, command: Sequence[str], *, input_bytes: bytes = b"") -> SandboxResult:
        if not command or any(not str(item).strip() for item in command):
            raise SandboxError("sandbox command must be non-empty")
        with tempfile.TemporaryDirectory(prefix="sudarshan-sandbox-") as work:
            environment = {"PATH": os.getenv("PATH", ""), "LANG": "C.UTF-8"}
            actual = [str(item) for item in command]
            if self.policy.container_image:
                docker = shutil.which("docker")
                if not docker:
                    raise SandboxError("container sandbox requires docker")
                actual = [docker, "run", "--rm", "--read-only"]
                if not self.policy.network:
                    actual.extend(["--network=none"])
                actual.extend(["-v", f"{work}:/workspace:rw", "-w", "/workspace", self.policy.container_image, *command])
                cwd = None
            else:
                if os.getenv("SUDARSHAN_ALLOW_LOCAL_SANDBOX", "false").lower() != "true":
                    raise SandboxError("local sandbox is disabled; configure a container_image")
                cwd = work
            try:
                completed = subprocess.run(
                    actual,
                    input=input_bytes,
                    capture_output=True,
                    cwd=cwd,
                    env=environment,
                    timeout=self.policy.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                return SandboxResult(-1, bytes(exc.stdout or b"")[: self.policy.max_output_bytes], bytes(exc.stderr or b"")[: self.policy.max_output_bytes], True)
            return SandboxResult(
                completed.returncode,
                completed.stdout[: self.policy.max_output_bytes],
                completed.stderr[: self.policy.max_output_bytes],
            )


__all__ = [
    "SandboxError", "SandboxPolicy", "SandboxResult", "SandboxRunner",
    "SkillIntegrityError", "package_digest", "sign_skill_package", "verify_skill_package",
]
