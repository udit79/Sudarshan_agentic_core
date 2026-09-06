"""Vision-model image transcription supporting OpenAI (gpt-4o-mini) and Gemini fallback.

Transcribes printed and handwritten text, preserving structure.
Priority:
1. OpenAI gpt-4o-mini (fastest: ~1.5–3s, high accuracy, uses OPENAI_API_KEY)
2. Gemini 3.6 Flash (fallback, uses GEMINI_API_KEY)
"""

from __future__ import annotations

import base64
import mimetypes
import os
from pathlib import Path

from ingestion_pipelines.config import load_env

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


def _encode_image_b64(file_path: str) -> str:
    with open(file_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def extract_text_from_image_openai(file_path: str) -> str:
    """Fast vision transcription using OpenAI gpt-4o-mini (~1.5–3s latency)."""
    try:
        from openai import OpenAI
    except ImportError as err:
        raise RuntimeError("openai is not installed. Run: python -m pip install openai") from err

    load_env()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key or api_key.startswith("replace-"):
        raise RuntimeError("OPENAI_API_KEY is not set or still default placeholder in .env")

    client = OpenAI(api_key=api_key)
    mime = _mime_type(file_path)
    b64_data = _encode_image_b64(file_path)

    print(f"   [Vision OCR] Calling OpenAI gpt-4o-mini for '{Path(file_path).name}' (~1-3s)...", flush=True)

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
                            "url": f"data:{mime};base64,{b64_data}",
                            "detail": "high",
                        },
                    },
                ],
            }
        ],
        max_tokens=4096,
    )
    print("   [Vision OCR] Completed transcription via OpenAI.", flush=True)
    return response.choices[0].message.content or ""


def extract_text_from_image_gemini(file_path: str) -> str:
    """Vision-model transcription using Google Gemini API."""
    try:
        from google import genai
        from google.genai import types as genai_types
    except ImportError as err:
        raise RuntimeError("google-genai is not installed. Run: python -m pip install google-genai") from err

    load_env()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key or api_key.startswith("replace-"):
        raise RuntimeError("GEMINI_API_KEY is not set or still default placeholder in .env")

    client = genai.Client(api_key=api_key)
    with open(file_path, "rb") as f:
        image_bytes = f.read()
    mime = _mime_type(file_path)

    print(f"   [Vision OCR] Calling Gemini Vision API for '{Path(file_path).name}' (cloud processing takes ~10-25s)...", flush=True)
    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=[
            genai_types.Part.from_bytes(data=image_bytes, mime_type=mime),
            _TRANSCRIPTION_PROMPT,
        ],
        config=genai_types.GenerateContentConfig(
            automatic_function_calling=genai_types.AutomaticFunctionCallingConfig(disable=True)
        ),
    )
    print("   [Vision OCR] Completed transcription via Gemini.", flush=True)
    return response.text or ""


def extract_text_from_image(file_path: str) -> str:
    """Smart provider resolution: prefers OpenAI gpt-4o-mini, falls back to Gemini."""
    load_env()
    openai_key = os.environ.get("OPENAI_API_KEY")

    if openai_key and not openai_key.startswith("replace-"):
        return extract_text_from_image_openai(file_path)

    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key and not gemini_key.startswith("replace-"):
        return extract_text_from_image_gemini(file_path)

    raise RuntimeError(
        "Neither OPENAI_API_KEY nor GEMINI_API_KEY is configured in your .env file."
    )
