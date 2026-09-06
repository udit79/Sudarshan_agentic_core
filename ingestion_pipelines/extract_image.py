"""Vision-model image transcription via Gemini.

Replaces pytesseract for all image inputs.  Handles both printed and
handwritten content; tesseract only handled the former reliably.
"""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path

from ingestion_pipelines.config import load_env


# Supported image types and their MIME type overrides where Python's mimetypes
# module may guess incorrectly (e.g. .jpg -> image/jpeg, not image/jpg).
_MIME_MAP: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
}

_TRANSCRIPTION_PROMPT = (
    "Transcribe all text in this image exactly as written, including "
    "handwritten notes. Preserve structure (headings, lists, equations, "
    "tables) as plain text. Return only the transcription, no commentary."
)


def _mime_type(file_path: str) -> str:
    ext = Path(file_path).suffix.lower()
    if ext in _MIME_MAP:
        return _MIME_MAP[ext]
    guessed, _ = mimetypes.guess_type(file_path)
    return guessed or "image/jpeg"


def extract_text_from_image_gemini(file_path: str) -> str:
    """Vision-model transcription using the Gemini API.

    Reads GEMINI_API_KEY from the environment.  Raises a clear RuntimeError
    if the key is missing so callers can surface a useful message.
    """
    try:
        from google import genai
        from google.genai import types as genai_types
    except ImportError as err:
        raise RuntimeError(
            "google-genai is not installed. "
            "Run: python -m pip install google-genai"
        ) from err

    load_env()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to your .env file."
        )

    client = genai.Client(api_key=api_key)

    with open(file_path, "rb") as f:
        image_bytes = f.read()

    mime = _mime_type(file_path)

    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=[
            genai_types.Part.from_bytes(data=image_bytes, mime_type=mime),
            _TRANSCRIPTION_PROMPT,
        ],
        # Newer google-genai releases warn on the default AFC path for
        # one-shot generate_content calls; we never pass tools, so disable it.
        config=genai_types.GenerateContentConfig(
            automatic_function_calling=genai_types.AutomaticFunctionCallingConfig(disable=True)
        ),
    )
    return response.text or ""
