"""OpenAI-only image generation adapter for LinkedIn post visuals."""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any
from uuid import uuid4


GOVERNMENT_STYLE_PREFIX = (
    "Create a restrained, professional, government-quality visual for a public information post. "
    "Use a sober composition, clear hierarchy, neutral colors, accessible contrast, and accurate visual "
    "metaphors. The result must not be flashy, sensational, glossy, cartoonish, or advertisement-like. "
    "Do not invent seals, government logos, official insignia, statistics, labels, people, places, or events. "
    "Do not reveal confidential, personal, or restricted information. Avoid dense unreadable text; use no text "
    "unless it is explicitly supplied in the prompt."
)


class OpenAIImageGenerator:
    """Generate one image through OpenAI's Image API and return its local path or URL.

    The OpenAI client is created lazily, so text-only posts do not require an API
    key. The SDK reads ``OPENAI_API_KEY`` from the environment.
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        output_dir: str | Path = "artifacts/linkedin/images",
        size: str = "1536x1024",
        quality: str = "high",
        output_format: str = "png",
        client: Any = None,
    ) -> None:
        self.model = model or os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
        self.output_dir = Path(output_dir)
        self.size = size
        self.quality = quality
        self.output_format = output_format
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI()
        return self._client

    def __call__(self, prompt: str) -> str:
        if not prompt.strip():
            raise ValueError("image generation requires a non-empty prompt")
        response = self.client.images.generate(
            model=self.model,
            prompt=f"{GOVERNMENT_STYLE_PREFIX}\n\nSpecific case-grounded visual brief:\n{prompt}",
            size=self.size,
            quality=self.quality,
            output_format=self.output_format,
        )
        image = response.data[0]
        encoded = getattr(image, "b64_json", None)
        if encoded:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            path = self.output_dir / f"linkedin-{uuid4().hex}.{self.output_format}"
            path.write_bytes(base64.b64decode(encoded))
            return str(path)
        url = getattr(image, "url", None)
        if url:
            return str(url)
        raise RuntimeError("OpenAI Image API returned neither image data nor a URL")
