from __future__ import annotations

import shutil

import pytest
from PIL import Image
from pydantic import ValidationError
from pypdf import PdfWriter

from api.artifacts import ArtifactStore
from pipelines.common.visual_qa import inspect_visual_artifact
from pipelines.infographic.quality import inspect_svg
from pipelines.ppt.presentation_quality import inspect_presentation
from pipelines.ppt.renderer import render_presentation
from pipelines.ppt.schemas import PresentationOutput, SlideContent
from pipelines.video.quality import inspect_video
from pipelines.orchestrator.contracts import RequestConstraints


class _ScopedEvidenceVerifier:
    def get_evidence(self, evidence_id, context, *, classification_level="RESTRICTED"):
        if context.user_id != "user-1" or context.case_id != "case-1" or context.task_id != "task-1":
            raise PermissionError("foreign evidence")
        return {"evidence_id": evidence_id, "classification_level": classification_level}


def _presentation() -> PresentationOutput:
    return PresentationOutput(
        presentation_id="phase6-brief",
        title="Phase 6 brief",
        classification_level="RESTRICTED",
        distribution="Authorized",
        slides=[
            SlideContent(slide_id="cover", order=1, title="Phase 6", bullets=[], layout="cover"),
            SlideContent(slide_id="context", order=2, title="Context", bullets=["Verified evidence"], layout="content"),
        ],
    )


def _copy_rendered_pptx(destination) -> str:
    rendered = render_presentation(_presentation())
    target = destination / "phase6-brief.pptx"
    shutil.copy2(rendered.path, target)
    return str(target)


def test_visual_integrity_rejects_missing_empty_and_corrupt_pptx(tmp_path) -> None:
    missing = inspect_visual_artifact(tmp_path / "missing.pptx", kind="pptx")
    assert missing.approved is False
    assert "artifact is missing" in missing.issues

    empty = tmp_path / "empty.pptx"
    empty.write_bytes(b"")
    empty_report = inspect_visual_artifact(empty, kind="pptx")
    assert empty_report.approved is False
    assert "artifact is empty" in empty_report.issues

    corrupt = tmp_path / "corrupt.pptx"
    corrupt.write_bytes(b"not a zip package")
    corrupt_report = inspect_visual_artifact(corrupt, kind="pptx")
    assert corrupt_report.approved is False
    assert any("PPTX package is unreadable" in issue for issue in corrupt_report.issues)


def test_rendered_pptx_is_structurally_valid_editable_and_contains_required_text(tmp_path) -> None:
    artifact = _copy_rendered_pptx(tmp_path)
    report = inspect_visual_artifact(artifact, kind="pptx", required_text=("Phase 6", "Context"))
    assert report.approved is True
    assert report.kind == "pptx"
    assert report.byte_size > 0


def test_register_checked_rejects_wrong_file_type_for_declared_pptx(tmp_path) -> None:
    source = tmp_path / "looks-like-a-presentation.bin"
    source.write_bytes(b"non-empty but not a PPTX package")
    store = ArtifactStore(tmp_path / "artifacts")
    controlled = store.root / source.name
    shutil.copy2(source, controlled)

    checked = store.register_checked(
        controlled,
        run_id="run-wrong-type",
        kind="presentation",
        artifact_kind="pptx",
        renderer_id="presentation.pptx",
        classification_level="RESTRICTED",
        user_id="user-1",
        case_id="case-1",
        task_id="task-1",
    )

    assert checked.manifest.quality_status == "failed"
    assert checked.quality_issues
    assert any("PPTX" in issue for issue in checked.quality_issues)


def test_register_checked_records_failed_quality_report_without_promoting_candidate(tmp_path) -> None:
    source = tmp_path / "broken.svg"
    source.write_text("<svg width='10' height='10'><text>wrong</text></svg>", encoding="utf-8")
    store = ArtifactStore(tmp_path / "artifacts")
    controlled = store.root / source.name
    shutil.copy2(source, controlled)

    checked = store.register_checked(
        controlled,
        run_id="run-failed-quality",
        kind="infographic",
        artifact_kind="svg",
        renderer_id="infographic.native-svg",
        classification_level="RESTRICTED",
        user_id="user-1",
        case_id="case-1",
        task_id="task-1",
        required_text=("approved claim",),
    )

    assert checked.manifest.quality_status == "failed"
    assert checked.manifest.quality_report_id == checked.quality_report_id
    assert (store.quality_report_root / f"{checked.quality_report_id}.json").is_file()
    assert any("required visible text is missing" in issue for issue in checked.quality_issues)


def test_manifest_preserves_provenance_ownership_and_evidence_references(tmp_path) -> None:
    root = tmp_path / "artifacts"
    source = root / "brief.txt"
    source.parent.mkdir(parents=True)
    source.write_text("Evidence-backed brief", encoding="utf-8")
    store = ArtifactStore(root, evidence_scope_verifier=_ScopedEvidenceVerifier())

    manifest = store.register(
        source,
        run_id="run-provenance",
        kind="text",
        classification_level="RESTRICTED",
        user_id="user-1",
        case_id="case-1",
        task_id="task-1",
        evidence_ids=["evi-1", "evi-2"],
        source_ir_hash="a" * 64,
    )

    assert manifest.user_id == "user-1"
    assert manifest.case_id == "case-1"
    assert manifest.task_id == "task-1"
    assert manifest.evidence_ids == ["evi-1", "evi-2"]
    assert manifest.source_ir_hash == "a" * 64
    assert manifest.sha256
    assert manifest.size_bytes == len("Evidence-backed brief".encode("utf-8"))


def test_tampering_after_registration_is_detected(tmp_path) -> None:
    root = tmp_path / "artifacts"
    source = root / "brief.txt"
    source.parent.mkdir(parents=True)
    source.write_text("original", encoding="utf-8")
    store = ArtifactStore(root)
    manifest = store.register(
        source,
        run_id="run-tamper",
        kind="text",
        classification_level="RESTRICTED",
        user_id="user-1",
        case_id="case-1",
        task_id="task-1",
    )
    source.write_text("unauthorized replacement", encoding="utf-8")

    with pytest.raises(ValueError, match="checksum"):
        store.get(manifest.artifact_id)


def test_presentation_correctness_enforces_exact_count_and_required_sections() -> None:
    report = inspect_presentation(
        _presentation(),
        constraints=RequestConstraints(slide_count=3, required_sections=["Decision"]),
    )
    assert report.approved is False
    messages = [issue.message for issue in report.issues]
    assert any("Expected 3 slides" in message for message in messages)
    assert any("Missing required section: Decision" in message for message in messages)


def test_presentation_quality_detects_density_and_overflow_proxy() -> None:
    output = PresentationOutput(
        presentation_id="dense-brief",
        title="Dense brief",
        classification_level="RESTRICTED",
        distribution="Authorized",
        slides=[
            SlideContent(slide_id="s1", order=1, title="Title", bullets=["x"] * 6),
            SlideContent(slide_id="s2", order=2, title="Title", bullets=["x" * 301]),
        ],
    )
    report = inspect_presentation(output)
    assert report.approved is False
    codes = {issue.code for issue in report.issues}
    assert "PPT_CONTENT_DENSITY" in codes


def test_png_integrity_is_measured_but_text_quality_remains_explicitly_unverified(tmp_path) -> None:
    image_path = tmp_path / "diagram.png"
    Image.new("RGB", (32, 16), color=(20, 30, 40)).save(image_path)

    report = inspect_visual_artifact(image_path, kind="png")

    assert report.approved is True
    assert (report.width, report.height) == (32, 16)
    # The current PNG gate does not perform OCR. A structural pass is not a
    # claim that labels, hierarchy, or visual readability are correct.
    assert report.required_text == []


def test_pdf_integrity_requires_at_least_one_readable_page(tmp_path) -> None:
    pdf_path = tmp_path / "brief.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with pdf_path.open("wb") as handle:
        writer.write(handle)

    report = inspect_visual_artifact(pdf_path, kind="pdf")

    assert report.approved is True
    assert report.byte_size > 0


def test_svg_safety_and_accessibility_are_machine_checked(tmp_path) -> None:
    source = tmp_path / "unsafe.svg"
    source.write_text(
        "<svg width='100' height='50'><script>alert(1)</script><text>Claim</text></svg>",
        encoding="utf-8",
    )

    report = inspect_svg(source, required_text=("Claim",), strict_accessibility=True)

    assert report.approved is False
    assert any("script" in issue.lower() for issue in report.issues)


def test_video_integrity_reports_missing_or_unavailable_probe_without_claiming_quality(tmp_path) -> None:
    missing = inspect_video(tmp_path / "missing.mp4")
    assert missing.status == "failed"
    assert "output_missing_or_empty" in missing.failures

    nonempty = tmp_path / "placeholder.mp4"
    nonempty.write_bytes(b"not a real video")
    report = inspect_video(nonempty)
    assert report.status in {"failed", "partial"}
    assert report.output_path == str(nonempty)


def test_presentation_schema_rejects_unresolved_placeholder() -> None:
    with pytest.raises(ValidationError, match="unresolved placeholders"):
        PresentationOutput(
            presentation_id="placeholder",
            title="[insert title]",
            classification_level="RESTRICTED",
            distribution="Authorized",
            slides=[
                SlideContent(slide_id="s1", order=1, title="One"),
                SlideContent(slide_id="s2", order=2, title="Two"),
            ],
        )
