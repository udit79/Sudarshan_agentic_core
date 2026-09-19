from __future__ import annotations

from pipelines.orchestrator.prompt_budget import measure_context_edges, measure_prompt_fields


def test_prompt_field_audit_returns_lengths_without_content() -> None:
    measurements = measure_prompt_fields({
        "memory_context": "verified case fact",
        "query": "summarize the case",
    })

    assert [item.name for item in measurements] == ["memory_context", "query"]
    assert all(item.characters > 0 for item in measurements)
    assert all(item.estimated_tokens > 0 for item in measurements)
    assert all("verified case fact" not in str(item.as_dict()) for item in measurements)


def test_context_edge_audit_is_deterministic_and_sanitized() -> None:
    first = measure_context_edges({
        "analysis": {"memory_context": "A" * 400},
        "review": {"analysis_output": "B" * 800},
        "quality": {"summary_output": "C" * 1200, "review_output": "D" * 500},
    })
    second = measure_context_edges({
        "analysis": {"memory_context": "A" * 400},
        "review": {"analysis_output": "B" * 800},
        "quality": {"summary_output": "C" * 1200, "review_output": "D" * 500},
    })

    assert [item.as_dict() for item in first] == [item.as_dict() for item in second]
    assert [item.name for item in first] == ["analysis", "quality", "review"]
    assert first[-1].estimated_tokens < first[1].estimated_tokens
