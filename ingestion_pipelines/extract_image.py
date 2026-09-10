"""OpenAI-only vision transcription for images.

Transcribes printed and handwritten text with OpenAI's vision-capable model,
preserving structure and provenance for the ingestion boundary.
"""

from __future__ import annotations

import base64
import mimetypes
import os
from pathlib import Path
from typing import Callable

from ingestion_pipelines.config import load_env
from ingestion_pipelines.runtime import IngestionBudgetExceededError

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


def extract_text_from_image_openai(
    file_path: str,
    *,
    stage_charger: Callable[[str, int, int, int], object] | None = None,
    usage_recorder: Callable[[str, str, str, int, int, bool], object] | None = None,
) -> str:
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
    if stage_charger is not None:
        stage_charger("vision", 1, 4096, 0)

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
    print("   [Vision OCR] Completed transcription via OpenAI.", flush=True)
    return response.choices[0].message.content or ""


def extract_text_from_image(
    file_path: str,
    *,
    stage_charger: Callable[[str, int, int, int], object] | None = None,
    usage_recorder: Callable[[str, str, str, int, int, bool], object] | None = None,
) -> str:
    """Transcribe an image through the configured OpenAI vision model."""
    load_env()
    openai_key = os.environ.get("OPENAI_API_KEY")

    if openai_key and not openai_key.startswith("replace-"):
        try:
            return extract_text_from_image_openai(
                file_path,
                stage_charger=stage_charger,
                usage_recorder=usage_recorder,
            )
        except Exception as err:
            if isinstance(err, IngestionBudgetExceededError):
                raise
            return f"(Image OCR unavailable: provider error [{type(err).__name__}])"

    return "(Image OCR unavailable: OPENAI_API_KEY is not configured)"
