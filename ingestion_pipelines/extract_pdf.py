"""Hybrid Multi-Page PDF extractor with digital-first parsing and vision OCR fail-safe.

Follows the "PAGE DELIMITERS + HYBRID VISION" design:
- Preserves structure with clear "--- Page N ---" headers for provenance.
- Digital pages: Extracted in milliseconds locally (free, 0ms, 0 API cost).
- Scanned / Handwritten pages (< 30 text chars): Automatically rendered to image
  and transcribed via OpenAI's vision-capable model (gpt-4o-mini).
- Multi-page concurrency: Scanned pages are processed in parallel via ThreadPoolExecutor.
"""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from typing import Callable

from ingestion_pipelines.config import load_env

_TRANSCRIPTION_PROMPT = (
    "Transcribe all text on this document page exactly as written, including "
    "handwritten notes, stamps, signatures, and tables. Preserve structure "
    "(headings, lists, tables). Return only the transcription, no commentary."
)


def _ocr_page_image_bytes(
    img_bytes: bytes,
    page_num: int,
    *,
    usage_recorder: Callable[[str, str, str, int, int, bool], object] | None = None,
) -> str:
    """Transcribe a scanned page with OpenAI's vision-capable model."""
    load_env()
    openai_key = os.environ.get("OPENAI_API_KEY")

    if openai_key and not openai_key.startswith("replace-"):
        from openai import OpenAI
        client = OpenAI(api_key=openai_key)
        b64_data = base64.b64encode(img_bytes).decode("utf-8")
        print(f"   [PDF Hybrid OCR] Page {page_num}: Scanned page detected, calling OpenAI gpt-4o-mini...", flush=True)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _TRANSCRIPTION_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{b64_data}",
                                "detail": "high",
                            },
                        },
                    ],
                }
            ],
            max_tokens=4096,
        )
        if usage_recorder is not None:
            usage = getattr(response, "usage", None)
            usage_recorder(
                "vision",
                "openai",
                "gpt-4o-mini",
                int(getattr(usage, "prompt_tokens", 0) or 0),
                int(getattr(usage, "completion_tokens", 0) or 0),
                False,
            )
        return response.choices[0].message.content or ""

    return "(Scanned page - OCR unavailable: OPENAI_API_KEY is not configured)"


def extract_text_from_pdf(
    file_path: str,
    *,
    stage_charger: Callable[[str, int, int, int], object] | None = None,
    usage_recorder: Callable[[str, str, str, int, int, bool], object] | None = None,
) -> str:
    """Extracts text from multi-page PDFs using hybrid digital + vision extraction."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Source file not found: {file_path}")

    try:
        import pymupdf
        doc = pymupdf.open(str(path))
        num_pages = len(doc)
    except Exception:
        # Fallback to pypdf if pymupdf fails
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        num_pages = len(reader.pages)
        doc = None

    page_results: list[tuple[int, str]] = []
    scanned_tasks: list[tuple[int, bytes]] = []

    print(f"   [PDF Processing] Parsing {num_pages} pages from '{path.name}'...", flush=True)

    if doc is not None:
        for page_idx in range(num_pages):
            page = doc[page_idx]
            page_num = page_idx + 1
            text = page.get_text().strip()

            if len(text) >= 30:
                # Fast path: Real digital text found
                page_results.append((page_num, f"--- Page {page_num} ---\n{text}"))
            else:
                # Scanned or image-only page: Render to PNG bytes for Vision OCR
                pix = page.get_pixmap(dpi=150)
                img_bytes = pix.tobytes("png")
                scanned_tasks.append((page_num, img_bytes))
    else:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        for page_idx, page in enumerate(reader.pages):
            page_num = page_idx + 1
            text = (page.extract_text() or "").strip()
            if len(text) >= 30:
                page_results.append((page_num, f"--- Page {page_num} ---\n{text}"))
            elif page.images:
                scanned_tasks.append((page_num, page.images[0].data))
            else:
                page_results.append((page_num, f"--- Page {page_num} ---\n(Empty Page)"))

    # Process scanned pages concurrently if any were found
    if scanned_tasks:
        print(f"   [PDF Processing] Transcribing {len(scanned_tasks)} scanned page(s) concurrently via Vision...", flush=True)
        load_env()
        vision_available = bool(
            os.environ.get("OPENAI_API_KEY")
            and not os.environ.get("OPENAI_API_KEY", "").startswith("replace-")
        )
        if stage_charger is not None and vision_available:
            stage_charger("vision", len(scanned_tasks), 4096 * len(scanned_tasks), 0)
        with ThreadPoolExecutor(max_workers=min(5, len(scanned_tasks))) as executor:
            future_to_page = {
                executor.submit(
                    _ocr_page_image_bytes,
                    img_bytes,
                    p_num,
                    usage_recorder=usage_recorder,
                ): p_num
                for p_num, img_bytes in scanned_tasks
            }
            for future in future_to_page:
                p_num = future_to_page[future]
                try:
                    ocr_text = future.result().strip()
                    page_results.append((p_num, f"--- Page {p_num} [Scanned OCR] ---\n{ocr_text}"))
                except Exception as err:
                    page_results.append((p_num, f"--- Page {p_num} [OCR Failed] ---\nError: {err}"))

    # Sort pages by page number to preserve natural reading order
    page_results.sort(key=lambda x: x[0])
    return "\n\n".join(content for _, content in page_results).strip()
