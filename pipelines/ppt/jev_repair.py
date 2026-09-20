"""Bounded Jev-assisted normalization for presentation JSON."""
from __future__ import annotations
import json
import os
import urllib.request
from typing import Any

def repair_presentation_json(value: Any) -> Any:
    """Apply structural repairs only; never invent presentation facts."""
    if isinstance(value, str):
        text = value.strip().removeprefix("```").removeprefix("json").removesuffix("```").strip()
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return value
    if not isinstance(value, dict):
        return value
    for key in ("json", "data", "output", "presentation"):
        if isinstance(value.get(key), dict) and not any(k in value for k in ("title", "slides")):
            value = value[key]
            break
    if isinstance(value.get("slides"), list):
        for slide in value["slides"]:
            if isinstance(slide, dict):
                if isinstance(slide.get("bullets"), str):
                    slide["bullets"] = [slide["bullets"]]
                slide.setdefault("layout", "content")
    return value

def jev_allows_repair(raw: Any) -> bool:
    """Ask Jev whether only bounded structural repair is appropriate."""
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        return False
    try:
        body = json.dumps({"model": "typesafe/jev-1.13", "state": {"candidate": raw}, "questions": {
            "action": {"type": "choice", "instructions": "Is this presentation JSON repairable without inventing facts?",
                        "criteria": {"repair": "Only wrappers, list coercion, or default layout values are wrong.",
                                     "retry": "Required content is missing, contradictory, or unsafe."}}
        }}).encode()
        request = urllib.request.Request("https://openrouter.ai/api/v1/decisions", data=body,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=8) as response:
            return json.loads(response.read())["answers"]["action"].get("choice") == "repair"
    except Exception:
        return False

__all__ = ["jev_allows_repair", "repair_presentation_json"]
