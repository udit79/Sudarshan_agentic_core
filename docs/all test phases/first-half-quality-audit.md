# First-half quality engineering audit

## Purpose

This document is the memory checkpoint for Phases 0–9. It explains what was
tested, why it matters, what the tests prove, and what they do not prove.

The work follows `docs/pipeline-benchmarking.md`: correctness comes first,
then safe failure behavior, then measurable operational data, then live model
quality and human review.

## The simple picture

```text
input evidence
  → ingestion and provenance
  → scoped memory and resolver
  → pipeline contract and orchestration
  → artifact correctness
  → failure/retry/restart safety
  → status, DAG, trajectory, observability, telemetry
  → later: live provider, frontend, benchmark, charts, report
```

## WHAT / WHY / WHERE / INPUT / OUTPUT / TEST / RESULT

| Area | WHAT | WHY | WHERE | Input → expected output | Test/result |
|---|---|---|---|---|---|
| Phase 0 | Existing architecture and test inspection | Prevent invented architecture and unsafe edits | Repository modules and existing tests | Existing implementation → documented boundary | PASS; board and phase reports created |
| Phases 1–5 | Ingestion edge cases | Bad evidence must not become bad context | `ingestion/`, `tests/component/test_ingestion_matrix.py`, `tests/component/test_np10_ingestion.py` | Valid, empty, malformed, large, unsupported files → explicit safe result and provenance | PASS for deterministic matrix; one existing live-provider case skipped |
| Phases 6–16 | Memory types, recall, relevance, stale/conflicting data, isolation | Memory must be scoped and must not silently become permanent fact | `memory/`, resolver/evidence store, memory tests | User/Case/Task memory → only permitted relevant context | PASS; 20-memory-case matrix and 53-test focused regression passed |
| Phase 3 isolation | User/Case/Task content and artifact isolation | Different cases must not contaminate one another | Evidence index, `MemoryManager`, `ArtifactStore` | Case A request → Case A evidence/artifact only | PASS; 8 tests passed with content-level checks |
| Phase 5 | Pipeline contracts | Each pipeline must receive and return its actual schema | Pipeline adapters/contracts and `tests/component/test_pipeline_contract_matrix.py` | Valid/invalid requests and outputs → typed acceptance or clear rejection | PASS; 79 matrix tests and 154 affected tests passed |
| Phase 6 | Artifact correctness | A file can exist but still be corrupt, wrong, or unowned | `api/artifacts.py`, renderers, artifact tests | Candidate file → verified type, checksum, manifest, ownership | PASS; 13 focused and 205 affected tests passed |
| Phase 7 | Failure and recovery | Failure must be visible and safe, not silently converted to success | Scheduler, runtime, provider boundaries, failure matrix | Provider/memory/pipeline/render failure → typed failure, partial, retry, or cancellation | PASS; 58 matrix and 162 affected tests passed |
| Phase 8 | Duplicate execution and restart safety | Retries and concurrency must not multiply side effects | Scheduler, DAG, cache, artifact store | Duplicate/retry/parallel/timeout/cancel → controlled run and artifact identity | PASS; 8 matrix and 89 affected tests passed; true process-kill remains open |
| Phase 9 | Status, DAG, trajectory, observability, telemetry | Humans and benchmarks need a safe explanation of each run | Progress, DAG, observability, application/MCP/API projections | Successful/failure run → consistent views, safe memory/provider metadata, measured usage | PASS; 7 matrix and 149 affected tests passed |
| Phase 10 | Full regression gate | All accumulated changes must coexist | Entire repository test collection | All deterministic tests → no regression | PASS in documented local mode |

Test counts in this table are phase-specific runs. They overlap deliberately;
they must not be added together as if they were unique tests.

## First-half full regression result

### Default environment

```text
674 passed, 8 skipped, 3 failed, 32 warnings in 39.54s
```

The three failures were API health/list-pipeline tests. Application startup
defaulted to Cognee Cloud and raised `COGNEE_API_KEY is required for Cognee
Cloud` because no Cloud credentials were present.

This was not a failed ingestion, memory, pipeline, artifact, isolation, or
telemetry assertion. It exposed a test-environment requirement: full API tests
must run with configured Cloud credentials or explicit local development mode.

### Deterministic local environment

```powershell
$env:COGNEE_BACKEND = "local"
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

Result:

```text
677 passed, 8 skipped, 32 warnings in 32.49s
```

This is the clean first-half regression baseline for development. The skipped
tests are intentional opt-in/live or environment-dependent cases. The warnings
are existing dependency deprecations and an existing CrewAI telemetry export
attempt; they did not fail tests.

## What the tests actually accomplished

The work was not wasted. It produced evidence and found genuine defects,
including:

- a missing video-planner import;
- incorrect artifact inspection based only on a declared file kind;
- partial results being reported as total failures;
- artifact evidence ownership being checked before registration side effects;
- SQLite usage receipts being double-counted when the same `usage_id` was
  projected more than once.

Each correction was small, tied to a failing test, and followed by focused and
affected regression runs.

## Terms to remember

- **Contract**: the accepted input/output shape a pipeline promises.
- **Provenance**: where evidence or an artifact came from, including source and
  ownership information.
- **Isolation**: preventing one User, Case, or Task from seeing another's data.
- **Idempotency**: repeating one logical request without multiplying side
  effects.
- **DAG**: the dependency graph of execution steps; it is not the same as the
  semantic memory graph.
- **Trajectory**: the ordered operational story of recorded execution events.
- **Observability**: safe details for understanding and diagnosing a run.
- **Telemetry**: numeric measurements such as tokens, latency, cost, attempts,
  cache outcomes, and artifact counts.
- **pass@k**: at least one success in k attempts.
- **pass^k**: all k attempts succeed; this is the stronger target for contracts,
  isolation, lifecycle, and security.

## Who uses the results?

- Developer: runs focused tests while changing a component.
- CI/reviewer: runs the full deterministic regression before merge.
- Operator: uses status, trajectory, observability, and telemetry to understand
  a real run.
- Benchmark author: uses sanitized telemetry and artifact manifests for
  p50/p95 latency, token, cost, and quality comparisons.
- Human reviewer: checks visual quality and unsupported claims, which automated
  structural tests cannot prove.
- Team lead/judges: receives the final report and charts showing both quality
  and operational cost.

## What remains open

These are not evidence that the system is impossible. They are boundaries that
need more tests, credentials, deployment access, or an explicit product rule.

### NOT YET IMPLEMENTED

- Live DeepSeek/OpenAI/provider lifecycle and real token/cost receipts.
- Live Cognee Cloud and MongoDB behavior.
- True process-kill recovery while a provider request is in flight.
- Frontend end-to-end upload → run → status → artifact verification.
- Warm/cold repeated benchmarks and p50/p95 graphs.
- Golden/holdout cases, external baseline, human artifact quality review, and
  final report.

### NEEDS DESIGN DECISION

- A uniform insufficient-context policy for every pipeline.
- A formal human/automated artifact quality policy.
- Whether duplicate execution is keyed by `run_id`, `task_id`, or a dedicated
  idempotency key.
- Whether artifact writers must verify an active lease before every side effect.
- Which projection is authoritative after a crash if status and DAG disagree.
- Production retention and access rules for telemetry.

## Are we ready for live testing?

Not as the next unprepared step. We are ready to plan a controlled live canary,
but the first-half deterministic work should be preserved first.

Recommended order:

```text
personal rerun of local full regression
  → checkpoint commit
  → finish Phase 10 release gate
  → close hard-gate gaps: insufficient context and artifact quality review
  → prepare local ignored .env or secret manager
  → one controlled real API run
  → repeated benchmark runs and Matplotlib charts
```

Live testing requires credentials only when the real service is used. Do not
paste keys into chat. Use a local ignored `.env` or the team's secret manager,
and record only sanitized run summaries.

## First-half conclusion

The first half is healthy for deterministic application behavior:

- the full local regression is green;
- the board is tracked through Phase 39;
- known limitations are written down rather than hidden;
- no live-provider claim is being made prematurely;
- the implementation changes were narrow and regression-tested.

The next work is the second half: release-gate completion, real API canary,
benchmark measurements, quality review, charts, and the final report.
