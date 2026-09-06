"""JSONL runner that lets DeepSeek Harness invoke the real Python system.

The Harness owns the session, tools, cancellation surface, and sandbox. This
runner owns no memory or routing policy; it creates the Sudarshan orchestrator
and returns the same JSON contract that an HTTP backend should expose.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from integrations.deepseek_harness.application import get_application


def run_one(payload: dict[str, Any]) -> dict[str, Any]:
    return get_application().run(payload)


def main() -> int:
    raw = sys.stdin.read().strip()
    if not raw:
        raise SystemExit("Expected one JSON request on stdin")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise SystemExit("The Harness request must be a JSON object")
    print(json.dumps(run_one(payload), ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
