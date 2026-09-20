"""Centralised token-budget stage caps and run-policy defaults.

Each constant is documented with the rationale for its value so that future
changes can be made deliberately rather than by editing scattered call sites.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Stage-level memory recall token caps
# ---------------------------------------------------------------------------
# These caps bound how many tokens a single memory-recall call may consume.
# They are intentionally lower than the top-level run budget so that recall
# does not exhaust the budget before the generation pipeline runs.
#
# Stage: request_memory_recall  (pre-understanding, lightweight orientation)
# Rationale: only needs enough context for intent resolution (~8 records),
#             so capping at 20% of the 6 000 default run budget is sufficient.
STAGE_RECALL_UNDERSTANDING_TOKENS: int = 1200

# Stage: grounding  (full case context before generation)
# Rationale: needs richer context (up to 16 records), so ~43% of the default
#             run budget.  Grounding quality directly affects output quality.
STAGE_RECALL_GROUNDING_TOKENS: int = 2600

# Default recall budget used when a caller does not supply an explicit value.
# Matches the historic default in MemoryManager.recall().
STAGE_RECALL_DEFAULT_TOKENS: int = 2000

# ---------------------------------------------------------------------------
# Budget warning threshold
# ---------------------------------------------------------------------------
# Fraction of the run budget that, when consumed, triggers a WARNING-level log.
# At 80 % consumed the orchestrator still has headroom but should avoid new
# heavy operations.
BUDGET_WARNING_FRACTION: float = 0.80

# ---------------------------------------------------------------------------
# Run policy defaults  (mirrored from contracts.py; kept here for locality)
# ---------------------------------------------------------------------------
RUN_DEFAULT_TOKEN_BUDGET: int = 6_000
RUN_DEFAULT_TOP_K: int = 16


def truncate_to_token_budget(text: str, budget: int) -> str:
    """Cap *text* to approximately *budget* tokens using a 4-chars-per-token estimate.

    This is intentionally a simple safety cap rather than a precise tokeniser call so
    that it can be used without pulling in model-specific dependencies.  The 4:1 ratio
    is conservative for English prose; non-Latin scripts may consume slightly more but
    are still bounded.
    """
    return text[: budget * 4]


__all__ = [
    "BUDGET_WARNING_FRACTION",
    "RUN_DEFAULT_TOKEN_BUDGET",
    "RUN_DEFAULT_TOP_K",
    "STAGE_RECALL_DEFAULT_TOKENS",
    "STAGE_RECALL_GROUNDING_TOKENS",
    "STAGE_RECALL_UNDERSTANDING_TOKENS",
    "truncate_to_token_budget",
]
