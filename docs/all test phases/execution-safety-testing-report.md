# Phase 8 — Duplicate execution, concurrency, and restart safety

## WHAT

This phase tests whether repeated and parallel execution remains controlled:

- one logical request should not create multiple logical runs accidentally;
- retries should use the existing run identity;
- parallel branches should keep their own scope and artifacts;
- a late provider result should not overwrite a terminal timeout;
- artifact registration should be idempotent for the same run and content;
- durable state should support restart and resume.

Idempotency means that repeating the same logical request produces one
controlled result rather than multiplying side effects. In this repository,
the scheduler uses `run_id` plus a request hash for run admission, while the
artifact store derives a stable artifact ID from `run_id`, kind, and content
hash.

## WHY

Production workers retry, overlap, restart, and receive late responses. Without
these controls, a user could receive two artifacts, usage could be charged
twice, or Case A could receive a result from Case B.

## WHERE

- Run admission, request hashing, attempts, leases, timeout, cancellation, and
  durable queue state: `api/scheduler.py`
- Shared admission and fencing primitives: `api/control_plane.py`
- DAG child submission, parallel branches, and restart hydration:
  `api/dag_scheduler.py` and `pipelines/orchestrator/dag.py`
- Child parallelism and cache claims: `pipelines/orchestrator/skill_runtime.py`
  and `pipelines/orchestrator/cache.py`
- Stable artifact identity and manifest reuse: `api/artifacts.py`
- Usage deduplication: `pipelines/orchestrator/budget.py` and
  `pipelines/orchestrator/observability.py`
- Existing restart/parallel evidence:
  `tests/component/test_shared_scheduler.py`,
  `tests/component/test_reliability.py`,
  `tests/component/test_distributed_dag.py`, and
  `tests/pipeline/test_pipeline_contracts.py`

## INPUT → OUTPUT

`same request / retry / parallel worker / restart / late response → admission state → execution state → artifact and usage state`

The tests use local SQLite stores, controlled worker functions, short bounded
delays, and deterministic artifact content. They do not contact real providers.

## Test matrix

| Case | Expected behavior | Evidence | Result |
|---|---|---|---|
| Same request submitted twice | One `run_id`, one queue record, one execution, replay for later submissions | New matrix and shared scheduler tests | PASS |
| Same run retried | Same logical run, attempt increments, transient failure retries once within policy | New matrix and scheduler retry logic | PASS |
| Same task executed concurrently | Current scheduler permits two run IDs with the same task ID | New matrix | PASS; NEEDS DESIGN DECISION |
| Two child pipelines in parallel | Separate branches finish without corrupting each other | Pipeline fan-out tests and new case-parallel test | PASS |
| Parent run interrupted | Cooperative cancellation reaches worker and terminal state is `cancelled` | New matrix and runtime tests | PASS |
| Process restart during execution | Durable queued/running state can be reclaimed or resumed by a new worker | Shared scheduler and reliability tests | PASS for deterministic restart fixtures |
| Provider response after timeout | Timeout remains terminal; late returned artifact reference is not committed to scheduler state | New matrix | PASS |
| Artifact generation completes twice | Same run/content returns one stable manifest | New matrix and artifact store | PASS |
| Duplicate artifact admission | Existing manifest is reused instead of a second logical artifact | New matrix | PASS |
| Resume after restart | Durable DAG/progress records replay from the stored cursor/state | Reliability and distributed DAG tests | PASS for deterministic coverage |

## New tests

`tests/component/test_execution_safety_matrix.py` adds eight focused tests:

1. Concurrent duplicate run submission.
2. Conflicting reuse of an existing run ID.
3. Same-run transient retry and attempt counting.
4. Same-task/different-run behavior.
5. Parallel case-scoped execution and artifact references.
6. Late provider response after scheduler timeout.
7. Cooperative cancellation of a running parent.
8. Duplicate artifact registration.

## RESULT

### Baseline

Existing Phase 8-related tests passed:

```text
81 passed in 13.33s
```

### New matrix

```text
8 passed in 1.13s
```

### Classification

**PASS**

- Same request replay and conflicting request detection work through the
  scheduler's run identity and request hash.
- Same-run retry increments the attempt count without creating a second
  logical admission.
- Parallel Case A and Case B executions retain separate case IDs, queries, and
  artifact references.
- Cooperative cancellation produces a terminal `cancelled` state.
- A late response after a scheduler timeout cannot overwrite the terminal
  failure or add its returned artifact reference to scheduler state.
- Duplicate artifact registration reuses the stable manifest.
- Existing durable DAG, progress, shared queue, cache lease, and usage
  reconciliation tests cover restart, resume, and duplicate accounting.

**FAIL**

- None in the new deterministic matrix.

**NOT YET IMPLEMENTED**

- A real process-kill test while a provider call is in flight. The current
  tests recreate workers and stores safely; they do not terminate a production
  process or network connection.
- Real distributed multi-worker concurrency against Redis/control-plane
  infrastructure.
- Live provider idempotency-key behavior and late HTTP response behavior.
- A complete artifact transaction/fencing mechanism for an uncooperative
  provider that writes bytes after the scheduler timeout.

**NEEDS DESIGN DECISION**

- The scheduler deduplicates by `run_id`. It currently allows two different
  run IDs with the same `task_id` to execute concurrently. Decide whether
  `task_id` is a reusable task scope or must also be an idempotency key.
- The scheduler ignores a late result after timeout, but it cannot forcibly
  stop arbitrary Python worker threads. Decide whether artifact writers must
  validate an active lease/fencing token before every side effect.
- Decide whether a retried provider submission needs an external provider
  idempotency key to prevent duplicate upstream jobs.

## Usage and status safety

The existing usage reconciliation tests deduplicate records by `usage_id` and
aggregate attempts separately from the logical run. The scheduler stores one
attempt count per `run_id`, while observability aggregates only sanitized usage
fields. This proves the local accounting contract; it does not reconcile a
real provider invoice.

The operator should see one logical run with an attempt count, current status,
artifact references, and safe timing/usage totals. A retry is not a new user
request, and a late provider response must not turn a failed run into success.

## Case isolation

The new parallel test uses two cases with different queries and requires the
resulting scheduler states and artifact references to retain their matching
case. This is stronger than checking that IDs differ: it checks that the
returned result for Case A contains the Case A artifact and the Case B result
contains the Case B artifact.

## Hands-on command

Run the Phase 8 matrix and affected regression yourself:

```powershell
$runStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$base = Join-Path $env:TEMP "sudarshan-phase8-$runStamp"
.venv\Scripts\python.exe -m pytest `
  tests/component/test_execution_safety_matrix.py `
  tests/component/test_shared_scheduler.py `
  tests/component/test_distributed_dag.py `
  tests/component/test_dag_scheduler.py `
  tests/component/test_dag.py `
  tests/component/test_np08_dag.py `
  tests/component/test_distributed_cache.py `
  tests/component/test_cache.py `
  tests/component/test_skill_runtime.py `
  tests/component/test_usage_reconciliation.py `
  tests/component/test_artifact_store.py `
  tests/pipeline/test_pipeline_contracts.py `
  tests/pipeline/test_video_pipeline.py `
  -q --basetemp=$base -p no:cacheprovider
```

No provider credentials are required for this command. It is a deterministic
execution-safety check, not a real API benchmark.

## Next step

After personally rerunning this command, commit the Phase 8 checkpoint. Then
move to Phase 9 observability and telemetry so real API tests can later capture
wall time, provider time, queue time, attempts, tokens, cost, cache outcomes,
and artifact quality without exposing sensitive data.
