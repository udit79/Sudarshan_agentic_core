from pipelines.common.visual_qa import evaluate_renderer_promotion, inspect_visual_artifact


def test_visual_qa_checks_svg_and_renderer_promotion(tmp_path):
    path = tmp_path / "preview.svg"
    path.write_text('<svg width="100" height="50"><text>NTRO</text></svg>', encoding="utf-8")
    report = inspect_visual_artifact(path, required_text=("NTRO",), renderer_version="svg@1")
    assert report.approved is True
    promotion = evaluate_renderer_promotion([report], renderer_version="svg@1")
    assert promotion.approved is True


def test_visual_qa_rejects_missing_or_corrupt_artifact(tmp_path):
    report = inspect_visual_artifact(tmp_path / "missing.pptx", kind="pptx")
    assert report.approved is False
    promotion = evaluate_renderer_promotion([report], renderer_version="pptx@1")
    assert promotion.approved is False
