"""PPTX artifact renderer for the PPT generation pipeline.

Converts a validated PresentationOutput into a .pptx file using python-pptx.
Written to artifacts/presentations/ with a stable, auditable filename.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

from pptx import Presentation
from pptx.util import Inches, Pt

from pipelines.ppt.schemas import PresentationOutput


_ARTIFACT_DIR = Path("artifacts") / "presentations"


class PresentationArtifact(NamedTuple):
    path: str
    presentation_id: str
    slide_count: int
    content: str   # human-readable summary for memory write-back





def _add_title_slide(prs: Presentation, output: PresentationOutput) -> None:
    """Slide 1: Cover — title, subtitle, classification."""
    layout = prs.slide_layouts[0]  # Title Slide layout
    slide = prs.slides.add_slide(layout)

    title_ph = slide.shapes.title
    subtitle_ph = slide.placeholders[1]

    title_ph.text = output.title
    title_ph.text_frame.paragraphs[0].font.size = Pt(36)
    title_ph.text_frame.paragraphs[0].font.bold = True

    subtitle_ph.text = (
        f"{output.subtitle}\n\n"
        f"Classification: {output.classification_level}\n"
        f"Distribution: {output.distribution}"
    )
    subtitle_ph.text_frame.paragraphs[0].font.size = Pt(18)


def _add_agenda_slide(prs: Presentation, output: PresentationOutput) -> None:
    """Slide 2: Agenda."""
    layout = prs.slide_layouts[1]  # Title and Content layout
    slide = prs.slides.add_slide(layout)

    slide.shapes.title.text = "Agenda"
    slide.shapes.title.text_frame.paragraphs[0].font.size = Pt(28)
    slide.shapes.title.text_frame.paragraphs[0].font.bold = True

    body = slide.placeholders[1]
    tf = body.text_frame
    tf.clear()
    for i, item in enumerate(output.agenda):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.text = item
        para.font.size = Pt(18)
        para.level = 0


def _add_content_slide(prs: Presentation, slide_data) -> None:
    """Content slides from SlideContent objects."""
    layout = prs.slide_layouts[1]  # Title and Content
    slide = prs.slides.add_slide(layout)

    slide.shapes.title.text = slide_data.title
    slide.shapes.title.text_frame.paragraphs[0].font.size = Pt(24)
    slide.shapes.title.text_frame.paragraphs[0].font.bold = True

    body = slide.placeholders[1]
    tf = body.text_frame
    tf.clear()
    for i, bullet in enumerate(slide_data.bullets):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.text = bullet
        para.font.size = Pt(16)
        para.level = 0

    # Speaker notes
    if slide_data.speaker_notes:
        notes_frame = slide.notes_slide.notes_text_frame
        notes_frame.text = slide_data.speaker_notes


def _add_conclusion_slide(prs: Presentation, output: PresentationOutput) -> None:
    """Second-to-last slide: Key Takeaways + Conclusion."""
    layout = prs.slide_layouts[1]
    slide = prs.slides.add_slide(layout)

    slide.shapes.title.text = "Key Takeaways"
    slide.shapes.title.text_frame.paragraphs[0].font.size = Pt(28)
    slide.shapes.title.text_frame.paragraphs[0].font.bold = True

    body = slide.placeholders[1]
    tf = body.text_frame
    tf.clear()
    for i, item in enumerate(output.key_takeaways):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.text = item
        para.font.size = Pt(18)
        para.level = 0

    notes_frame = slide.notes_slide.notes_text_frame
    notes_frame.text = output.conclusion_summary


def _add_closing_slide(prs: Presentation, output: PresentationOutput) -> None:
    """Final slide: Confidence + Gaps + References."""
    layout = prs.slide_layouts[1]
    slide = prs.slides.add_slide(layout)

    slide.shapes.title.text = "Confidence & Intelligence Gaps"
    slide.shapes.title.text_frame.paragraphs[0].font.size = Pt(24)
    slide.shapes.title.text_frame.paragraphs[0].font.bold = True

    body = slide.placeholders[1]
    tf = body.text_frame
    tf.clear()

    # Confidence statement
    p = tf.paragraphs[0]
    p.text = f"Confidence: {output.confidence_statement}"
    p.font.size = Pt(15)
    p.font.bold = True

    # Gaps
    if output.intelligence_gaps:
        gap_para = tf.add_paragraph()
        gap_para.text = "Intelligence Gaps:"
        gap_para.font.size = Pt(14)
        gap_para.font.bold = True
        for gap in output.intelligence_gaps:
            gp = tf.add_paragraph()
            gp.text = f"• {gap}"
            gp.font.size = Pt(13)
            gp.level = 1

    # References
    if output.references:
        ref_para = tf.add_paragraph()
        ref_para.text = "References:"
        ref_para.font.size = Pt(14)
        ref_para.font.bold = True
        for ref in output.references:
            rp = tf.add_paragraph()
            rp.text = f"• {ref}"
            rp.font.size = Pt(12)
            rp.level = 1


def render_presentation(
    output: PresentationOutput,
    *,
    approved_by: str | None = None,
) -> PresentationArtifact:
    """Render PresentationOutput → PPTX file → PresentationArtifact."""

    _ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_id = output.presentation_id.replace("/", "-").replace(" ", "_")[:60]
    filename = f"{safe_id}_{timestamp}.pptx"
    file_path = _ARTIFACT_DIR / filename

    prs = Presentation()
    # Standard widescreen (13.33 x 7.5 inches)
    prs.slide_width = Inches(13.33)
    prs.slide_height = Inches(7.5)

    _add_title_slide(prs, output)
    _add_agenda_slide(prs, output)

    for slide_data in output.slides:
        _add_content_slide(prs, slide_data)

    _add_conclusion_slide(prs, output)
    _add_closing_slide(prs, output)

    prs.save(str(file_path))

    # Human-readable content summary for memory write-back
    content_lines = [
        f"# {output.title}",
        f"## {output.subtitle}",
        f"Classification: {output.classification_level}",
        f"Distribution: {output.distribution}",
        "",
        "## Agenda",
        *[f"- {item}" for item in output.agenda],
        "",
        "## Key Takeaways",
        *[f"- {kw}" for kw in output.key_takeaways],
        "",
        f"## Confidence\n{output.confidence_statement}",
        "",
        "## Slides",
    ]
    for slide in output.slides:
        content_lines.append(f"### Slide {slide.slide_number}: {slide.title}")
        content_lines.extend([f"- {b}" for b in slide.bullets])

    if approved_by:
        content_lines.append(f"\nApproved by: {approved_by}")

    return PresentationArtifact(
        path=str(file_path),
        presentation_id=output.presentation_id,
        slide_count=len(output.slides) + 4,  # content + title + agenda + conclusion + closing
        content="\n".join(content_lines),
    )
