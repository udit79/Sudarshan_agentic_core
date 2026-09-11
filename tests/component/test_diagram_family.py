import pytest

from pipelines.diagram import DiagramSpec, choose_diagram_kind, compile_flowchart_spec, inspect_diagram, pattern_for


def test_diagram_family_selects_semantic_type_before_layout():
    assert choose_diagram_kind("show dependencies between services") == "dependency"
    assert choose_diagram_kind("show branches from the central idea") == "mind-map"
    assert pattern_for("timeline")["direction"] == "left-to-right"

    spec = DiagramSpec(
        diagram_id="deps",
        kind="dependency",
        nodes=[{"node_id": "a", "label": "Source", "role": "component"}, {"node_id": "b", "label": "API"}],
        edges=[{"source": "a", "target": "b", "label": "feeds"}],
    )
    assert inspect_diagram(spec) == []
    compiled = compile_flowchart_spec(spec)
    assert compiled.nodes[0].kind == "process"


def test_diagram_family_rejects_disconnected_complexity_and_unknown_kind():
    with pytest.raises(ValueError, match="unsupported diagram kind"):
        choose_diagram_kind("anything", requested="radial")
    spec = DiagramSpec(
        diagram_id="broken",
        kind="flowchart",
        nodes=[{"node_id": "a", "label": "A"}, {"node_id": "b", "label": "B"}],
    )
    assert "node is disconnected: a" in inspect_diagram(spec)
    with pytest.raises(ValueError, match="disconnected"):
        compile_flowchart_spec(spec)
