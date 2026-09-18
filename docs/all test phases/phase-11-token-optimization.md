# Phase 11A — Token optimization and provider budget control

Date: 2026-09-18  
Status: additive reservation ledger implemented; benchmark preflight wiring remains open
Scope: safe token measurement and allocation before further paid live runs

## WHAT

This subphase controls how many model tokens a pipeline is allowed to use and
records where those tokens are spent.

It is part of Phase 11 because a real-case benchmark is incomplete if it can
produce an artifact but cannot reliably measure or control provider usage.

## WHY

The latest controlled G01 executive-summary run used:

- configured provider budget: `12,000` tokens;
- provider-reported input tokens: `54,165`;
- provider-reported output tokens: `11,919`;
- provider-reported total used for the benchmark: `66,084` tokens;
- wall time: `55,399 ms`;
- artifacts released: `0`;
- final state: safely failed with `PROVIDER_TOKEN_BUDGET_EXCEEDED`.

This is an important safety finding. The system rejected the result, but the
current route is not yet cost-bounded before the first multi-agent attempt.

## WHERE

- `pipelines/orchestrator/spend_guard.py` tracks observed usage and prevents
  unsafe retries. Its current contract deliberately does not claim to stop
  the first provider attempt before usage is known.
- `pipelines/common/text_generation.py` creates the bounded prompt inputs,
  chooses per-call completion limits, and runs the CrewAI text crew.
- `pipelines/common/usage_capture.py` records sanitized provider counters and
  CrewAI wall time.
- `docs/pipeline-benchmarking.md` defines the benchmark record, repeated runs,
  p50/p95 latency, tokens, cost, artifacts, and sanitized output rules.

## INPUT

The future control layer may use only bounded, non-sensitive metadata:

- pipeline and stage name;
- estimated input-token count;
- output-token limit;
- maximum provider calls;
- remaining run budget;
- actual provider-reported counters after a call;
- stage duration and terminal status.

It must not store raw prompts, raw evidence, recalled memory, credentials, or
hidden reasoning in benchmark records.

## OUTPUT

The target benchmark record should distinguish:

```json
{
  "pipeline": "executive_summary",
  "budget": {
    "configured_total": 0,
    "reserved": 0,
    "used": 0,
    "remaining": 0,
    "status": "within_budget"
  },
  "usage": {
    "input_tokens": 0,
    "output_tokens": 0,
    "reasoning_tokens": 0,
    "cache_read_tokens": 0,
    "usage_status": "provider_reported"
  },
  "stages": [],
  "artifact_count": 0
}
```

The numbers above are schema examples only. They are not measurements.

## REQUIRED CONTROL DESIGN

The implementation should be added in small, reviewable steps:

1. **Per-pipeline profile**
   Define total budget, input limit, output limit, and maximum provider calls
   separately for each pipeline. A PPT and a short summary should not share an
   arbitrary identical allowance.

2. **Preflight estimation**
   Estimate the next provider call before starting it. If the estimated call
   cannot fit the remaining budget, stop with a clear budget status.

3. **Reservation**
   Reserve the estimated amount before the provider call. A reservation is an
   internal accounting hold; it is not a claim that the provider billed that
   amount.

4. **Provider receipt reconciliation**
   Replace the reservation with actual provider-reported usage when available.
   Keep estimated and actual values separate.

5. **Context reduction**
   Pass one bounded evidence/context digest to each stage where possible. Do
   not repeatedly carry full memory, full prior outputs, or duplicated task
   instructions when the stage does not need them.

6. **Safe termination**
   If the budget is exhausted or the provider receipt is unavailable after an
   attempted call, do not retry automatically and do not publish an artifact.

7. **Sanitized telemetry**
   Record stage names, counts, hashes/IDs, durations, and statuses—not the raw
   content that caused the counts.

## TEST PLAN

Before restoring an LLM key, add offline tests for:

- preflight rejection when the next call cannot fit;
- successful reservation within the remaining budget;
- reconciliation of estimated and actual counters;
- no retry after budget exhaustion;
- no artifact release after budget rejection;
- no generated-content memory write after budget rejection;
- no double counting of cache-read tokens;
- separate accounting for input, output, reasoning, and cache-read tokens;
- unchanged default behaviour when no explicit budget is supplied;
- repeated runs producing the same decision for the same sanitized inputs.

Budget and isolation controls should target `pass^k`: every repeated run must
obey the same safety rule. Model quality may later use `pass@k`, but a single
successful run must never override a budget or security failure.

## CURRENT IMPLEMENTATION CHECKPOINT

`TokenBudgetReservation` now exists in
`pipelines/orchestrator/spend_guard.py`. It is a small in-memory accounting
component that can:

- reserve a projected amount before a provider call;
- reject a reservation that cannot fit the remaining cap;
- reconcile the reservation with actual provider-reported usage;
- fail closed if actual usage exceeds the configured cap; and
- expose only counters and status, never sensitive inputs.

Focused offline results: **28 passed**. The affected text/pipeline regression
with an isolated temporary directory: **111 passed**. The full offline
regression then passed **722 tests, 8 skipped, 32 warnings**. No provider call
or API key was used.

The reservation ledger is connected to an explicit
`provider_budget_preflight=true` benchmark-only switch. The switch requires a
pipeline profile containing input budget, output budget, and provider-call
count. Missing or over-budget profiles fail before CrewAI execution. The
default path remains unchanged. A future checkpoint can refine profiles and
reconcile receipts at finer per-stage boundaries.

### Executive-summary profile checkpoint

`pipelines/orchestrator/budget_profiles.py` now contains an explicit,
unapproved diagnostic profile for the recorded G01 executive-summary run. It
uses only the observed aggregate receipt of 54,165 input tokens and 11,919
output tokens across four stages. The rounded reservation is greater than the
configured 12,000-token budget, so the profile fails closed before execution.

This is intentionally not a cheaper production recommendation. It proves that
the current route cannot honestly be approved for another paid run until the
context and stage allocation are reduced and measured again.

### G01 dynamic-input audit

The offline prompt audit was run against the sanitized G01 fixture with a
1,500-token dynamic-input allowance. It measured **165 estimated dynamic
tokens** in total:

- memory context: 387 characters, 97 estimated tokens;
- prompt plan: 69 characters, 18 estimated tokens;
- request understanding: 33 characters, 9 estimated tokens;
- query: 54 characters, 14 estimated tokens;
- all other dynamic metadata together: 27 estimated tokens.

This is an important diagnosis: the original 54,165 provider input tokens
cannot be explained by the raw G01 evidence alone. The remaining input cost is
likely in provider/system instructions, agent/task prompt templates, tool
interactions, or repeated intermediate task output. The audit does not guess
which one; the next measurement must capture sanitized per-stage provider
receipts or equivalent boundary counters.

### Stage-level usage checkpoint

CrewAI task outputs now contribute separate sanitized stage usage records from
the existing task callback boundary. Each record contains only the stage name,
attempt, input/output/reasoning counters, cache counters, and usage status. The
records are attached to the pipeline usage record for diagnosis but are not
added again to the aggregate total.

Focused usage, prompt-audit, and budget tests passed **39**. The full offline
regression then passed **723 tests, 8 skipped, 32 warnings**. This prepares the
next live run to show which task stages consume input tokens; it does not yet
reduce provider usage by itself.

The benchmark-only `provider_context_compaction=true` option now replaces
verbose intermediate raw task output with the validated structured JSON before
CrewAI passes that output to a later task. The default path remains unchanged.
The focused context/usage/budget tests passed **45**, and the full offline
regression passed **724 tests, 8 skipped, 32 warnings**.

## LIVE RE-ENTRY GATE

Do not restore the LLM key until all of these are true:

- offline token-control tests pass;
- the full regression passes;
- the token-control report is updated;
- the exact G01 live budget is written down before execution;
- the run is limited to one controlled attempt;
- the operator knows how to stop the server and inspect the resulting record.

The first live rerun should be G01 only. It should verify both:

1. the system stays within the declared budget; and
2. one valid artifact is produced, validated, and scoped to the correct case.

## CURRENT CLASSIFICATION

| Item | Status |
|---|---|
| Existing usage capture | PASS, provider-dependent |
| Existing retry spend guard | PASS for post-attempt retry containment |
| Reservation ledger | PASS, offline and benchmark-wired |
| Pre-call declared-budget enforcement | PASS, opt-in |
| Executive-summary diagnostic profile | PASS, deliberately rejected |
| G01 dynamic-input audit | PASS, 165 estimated dynamic tokens |
| Stage-level usage capture | PASS, offline; live receipt pending |
| Opt-in intermediate context compaction | PASS, offline; live effect pending |
| Provider-call exact total enforcement | NOT YET PROVEN |
| Per-stage token ledger | PASS, live receipt pending |
| Reconciled currency cost | NOT YET MEASURED |
| Successful live G01 artifact | NOT YET PROVEN |
| Phase 11 complete | NO |

## RELATION TO THE PLUGIN, MCP, AND A2A DIRECTION

This work supports future isolated pipelines and plugin execution because each
pipeline can eventually carry its own provider budget profile and sanitized
usage receipt. MCP and A2A boundaries should receive status, artifacts, and
safe usage metadata; they should not receive provider credentials, raw memory,
or hidden reasoning.

The token-control layer belongs at the application/provider boundary. It does
not require changing the MCP or A2A protocol shape now.

## NEXT CHECKPOINT

The next implementation checkpoint is an additive offline preflight/reservation
component plus focused tests. It should be enabled explicitly for benchmark
runs first. The normal unbudgeted path must remain unchanged until the focused
and affected regression tests pass.
