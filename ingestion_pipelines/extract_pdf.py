"""Hybrid Multi-Page PDF extractor with digital-first parsing and vision OCR fail-safe.

Follows the "PAGE DELIMITERS + HYBRID VISION" design:
- Preserves structure with clear "--- Page N ---" headers for provenance.
- Digital pages: Extracted in milliseconds locally (free, 0ms, 0 API cost).
- Scanned / Handwritten pages (< 30 text chars): Automatically rendered to image
  and transcribed via our vision model (gpt-4o-mini / Gemini).
- Multi-page concurrency: Scanned pages are processed in parallel via ThreadPoolExecutor.
"""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path

from ingestion_pipelines.config import load_env

_TRANSCRIPTION_PROMPT = (
    "Transcribe all text on this document page exactly as written, including "
    "handwritten notes, stamps, signatures, and tables. Preserve structure "
    "(headings, lists, tables). Return only the transcription, no commentary."
)


def _ocr_page_image_bytes(img_bytes: bytes, page_num: int) -> str:
    """Transcribes page image bytes using OpenAI gpt-4o-mini (or Gemini fallback)."""
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
        return response.choices[0].message.content or ""

    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key and not gemini_key.startswith("replace-"):
        from google import genai
        from google.genai import types as genai_types
        client = genai.Client(api_key=gemini_key)
        print(f"   [PDF Hybrid OCR] Page {page_num}: Scanned page detected, calling Gemini Vision...", flush=True)
        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=[
                genai_types.Part.from_bytes(data=img_bytes, mime_type="image/png"),
                _TRANSCRIPTION_PROMPT,
            ],
            config=genai_types.GenerateContentConfig(
                automatic_function_calling=genai_types.AutomaticFunctionCallingConfig(disable=True)
            ),
        )
        return response.text or ""

    return "(Scanned page - OCR unavailable: no API key configured)"


def extract_text_from_pdf(file_path: str) -> str:
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
        with ThreadPoolExecutor(max_workers=min(5, len(scanned_tasks))) as executor:
            future_to_page = {
                executor.submit(_ocr_page_image_bytes, img_bytes, p_num): p_num
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
