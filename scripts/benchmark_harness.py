"""Offline native Harness/Sudarshan boundary benchmark.

This benchmark intentionally makes no provider or network calls. It measures
the local contracts that can regress in CI: MCP schema size, adapter dispatch,
renderer capability coverage, sandbox controls, and safe diagnostic output.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any

# Make direct `python scripts/benchmark_harness.py` behave like a repository
# module invocation without requiring an editable install.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from integrations.deepseek_harness.mcp_server import MCP_TOOL_PROFILES, mcp
from pipelines.common.renderers import default_renderer_registry
from pipelines.common.sandbox import LocalSandboxAdapter, SandboxPolicy


def _tool_count() -> int:
    return len(tuple(mcp._tool_manager.list_tools()))


def _adapter_latency(iterations: int = 100) -> float:
    class Health:
        def health(self) -> dict[str, str]: return {"status": "ok"}

    from integrations.deepseek_harness.adapter import SudarshanHarnessAdapter

    adapter = SudarshanHarnessAdapter(lambda: Health())
    started = time.perf_counter()
    for _ in range(iterations):
        adapter.call("health")
    return round((time.perf_counter() - started) * 1000 / iterations, 3)


def _sandbox_checks() -> dict[str, Any]:
    policy = SandboxPolicy(allowed_commands=frozenset({Path(sys.executable).name, sys.executable}), timeout_seconds=2)
    adapter = LocalSandboxAdapter(policy)
    safe = adapter.execute(
        sys.executable,
        ("-c", "from pathlib import Path; Path('artifact.txt').write_text('ok')"),
        expected_outputs=("artifact.txt",),
    )
    secret = adapter.execute(
        sys.executable,
        ("-c", "print('api_key=secret-value')"),
    )
    timeout = adapter.execute(
        sys.executable,
        ("-c", "import time; time.sleep(3)"),
    )
    return {
        "success": safe.succeeded and bool(safe.artifacts),
        "timeout_detected": timeout.timed_out,
        "secret_redacted": "secret-value" not in secret.stdout and "secret-value" not in secret.stderr,
    }


def build_report() -> dict[str, Any]:
    artifact_tools = len(MCP_TOOL_PROFILES["artifact"] or ())
    full_tools = _tool_count()
    sandbox = _sandbox_checks()
    renderers = default_renderer_registry().as_dict()
    return {
        "benchmark": "sudarshan-harness-boundary",
        "schema": {
            "full_mcp_tools": full_tools,
            "artifact_profile_tools": artifact_tools,
            "schema_reduction_percent": round((1 - artifact_tools / full_tools) * 100, 1) if full_tools else 0.0,
        },
        "latency_ms": {"adapter_health_dispatch_p50_local": _adapter_latency()},
        "quality": {
            "renderer_count": len(renderers),
            "renderer_capabilities": renderers,
            "sandbox": sandbox,
        },
        "recovery": {"timeout_detected": sandbox["timeout_detected"]},
        "cost": {"provider_calls": 0, "model_tokens": 0, "network_calls": 0},
        "safe_logging": {"secret_redaction_passed": sandbox["secret_redacted"]},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build_report()
    encoded = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
