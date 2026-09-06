"""Native PPTX ingestion enrichment — reverse-engineered from PPT Master.

This module extracts structural information and markdown from PPTX files without
requiring external services or sandboxed VBA execution. It parses slide content,
transitions, layouts, and speaker notes directly from the OOXML structures using
python-pptx.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Generator

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE


class PPTMasterError(RuntimeError):
    """Raised when PPT Master intake fails."""


@dataclass
class PPTXSourceProfile:
    """Enriched source profile extracted from a PPTX file."""

    slide_count: int
    title: str = ""
    author: str = ""
    keywords: list[str] = None
    has_media: bool = False
    markdown_content: str = ""

    def __post_init__(self) -> None:
        if self.keywords is None:
            self.keywords = []


class PPTMasterIntake:
    """Enrich PPTX files during ingestion natively."""

    def __init__(self) -> None:
        pass

    def extract(self, file_path_or_stream: str | Path | BinaryIO) -> PPTXSourceProfile:
        """Extract markdown and metadata from a PPTX presentation."""

        try:
            prs = Presentation(file_path_or_stream)
        except zipfile.BadZipFile as exc:
            raise PPTMasterError("Invalid or corrupted PPTX file") from exc
        except Exception as exc:
            raise PPTMasterError(f"Failed to load PPTX: {exc}") from exc

        title = prs.core_properties.title or ""
        author = prs.core_properties.author or ""
        keywords = prs.core_properties.keywords.split(",") if prs.core_properties.keywords else []

        markdown_lines = []
        if title:
            markdown_lines.append(f"# {title}\n")
        
        has_media = False
        slide_count = len(prs.slides)

        for i, slide in enumerate(prs.slides, start=1):
            markdown_lines.append(f"## Slide {i}")
            
            # Extract slide layout name if available
            layout_name = slide.slide_layout.name if slide.slide_layout else "Unknown Layout"
            markdown_lines.append(f"*(Layout: {layout_name})*\n")

            has_title = False
            for shape in slide.shapes:
                if shape.has_text_frame:
                    text = shape.text.strip()
                    if not text:
                        continue
                    
                    if shape == slide.shapes.title and not has_title:
                        markdown_lines.append(f"### {text}")
                        has_title = True
                    else:
                        # Indent bullet points based on level
                        for paragraph in shape.text_frame.paragraphs:
                            p_text = paragraph.text.strip()
                            if p_text:
                                level = paragraph.level or 0
                                indent = "  " * level
                                markdown_lines.append(f"{indent}- {p_text}")

                elif shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                    has_media = True
                    markdown_lines.append("\n*[Image Media]*")
                
                elif shape.shape_type == MSO_SHAPE_TYPE.MEDIA:
                    has_media = True
                    markdown_lines.append("\n*[Video/Audio Media]*")
                
                elif shape.shape_type == MSO_SHAPE_TYPE.TABLE:
                    markdown_lines.append("\n*[Table]*")
                    for row in shape.table.rows:
                        row_data = [cell.text_frame.text.replace("\n", " ").strip() for cell in row.cells]
                        markdown_lines.append("| " + " | ".join(row_data) + " |")

            # Extract speaker notes
            if slide.has_notes_slide:
                notes = slide.notes_slide.notes_text_frame.text.strip()
                if notes:
                    markdown_lines.append(f"\n**Speaker Notes:**\n> {notes}\n")

            markdown_lines.append("\n---\n")

        return PPTXSourceProfile(
            slide_count=slide_count,
            title=title,
            author=author,
            keywords=[k.strip() for k in keywords if k.strip()],
            has_media=has_media,
            markdown_content="\n".join(markdown_lines),
        )

