from __future__ import annotations

import json
import sys
from pathlib import Path
from threading import Event

from pipelines.infographic.ir import diagram_ir_from_output, infographic_ir_from_output, infographic_ir_to_syntax
from pipelines.infographic.normalization import normalize_infographic_output
from pipelines.infographic.renderer import AntVInfographicRenderer
from pipelines.infographic.quality import inspect_svg
from pipelines.infographic.schemas import InfographicOutput
from pipelines.infographic.templates import get_infographic_theme, infographic_template_registry, select_infographic_template


FIXTURE = Path(__file__).parents[1] / "fixtures" / "infographic-final-output.json"


def load_final_output() -> InfographicOutput:
    return InfographicOutput.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))


def test_real_final_output_shape_compiles_to_semantic_ir() -> None:
    output = load_final_output()
    ir = infographic_ir_from_output(output)
    compiled = infographic_ir_to_syntax(ir)
    diagram = diagram_ir_from_output(output)

    assert ir.infographic_id == output.infographic_id
    assert len(ir.blocks) == len(output.evidence)
    assert compiled.startswith("infographic")
    assert "[E-1]" in compiled
    assert len(diagram.nodes) == 2
    assert diagram.edges[0].source == "E-1"


def test_infographic_template_and_theme_selection_is_allow_listed() -> None:
    registry = infographic_template_registry()
    assert set(registry) == {
        "list-grid-simple",
        "list-row-simple-horizontal-arrow",
        "sequence-steps-simple",
    }
    selection = select_infographic_template("timeline")
    assert selection.template.template_id == "list-row-simple-horizontal-arrow"
    assert selection.used_fallback is False
    assert selection.template.external_dependencies == ()
    assert get_infographic_theme()["accent"].startswith("#")

    try:
        select_infographic_template("timeline", requested_template="remote-template")
    except ValueError as exc:
        assert "unknown infographic template" in str(exc)
    else:
        raise AssertionError("unapproved template was accepted")


def test_real_final_output_renders_through_node_boundary(tmp_path) -> None:
    output = normalize_infographic_output(load_final_output())
    renderer = AntVInfographicRenderer(output_dir=tmp_path, timeout_seconds=30, ssr_timeout_ms=2000)
    artifact_path = renderer(output.syntax, artifact_name=output.infographic_id)
    artifact = Path(artifact_path)
    svg = artifact.read_text(encoding="utf-8")

    assert artifact.is_file()
    assert artifact.suffix == ".svg"
    assert "<svg" in svg[:500]
    assert "Source review" in svg or "E-1" in svg
    assert "Synthetic case process" in svg
    assert renderer.last_render_mode in {"native", "fallback"}
    assert "#1e3a8a" in svg.lower() or "#0f766e" in svg.lower()
    report = inspect_svg(
        artifact,
        required_text=("Synthetic case process",),
        renderer_mode=renderer.last_render_mode,
        renderer_warning=renderer.last_render_warning,
        operator_waiver_id=("waiver-test" if renderer.last_render_mode == "fallback" else None),
    )
    assert report.approved, report.issues
    assert report.width and report.width > 0
    assert report.height and report.height > 0


def test_renderer_honors_cancellation_before_start(tmp_path) -> None:
    script = tmp_path / "renderer.py"
    script.write_text("", encoding="utf-8")
    renderer = AntVInfographicRenderer(
        node_binary=sys.executable,
        renderer_script=script,
        output_dir=tmp_path,
    )
    cancel = Event()
    cancel.set()

    try:
        renderer("infographic list-grid-simple", artifact_name="cancelled", cancel_event=cancel)
    except RuntimeError as exc:
        assert "cancelled" in str(exc)
    else:
        raise AssertionError("renderer ignored cancellation")
