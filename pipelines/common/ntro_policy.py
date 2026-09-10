"""NTRO / Government of India policy enforcement.

This module is not a generic classification engine.  It enforces the
domain-specific output-quality and handling rules that apply to every
Sudarshan pipeline output before delivery.  All pipelines route through
``sanitize_output`` after their quality gate.

The classification level is metadata — it does not alter pipeline routing.
Routing is determined exclusively by pipeline selection for parallel execution.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

# ---------------------------------------------------------------------------
# Classification levels (metadata only, NOT routing)
# ---------------------------------------------------------------------------

CLASSIFICATION_LEVELS: tuple[str, ...] = (
    "UNCLASSIFIED",
    "RESTRICTED",
    "CONFIDENTIAL",
    "SECRET",
    "TOP SECRET",
)

DEFAULT_CLASSIFICATION = "RESTRICTED"

_CLASSIFICATION_RANK = {level: index for index, level in enumerate(CLASSIFICATION_LEVELS)}


def validate_classification(level: str, *, strict: bool = False) -> str:
    """Normalise and validate a classification level string.

    Returns the canonical uppercase form. Invalid values fall back to
    ``RESTRICTED`` for legacy internal metadata paths. Public request
    boundaries must use ``strict=True`` so misclassified requests are rejected.
    """

    normalised = level.strip().upper()
    if normalised in CLASSIFICATION_LEVELS:
        return normalised
    if strict:
        raise ValueError(
            f"classification_level must be one of: {', '.join(CLASSIFICATION_LEVELS)}"
        )
    return DEFAULT_CLASSIFICATION


def require_classification(level: str) -> str:
    """Validate a caller-supplied classification without silent downgrading."""

    return validate_classification(level, strict=True)


def require_classification_access(access_level: str, artifact_level: str) -> tuple[str, str]:
    """Require a caller clearance at least as high as an artifact marking."""

    access = require_classification(access_level)
    required = require_classification(artifact_level)
    if _CLASSIFICATION_RANK[access] < _CLASSIFICATION_RANK[required]:
        raise PermissionError(
            f"{access} clearance cannot access {required} artifact"
        )
    return access, required


# ---------------------------------------------------------------------------
# Distribution marking
# ---------------------------------------------------------------------------

STANDARD_DISTRIBUTIONS: tuple[str, ...] = (
    "Authorized NTRO personnel",
    "Cabinet Secretariat",
    "NSA Office",
    "PMO",
    "RAW",
    "IB",
    "Ministry of Defence",
    "Ministry of External Affairs",
    "CERT-In",
    "NIA",
    "DRDO",
)


def validate_distribution(distribution: str) -> str:
    """Accept a custom distribution or normalise to the closest standard form."""

    stripped = distribution.strip()
    if not stripped:
        return STANDARD_DISTRIBUTIONS[0]
    lower = stripped.lower()
    for standard in STANDARD_DISTRIBUTIONS:
        if standard.lower() == lower:
            return standard
    # Custom distribution accepted; the backend owns the access-control list.
    return stripped


# ---------------------------------------------------------------------------
# Output sanitizer
# ---------------------------------------------------------------------------

# Patterns that must never appear in a delivered NTRO output.
_AI_SELF_REFERENCE = re.compile(
    r"\b("
    r"as an? (?:AI|language model|LLM|assistant|chatbot)"
    r"|I(?:'m| am) (?:an? )?(?:AI|language model|LLM|assistant)"
    r"|(?:GPT|ChatGPT|OpenAI|Anthropic|Claude|DeepSeek|CrewAI|LangGraph|LangChain)"
    r"|(?:my training data|my knowledge cutoff|I don'?t have access)"
    r"|(?:as a (?:text|large) (?:model|system))"
    r")\b",
    re.IGNORECASE,
)

_PROMPT_ARTIFACT = re.compile(
    r"(?:"
    r"<\/?(?:system|user|assistant|tool_call|tool_result|function_call)[^>]*>"
    r"|```(?:json|xml|yaml)?[\s\S]*?(?:system_prompt|user_message|assistant_message)"
    r"|\bprompt(?:_text|_plan|_template)\b"
    r"|recall_sudarshan_memory"
    r"|MemoryManager\."
    r"|TaskMemoryWriter"
    r"|PipelineOrchestrator"
    r"|AdvisoryRequest"
    r"|PipelineResponse"
    r"|KnowledgeUnit"
    r"|sudarshan_memory_id"
    r"|node_set:sudarshan"
    r"|pipeline://\w+"
    r")",
    re.IGNORECASE,
)

_INTERNAL_TOOL_NAME = re.compile(
    r"\b("
    r"run_sudarshan|resume_sudarshan|cancel_sudarshan|get_sudarshan_status"
    r"|recall_sudarshan_memory"
    r"|CrewAI|LangGraph|Cognee"
    r")\b",
    re.IGNORECASE,
)

# Secret-shaped values are redacted at response and logging boundaries. This
# is deliberately conservative: ordinary words such as ``token_budget`` are
# safe, while credentials and bearer/JWT-like values are not.
_SECRET_VALUE = re.compile(
    r"(?:"
    r"(?:sk|rk|ghp|github_pat|xox[baprs])-[-A-Za-z0-9_]{4,}"
    r"|Bearer\s+[A-Za-z0-9._~+/=-]{8,}"
    r"|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
    r"|(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password)"
    r"\s*[:=]\s*[^\s,;]+"
    r")",
    re.IGNORECASE,
)
_SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret"
    r"|password|passwd|authorization|cookie|private[_-]?key|credential|secret)",
    re.IGNORECASE,
)


def redact_sensitive(value: Any) -> Any:
    """Recursively remove credentials from data crossing a trust boundary."""

    if isinstance(value, str):
        return _SECRET_VALUE.sub("[REDACTED]", value)
    if isinstance(value, Mapping):
        safe: dict[Any, Any] = {}
        for key, item in value.items():
            safe[key] = "[REDACTED]" if _SENSITIVE_KEY.search(str(key)) else redact_sensitive(item)
        return safe
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class SanitizationResult:
    """Outcome of output sanitization."""

    text: str
    violations_found: int
    violations: tuple[str, ...]


def sanitize_text(text: str) -> SanitizationResult:
    """Remove AI self-references, prompt artifacts, and internal tool names.

    Returns the sanitized text and a count of violations found.  The caller
    should log violations for audit but should not expose them in the response.
    """

    if not text or not text.strip():
        return SanitizationResult(text, 0, ())

    violations: list[str] = []
    result = text

    for match in _AI_SELF_REFERENCE.finditer(result):
        violations.append(f"ai_self_reference: {match.group()[:80]}")
    result = _AI_SELF_REFERENCE.sub("", result)

    for match in _PROMPT_ARTIFACT.finditer(result):
        violations.append(f"prompt_artifact: {match.group()[:80]}")
    result = _PROMPT_ARTIFACT.sub("", result)

    for match in _INTERNAL_TOOL_NAME.finditer(result):
        violations.append(f"internal_tool: {match.group()[:80]}")
    result = _INTERNAL_TOOL_NAME.sub("", result)

    # Collapse multiple blank lines left by removals.
    result = re.sub(r"\n{3,}", "\n\n", result)

    return SanitizationResult(result.strip(), len(violations), tuple(violations))


def sanitize_output(output: Any) -> Any:
    """Recursively sanitize all string values in a pipeline output structure."""

    if isinstance(output, str):
        return sanitize_text(output).text
    if isinstance(output, Mapping):
        return {key: sanitize_output(value) for key, value in output.items()}
    if isinstance(output, (list, tuple)):
        sanitized = [sanitize_output(item) for item in output]
        return type(output)(sanitized) if isinstance(output, tuple) else sanitized
    if hasattr(output, "model_dump"):
        data = output.model_dump(mode="json")
        return sanitize_output(data)
    return output


# ---------------------------------------------------------------------------
# NTRO handling instructions
# ---------------------------------------------------------------------------

HANDLING_INSTRUCTIONS: dict[str, str] = {
    "UNCLASSIFIED": "This document may be shared with authorized government personnel.",
    "RESTRICTED": (
        "Handle in accordance with NTRO information security procedures. "
        "Do not transmit over unencrypted channels."
    ),
    "CONFIDENTIAL": (
        "This document is CONFIDENTIAL. Distribute only to authorized "
        "recipients with appropriate clearance and need-to-know."
    ),
    "SECRET": (
        "This document is SECRET. Handle, store, and transmit in accordance "
        "with Government of India security classification guidelines. "
        "Unauthorized disclosure is a criminal offence."
    ),
    "TOP SECRET": (
        "This document is TOP SECRET. Restrict access to individually "
        "cleared personnel with documented need-to-know. Follow all "
        "Government of India TOP SECRET handling procedures."
    ),
}


def handling_instruction_for(classification_level: str) -> str:
    """Return the NTRO handling instruction for a classification level."""

    level = validate_classification(classification_level)
    return HANDLING_INSTRUCTIONS.get(level, HANDLING_INSTRUCTIONS[DEFAULT_CLASSIFICATION])


# ---------------------------------------------------------------------------
# Bilingual support markers
# ---------------------------------------------------------------------------

_HINDI_BLOCK = re.compile(r"[\u0900-\u097F]")


def contains_hindi(text: str) -> bool:
    """Detect whether text contains Devanagari script (Hindi)."""

    return bool(_HINDI_BLOCK.search(text))


def bilingual_label(english: str, hindi: str | None = None) -> str:
    """Format a bilingual English/Hindi label for GoI officials."""

    if hindi and hindi.strip():
        return f"{english} / {hindi.strip()}"
    return english


# ---------------------------------------------------------------------------
# Response validation gate
# ---------------------------------------------------------------------------

def validate_ntro_response(response_data: Mapping[str, Any]) -> dict[str, Any]:
    """Post-pipeline gate ensuring no classified content leaks into metadata.

    This is called before the response leaves the orchestrator.  It strips
    internal fields that must never reach the frontend or Harness output.
    """

    FORBIDDEN_METADATA_KEYS = {
        "cognee_raw",
        "cognee_response",
        "api_key",
        "openai_api_key",
        "cognee_api_key",
        "model_reasoning",
        "chain_of_thought",
        "system_prompt",
        "raw_memory",
    }

    result = dict(response_data)
    metadata = dict(result.get("metadata") or {})

    for key in FORBIDDEN_METADATA_KEYS:
        metadata.pop(key, None)

    if "output" in result and isinstance(result["output"], (str, dict)):
        result["output"] = sanitize_output(result["output"])

    result["metadata"] = metadata
    return redact_sensitive(result)
