# Memory behaviour testing progress

This document tracks the memory phase separately from ingestion. The tests use
the existing `MemoryManager` and its `MemoryBackend` seam. They do not require a
live Cognee tenant, MongoDB, model provider, or `.env` credentials.

## Mentor vocabulary

- **Scope**: who may read a memory. Sudarshan represents this with
  `AccessContext` and `ScopeType` (`USER`, `CASE`, `TASK`).
- **Lifecycle**: whether a memory may currently be recalled. The relevant
  states are `ACTIVE`, `PENDING_REVIEW`, `SUPERSEDED`, `RETRACTED`, and
  `EXPIRED`.
- **Provenance**: where a memory came from, such as a source reference, page,
  pipeline, or run id.
- **MemoryBackend**: the provider seam. Cognee implements it in production;
  tests use a deterministic recording substitute.

## Matrix

| # | WHAT / memory type | WHY + WHERE | INPUT → expected output | TEST / result |
|---:|---|---|---|---|
| 1 | User preference / PROFILE | Durable preference belongs to USER; `MemoryManager.remember_profile` | Pink preference → same user recalls it; another user does not | `test_user_preference_is_explicit_user_profile` — PASS |
| 2 | Case fact / FACT | Case evidence belongs to CASE; inherited by its tasks at read time | Case fact → same case recalls it; other case does not | `test_case_information_is_available_only_inside_that_case` — PASS |
| 3 | Task event / EVENT | Operational detail is narrow and belongs to TASK | Task detail → same task recalls it; case-only view does not | `test_task_information_is_available_only_inside_that_task` — PASS |
| 4 | Temporary task / EVENT + expiry | Short-lived working data must not live forever | Expiring task data → disappears after expiry | `test_temporary_task_memory_expires` — PASS |
| 5 | Permanent user lesson / LESSON | Durable user knowledge requires an explicit helper call | Explicit lesson → USER memory with no expiry | `test_permanent_user_information_is_an_explicit_lesson` — PASS |
| 6 | Generated artifact / SUMMARY | Output is not automatically a FACT; artifact source is preserved | Generated output pending review + source fact → only approved active fact recalls | `test_generated_artifact_is_not_written_as_factual_memory` — PASS |
| 7 | Write approval / PENDING_REVIEW | Current approval boundary is lifecycle gating | Unapproved candidate → stored for review but not recalled | `test_pending_review_is_the_current_memory_write_approval_boundary` — PASS |
| 8 | Relevant recall | Resolver should rank useful context | Matching query → relevant memory is returned | `test_relevant_memory_is_ranked_and_recalled` — PASS |
| 9 | Irrelevant recall | Unrelated context can mislead downstream generation | Zero-score/no-overlap result → not injected | `test_clearly_irrelevant_zero_score_memory_is_not_injected` — PASS |
| 10 | User isolation | User boundary is enforced by `AccessContext` + node sets | User A query → User B memory absent | `test_other_user_memory_is_not_recalled` — PASS |
| 11 | Case isolation | Case boundary prevents same-user contamination | Case A query → Case B memory absent | `test_other_case_memory_is_not_recalled` — PASS |
| 12 | Task isolation | Task boundary prevents sibling-task leakage | Task A query → Task B memory absent | `test_other_task_memory_is_not_recalled` — PASS |
| 13 | Duplicate memory | Replays should be idempotent locally and deduped in context | Same unit twice → one local memory/context item | `test_duplicate_memory_is_idempotent_locally_and_deduplicated_in_context` — PASS |
| 14 | Conflicting FACTs | Conflict must be resolved explicitly, not by arrival order | Old + new with `supersedes` → old hidden, new recalled | `test_conflicting_information_requires_explicit_supersession` — PASS |
| 15 | Updated information | Replacement must preserve one current answer | Updated deadline → new value only | `test_updated_information_is_recalled_after_old_version_is_replaced` — PASS |
| 16 | Stale provider result | Provider data may outlive local cache | Expired provider result → rejected | `test_stale_provider_memory_is_rejected_even_without_local_store_row` — PASS |
| 17 | Provider outage | A failed dependency must not create a false local success | Backend failure → exception, no local write, safe telemetry | `test_memory_outage_fails_closed_without_local_write_or_sensitive_telemetry` — PASS |
| 18 | Empty memory | No evidence should produce no evidence | Empty backend result → empty context | `test_empty_memory_returns_empty_context` — PASS |
| 19 | Large recall | Prompt context needs a bounded budget | Large result + budget → bounded output with identity/provenance | `test_large_memory_result_is_bounded_but_keeps_provenance` — PASS |
| 20 | Provenance | Every recalled claim needs an audit trail | Source/page/pipeline/run → same fields after recall | `test_recalled_memory_preserves_provenance_for_audit` — PASS |

## Current design decisions and limits

1. There is no separate approval service or `approval_id` argument. The current
   product boundary is `MemoryLifecycle.PENDING_REVIEW`; promotion is not yet a
   first-class method. This phase tests and documents that boundary rather than
   inventing one.
2. “Irrelevant” is tested conservatively: a provider result with no query-term
   overlap and a zero score is excluded. A positive Cognee score may represent a
   semantic match even when wording differs, so this phase does not impose an
   arbitrary score threshold.
3. These are application-level contract tests. Live Cognee transport,
   persistence durability, and real semantic ranking still need a later
   integration/benchmark phase.
