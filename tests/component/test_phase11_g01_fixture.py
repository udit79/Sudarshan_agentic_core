"""Offline Phase 11 replay checks for the sanitized G01 golden case."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from memory import AccessContext, MemoryManager


FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "phase11_g01_normal_report.json"


def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


class _G01FixtureBackend:
    def __init__(self, case: dict[str, Any]) -> None:
        self.case = case

    def recall(self, **_: Any) -> list[dict[str, Any]]:
        return [{
            "text": self.case["content"],
            "metadata": {
                "scope_type": "case",
                "scope_id": self.case["case_id"],
                "source_reference": self.case["source_reference"],
                "memory_id": "fixture-g01-source",
            },
            "score": 1.0,
        }]


def test_g01_fixture_becomes_scoped_grounding_context() -> None:
    case = _fixture()
    manager = MemoryManager(_G01FixtureBackend(case))

    pack = manager.recall_context_pack(
        case["operator_request"],
        AccessContext(
            user_id="fixture-operator",
            case_id=case["case_id"],
            task_id="fixture-task-g01",
        ),
        run_id="fixture-run-g01",
        stage_id="grounding",
        top_k=4,
        token_budget=2600,
    )

    assert pack.scope["case_id"] == case["case_id"]
    assert len(pack.records) == 1
    record = pack.records[0]
    assert record["scope_type"] == "case"
    assert record["scope_id"] == case["case_id"]
    assert record["source_reference"] == case["source_reference"]
    for expected in [*case["expected_facts"], *case["expected_unknowns"]]:
        assert expected in pack.context_text
    for forbidden in case["forbidden_context"]:
        assert forbidden not in pack.context_text
