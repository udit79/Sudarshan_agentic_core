from pathlib import Path

import pytest

from pipelines.infographic.export import InfographicExportRequest, export_infographic_artifact
from pipelines.infographic.visual_regression import compare_svg_fixture, svg_regression_hash


def test_infographic_svg_export_and_structural_fixture(tmp_path) -> None:
    source = tmp_path / "source.svg"
    source.write_text('<svg width="100" height="50"><title>Brief</title><rect width="100" height="50"/></svg>', encoding="utf-8")
    target = tmp_path / "copy.svg"
    artifact = export_infographic_artifact(source, InfographicExportRequest(output_path=str(target)), required_text=("Brief",))
    assert artifact.format == "svg"
    assert compare_svg_fixture(target, svg_regression_hash(target)).approved


def test_infographic_export_rejects_unsafe_svg(tmp_path) -> None:
    source = tmp_path / "unsafe.svg"
    source.write_text('<svg width="1" height="1"><script>alert(1)</script></svg>', encoding="utf-8")
    with pytest.raises(ValueError, match="executable"):
        export_infographic_artifact(source, InfographicExportRequest(output_path=str(tmp_path / "out.svg")))
