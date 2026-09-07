"""OpenAI-only story and storyboard planning for the native video pipeline."""

from __future__ import annotations

import json
import os
from typing import Any

from pipelines.video.contracts import VideoPackage


class VideoPlanningError(RuntimeError):
    """Raised when OpenAI cannot produce a valid video package."""


class OpenAIVideoPlanner:
    """Create a validated video package from bounded case context."""

    def __init__(self, *, client: Any = None, model: str | None = None) -> None:
        self._client = client
        configured = model or os.getenv("OPENAI_VIDEO_SCRIPT_MODEL", "")
        self.model = configured or os.getenv("CREWAI_MODEL", "openai/gpt-5.4").removeprefix("openai/")

    @property
    def client(self) -> Any:
        if self._client is None:
            if not os.getenv("OPENAI_API_KEY", "").strip():
                raise VideoPlanningError("OPENAI_API_KEY is required for automatic video story planning")
            from openai import OpenAI

            self._client = OpenAI()
        return self._client

    def plan(
        self,
        *,
        subject: str,
        query: str,
        memory_context: str,
        prompt_plan: dict[str, Any] | None = None,
    ) -> VideoPackage:
        bounded_memory = (memory_context or "")[:30000]
        plan_text = json.dumps(prompt_plan or {}, ensure_ascii=False)[:12000]
        instruction = f"""
Create a case-grounded video preparation package as JSON only.

Subject: {subject[:500]}
User request: {query[:4000]}
Validated prompt plan: {plan_text}
Permitted memory context:
<memory>
{bounded_memory}
</memory>

Return exactly an object with:
- title: concise title
- script: complete narration script
- storyboard: 3 to 12 ordered scenes
- video_terms: visual search terms, one per scene

Each storyboard scene must contain scene_id, narration, visual_description,
duration_seconds (3 to 30), and on_screen_text. Use only facts supported by
the request or memory. Mark uncertainty instead of inventing details. Do not
mention models, prompts, tools, or internal workflow.
""".strip()
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You produce strict JSON video packages."},
                    {"role": "user", "content": instruction},
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            if isinstance(content, list):
                content = "".join(str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in content)
            data = json.loads(str(content or ""))
            if not isinstance(data, dict):
                raise ValueError("planner response was not an object")
            data["subject"] = subject[:500]
            return VideoPackage.model_validate(data)
        except Exception as exc:
            if isinstance(exc, VideoPlanningError):
                raise
            raise VideoPlanningError(f"OpenAI video planning failed: {exc}") from exc


__all__ = ["OpenAIVideoPlanner", "VideoPlanningError"]
