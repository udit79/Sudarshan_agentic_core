"""PPTX text and notes extractor using python-pptx.

Follows the "SLIDES + NOTES" design:
- Iterates slides in sequence
- Extracts text from all text frames and table cells
- Extracts speaker notes if present
- Preserves structure with clear slide delimiters
"""

from __future__ import annotations

from pathlib import Path
from pptx import Presentation


def extract_text_from_pptx(file_path: str) -> str:
    """Extracts slide content and speaker notes from a PowerPoint presentation."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Source file not found: {file_path}")

    prs = Presentation(str(path))
    slide_chunks: list[str] = []

    for slide_num, slide in enumerate(prs.slides, start=1):
        slide_lines: list[str] = []

        # 1. Collect text from all shapes (text frames and tables)
        for shape in slide.shapes:
            if shape.has_text_frame:
                for paragraph in shape.text_frame.paragraphs:
                    text = paragraph.text.strip()
                    if text:
                        slide_lines.append(text)
            elif shape.has_table:
                table_lines: list[str] = []
                for row in shape.table.rows:
                    row_cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                    if row_cells:
                        table_lines.append(" | ".join(row_cells))
                if table_lines:
                    slide_lines.extend(table_lines)

        # 2. Collect speaker notes if present
        notes_text = ""
        if slide.has_notes_slide:
            notes_slide = slide.notes_slide
            if notes_slide.notes_text_frame:
                notes_text = notes_slide.notes_text_frame.text.strip()

        # 3. Assemble slide representation
        content_block = "\n".join(slide_lines).strip()
        header = f"--- Slide {slide_num} ---"

        parts: list[str] = [header]
        if content_block:
            parts.append(content_block)
        if notes_text:
            parts.append(f"[Speaker Notes]:\n{notes_text}")

        # If the slide had either content or notes, record it
        if content_block or notes_text:
            slide_chunks.append("\n".join(parts))
        else:
            slide_chunks.append(f"{header}\n(Empty Slide)")

    return "\n\n".join(slide_chunks).strip()
