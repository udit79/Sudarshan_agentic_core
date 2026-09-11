import sys
from pathlib import Path
from threading import Event

from pipelines.ppt.ppt_master_adapter import PptMasterAdapter, PptMasterConfig


def _workspace(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "ppt-master"
    script = root / "skills" / "ppt-master" / "scripts" / "svg_to_pptx.py"
    script.parent.mkdir(parents=True)
    script.write_text("# fake exporter\n", encoding="utf-8")
    project = tmp_path / "project"
    (project / "svg_output").mkdir(parents=True)
    return root, project


def test_ppt_master_command_is_bounded_to_project_output(tmp_path):
    root, project = _workspace(tmp_path)
    adapter = PptMasterAdapter(PptMasterConfig(root=root, python_executable=sys.executable))

    command = adapter.build_command(project, project / "exports" / "deck.pptx", roundtrip=True)

    assert adapter.available is True
    assert command[0] == sys.executable
    assert command[-1] == "--roundtrip"
    assert "-o" in command

    try:
        adapter.build_command(project, tmp_path / "outside.pptx")
    except Exception as exc:
        assert "inside the project" in str(exc)
    else:
        raise AssertionError("adapter accepted an output outside the project")


def test_ppt_master_export_requires_quality_reports(tmp_path):
    root, project = _workspace(tmp_path)
    script = root / "skills" / "ppt-master" / "scripts" / "svg_to_pptx.py"
    script.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "args = sys.argv\n"
        "project = Path(args[1])\n"
        "output = Path(args[args.index('-o') + 1])\n"
        "output.parent.mkdir(parents=True, exist_ok=True)\n"
        "output.write_bytes(b'pptx')\n"
        "validation = project / 'validation'\n"
        "validation.mkdir(exist_ok=True)\n"
        "(validation / 'svg_quality_report.json').write_text('{}')\n"
        "(validation / f'{output.stem}.report.json').write_text('{}')\n",
        encoding="utf-8",
    )
    adapter = PptMasterAdapter(PptMasterConfig(root=root, python_executable=sys.executable, timeout_seconds=10))

    result = adapter.export(project, project / "exports" / "deck.pptx")

    assert result.status == "succeeded"
    assert Path(result.output_path).is_file()
    assert Path(result.quality_report_path).is_file()


def test_ppt_master_export_honors_pre_cancel(tmp_path):
    root, project = _workspace(tmp_path)
    adapter = PptMasterAdapter(PptMasterConfig(root=root, python_executable=sys.executable))
    cancel = Event()
    cancel.set()

    result = adapter.export(project, project / "deck.pptx", cancel_event=cancel)

    assert result.status == "cancelled"
    assert result.failure_code == "CANCELLED"
