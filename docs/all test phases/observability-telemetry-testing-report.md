# Phase 9 — Observability and telemetry testing report

## WHAT

This phase checks whether one run can be explained through safe, consistent
projections:

- **Status**: the current user-visible lifecycle state.
- **Events**: the ordered progress updates that a frontend can poll or stream.
- **DAG**: the durable dependency graph of parent and child work.
- **Trajectory**: the safe timeline of recorded work, grouped into parallel
  lanes.
- **Observability**: operator-facing details such as memory operations,
  provider receipts, cache outcomes, errors, and timing.
- **Telemetry**: numeric totals such as tokens, latency, cost, attempts, and
  artifact counts.

These are different views of the same run. They should agree about the final
state without exposing prompts, raw memory, model output, credentials, or
hidden reasoning.

## WHY

The benchmark specification says that a pipeline must be judged by more than a
successful response. Operators need to know what happened, users need a clear
status, and benchmark reports need reproducible latency and usage numbers.
Safe projections also reduce the chance that sensitive case information is
written into logs or exported to a telemetry collector.

## WHERE

- Frontend-safe status and progress events:
  `pipelines/orchestrator/progress.py` and
  `integrations/deepseek_harness/application.py`
- Safe operator events and aggregate telemetry:
  `pipelines/orchestrator/observability.py`
- Durable dependency graph:
  `pipelines/orchestrator/dag.py`
- Public application/MCP/API projections:
  `integrations/deepseek_harness/application.py`,
  `integrations/deepseek_harness/mcp_server.py`, and `api/server.py`
- Artifact manifest and checksum boundary: `api/artifacts.py`
- Memory lifecycle event producers: `memory/memory_manager.py`
- Specification followed: `docs/pipeline-benchmarking.md`
- New matrix: `tests/component/test_observability_telemetry_matrix.py`

## INPUT → OUTPUT

The tests feed safe synthetic lifecycle events for successful and failed runs,
including memory recall, provider information, usage, latency, artifacts, and
DAG transitions.

Expected output:

```text
run activity
  → status/events/DAG/trajectory/observability/telemetry projections
  → consistent terminal state, safe details, matching artifact references
```

## View guide

| View | What does it tell us? | Who uses it? | Why does it exist? |
|---|---|---|---|
| Status | Current state, stage, progress, quality, errors, and result references | User, frontend, Harness | The user needs a clear answer about whether work is queued, running, partial, failed, or complete | 
| Events | Ordered lifecycle updates and a replay cursor | Frontend and API client | Polling or streaming clients can resume without losing progress | 
| DAG | Nodes, dependencies, branches, node status, and output references | Orchestrator and operator | Parallel work must be understood through dependencies, not only a flat timeline | 
| Trajectory | Safe ordered execution story and parallel lanes | Harness and operator | It explains the path taken while remaining separate from model reasoning | 
| Observability | Memory/provider/cache/error details with bounded metadata | Operator and developer | Failures need diagnosis without storing raw case content | 
| Telemetry | Aggregated tokens, latency, cost, cache, children, artifacts, and waits | Benchmark author and operator | Quality comparisons need measurable operational data | 
| Artifact manifest | Ownership, checksum, type, quality, and evidence references | API, frontend, reviewer | A returned artifact must be verifiable and scoped to its run/case | 

## Test matrix and results

| Case | Expected behavior | Evidence | Result |
|---|---|---|---|
| Successful run | Status, progress, memory, provider, artifact, and usage views describe one successful run | New matrix success projection test | PASS |
| Failed run | Memory/provider failure codes and latency are visible; raw error content is absent | New matrix failure projection test | PASS |
| Status consistency | Final progress status, application summary, and telemetry last status agree | New matrix status consistency test | PASS |
| Events | Events are ordered and contain safe lifecycle fields | Existing `test_observability.py`, new matrix | PASS |
| DAG | Completed nodes, dependencies, terminal run status, and artifact references agree | New matrix plus `test_dag.py` | PASS |
| Trajectory | Recorded memory/provider events appear in the correct lanes | New matrix plus `test_trajectory_projection.py` | PASS |
| Memory observability | Recall operation, backend, counts, hash, trace ID, and duration are visible | New matrix plus memory tests | PASS |
| Provider information | Provider request ID and safe usage metadata are visible | New matrix | PASS |
| Artifact manifest | Manifest checksum, byte size, ownership, and stored bytes agree | New matrix plus artifact tests | PASS |
| Usage deduplication | Repeated receipt with the same `usage_id` counts once | New matrix | PASS after product fix |
| Sensitive-data redaction | Raw memory, raw provider errors, and model output are not projected | New matrix plus observability tests | PASS |

## Initial test result and correction

The first draft of the new matrix had two fixture errors:

1. The Windows test file was written with CRLF bytes, while the expected hash
   was calculated from an LF-only string.
2. The test used SQLite `:memory:` even though the store opens separate
   connections, making the schema connection-local.

Those were corrected in the test setup. The corrected run then exposed one
real product defect: SQLite observability summaries added duplicate usage
events instead of applying the existing `usage_id` deduplication rule.

## Product change

`pipelines/orchestrator/observability.py` now:

1. preserves `ProgressEvent.usage_id` when converting progress into an
   observability event; and
2. uses the existing `_summary_from_events` implementation for SQLite
   summaries, so repeated usage receipts are counted once.

This is a narrow telemetry correction. It does not change scheduling,
pipeline execution, memory contents, artifact generation, or provider calls.

## Automated results

### New Phase 9 matrix

```text
7 passed in 0.53s
```

### Affected regression

```text
149 passed, 1 warning in 13.66s
```

The warning is an existing dependency warning from Pydantic settings and is
not caused by this phase.

## Classification

### PASS

- Safe successful and failed run projections.
- Status/events/telemetry agreement for the tested lifecycle.
- DAG status, node completion, dependency edge, and artifact-reference
  agreement.
- Trajectory lane grouping.
- Memory lifecycle visibility without raw memory text.
- Provider request and safe usage visibility.
- Artifact manifest checksum, byte size, ownership, and content agreement.
- Duplicate-safe SQLite token and latency totals.
- Existing tamper-evident observability storage and role boundary tests.

### FAIL

None in the corrected Phase 9 matrix or affected regression.

### NOT YET IMPLEMENTED

- Live-provider receipts and invoice reconciliation.
- Production collector dashboards and alerting.
- Warm/cold p50/p95 benchmark aggregation across ten real provider runs.
- Cross-process telemetry comparison against deployed Redis infrastructure.
- Human interpretation of whether the trajectory is operationally useful.

### NEEDS DESIGN DECISION

- Define the authoritative source when status, DAG, and progress disagree after
  a crash. The current design treats the durable DAG as authoritative for
  dependencies and the scheduler/application state as authoritative for run
  lifecycle.
- Decide whether telemetry should expose estimated and provider-reconciled
  usage as separate benchmark fields at every API boundary.
- Define retention and access policy for operator telemetry in deployment.

## Hands-on command

Run the Phase 9 matrix and affected regression locally:

```powershell
$runStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$base = Join-Path $env:TEMP "sudarshan-phase9-$runStamp"

.venv\Scripts\python.exe -m pytest `
  tests/component/test_observability_telemetry_matrix.py `
  tests/component/test_observability.py `
  tests/component/test_trajectory_projection.py `
  tests/component/test_application_boundary.py `
  tests/component/test_memory_behaviour_matrix.py `
  memory/tests `
  tests/component/test_failure_recovery_matrix.py `
  tests/component/test_execution_safety_matrix.py `
  tests/component/test_shared_scheduler.py `
  tests/component/test_distributed_dag.py `
  tests/component/test_dag_scheduler.py `
  tests/component/test_dag.py `
  tests/component/test_np08_dag.py `
  tests/component/test_usage_reconciliation.py `
  tests/component/test_artifact_store.py `
  tests/component/test_artifact_correctness_matrix.py `
  -q --basetemp=$base -p no:cacheprovider
```

No provider, MongoDB, Cognee Cloud, or API credentials are required for this
deterministic phase.

## Relation to live testing

This phase prepares the measurements required by
`docs/pipeline-benchmarking.md`: wall time, queue/provider timing, attempts,
tokens, estimated cost, cache outcomes, artifact count, and partial/failure
state.

It does not prove that a live model produces good content. The recommended
order remains:

```text
Phase 9 telemetry
  → Phase 10 full regression
  → unresolved hard gates such as insufficient-context policy and human
    artifact review
  → controlled live API canary
  → repeated benchmark runs and charts
```
