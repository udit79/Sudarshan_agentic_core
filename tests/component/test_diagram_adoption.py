import json

import pytest

from pipelines.diagram import (
    DiagramExportRequest,
    DiagramSpec,
    diagram_type_registry,
    export_diagram,
    get_style_profile,
    import_drawio,
    import_excalidraw,
    import_mermaid,
    validate_style_profile,
)


def _spec() -> DiagramSpec:
    return DiagramSpec(
        diagram_id="adoption-demo",
        kind="architecture",
        title="Sudarshan architecture",
        nodes=[
            {"node_id": "client", "label": "Client"},
            {"node_id": "api", "label": "API"},
        ],
        edges=[{"source": "client", "target": "api", "label": "requests"}],
        detail="balanced",
    )


def test_registry_and_style_profile_are_allow_listed() -> None:
    registry = diagram_type_registry()
    assert "architecture" in registry
    assert registry["architecture"]["direction"] == "left-to-right"
    assert validate_style_profile(get_style_profile()) == []


def test_export_uses_one_ir_and_writes_safe_svg_and_html(tmp_path) -> None:
    spec = _spec()
    svg = export_diagram(spec, DiagramExportRequest(output_path=str(tmp_path / "diagram.svg")))
    html = export_diagram(spec, DiagramExportRequest(output_path=str(tmp_path / "diagram.html"), format="html"))

    assert svg.source_ir_hash == html.source_ir_hash
    assert "<title id=\"diagram-title\">Sudarshan architecture</title>" in (tmp_path / "diagram.svg").read_text(encoding="utf-8")
    html_text = (tmp_path / "diagram.html").read_text(encoding="utf-8")
    assert 'role="img"' in html_text
    assert "<script" not in html_text.lower()


def test_importers_are_bounded_and_non_executable() -> None:
    mermaid = import_mermaid('flowchart LR\nA["Source"] -->|feeds| B["API"]')
    assert mermaid.nodes[0].label == "Source"
    assert mermaid.edges[0].label == "feeds"

    drawio = import_drawio(
        '<mxfile><diagram><root>'
        '<mxCell id="a" value="Source" vertex="1"/>'
        '<mxCell id="b" value="API" vertex="1"/>'
        '<mxCell id="e" edge="1" source="a" target="b"/>'
        '</root></diagram></mxfile>'
    )
    assert len(drawio.nodes) == 2

    excalidraw = import_excalidraw(json.dumps({
        "elements": [
            {"id": "a", "type": "rectangle", "text": "Source"},
            {"id": "b", "type": "rectangle", "text": "API"},
            {"id": "e", "type": "arrow", "startBinding": {"elementId": "a"}, "endBinding": {"elementId": "b"}},
        ],
    }))
    assert len(excalidraw.edges) == 1

    with pytest.raises(ValueError, match="executable"):
        import_mermaid('flowchart LR\nA --> B\n<script>alert(1)</script>')
