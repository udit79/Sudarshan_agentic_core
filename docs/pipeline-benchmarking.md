# Pipeline benchmark and quality guide

This is the repeatable release procedure for comparing Sudarshan pipelines.
It separates deterministic correctness from model quality and provider
latency. Do not call a pipeline “good” from a single successful demo.

## 1. Fast regression gate

Run this before any benchmark:

```powershell
.venv\Scripts\python.exe -m pytest -q --basetemp=.pytest-tmp-regression
```

Focused checks by pipeline:

| Pipeline | Main checks |
| --- | --- |
| Advisory | `pipelines/tests/test_advisory_pipeline.py`, `tests/component/test_np09_pipelines.py` |
| Executive summary | `pipelines/tests/test_text_pipelines.py`, `tests/component/test_np09_pipelines.py` |
| LinkedIn | `pipelines/tests/test_text_pipelines.py`, `tests/component/test_np09_pipelines.py` |
| Presentation/PPT | `tests/pipeline/test_ppt_tasks.py`, `tests/component/test_ppt_p0_contracts.py`, `tests/component/test_np06_incremental.py`, `tests/component/test_presentation_quality.py` |
| Infographic | `pipelines/tests/test_infographic_pipeline.py`, `tests/pipeline/test_infographic_render.py`, `tests/component/test_json_renderer_contracts.py` |
| Diagram/visual flowchart | `tests/component/test_diagram_adoption.py`, `tests/component/test_json_renderer_contracts.py` |
| Video | `tests/pipeline/test_video_pipeline.py`, `tests/component/test_video_adapter.py`, `tests/component/test_np09_pipelines.py` |
| Ingestion | `tests/component/test_np10_ingestion.py` (governed ingestion only) |
| MCP/A2A boundary | `tests/component/test_np11_mcp_a2a.py`, `tests/component/test_a2a.py`, `tests/component/test_harness_parity.py` |

## 2. Benchmark harness

Use the same frozen fixtures for every provider and run mode:

1. Warm the process once; discard the warm-up result.
2. Run each case 10 times in a fresh logical `run_id` with a fixed seed.
3. Run both serial and allowed-parallel modes.
4. Record p50/p95 wall time, queue time, provider time, attempts, tokens,
   estimated cost, cache hit rate, artifact count, partial/failure rate, and
   peak concurrency.
5. Save only sanitized run summaries, event trajectories, quality reports, and
   artifact manifests. Never save prompts, raw memory, credentials, or hidden
   reasoning in benchmark output.

The comparison must use the same request fingerprint, evidence fixture,
classification, model policy, and quality thresholds. A provider that is
faster but returns a degraded or constraint-invalid artifact is not a better
result.

Recommended benchmark record:

```json
{
  "case": "ppt_exact_two_slides",
  "pipeline": "presentation",
  "run_id": "run-...",
  "status": "succeeded",
  "quality_status": "passed",
  "degraded": false,
  "wall_ms": 0,
  "queue_ms": 0,
  "provider_ms": 0,
  "attempts": 1,
  "tokens": {"provider": 0, "estimated": 0, "reconciled": 0},
  "cache": {"hit": false},
  "artifacts": [{"artifact_id": "artifact-...", "sha256": "..."}],
  "issues": []
}
```

## 3. Quality scorecard

Score each case as pass/fail for the hard gates, then report soft quality
separately. A single hard-gate failure makes the case blocked, regardless of
the model’s narrative quality.

Hard gates for every pipeline:

- typed output validates;
- evidence references resolve and remain within User/Case/Task scope;
- classification and distribution are preserved;
- no unapproved output is written as durable case FACT memory;
- status, attempt, usage, trajectory, and artifact manifest agree;
- timeout, cancellation, retry, and duplicate-admission behavior is explicit.

Pipeline-specific gates:

- Advisory: evidence-linked recommendations, quality review, human approval,
  approval-aware memory write-back.
- Executive summary: every factual key finding cites evidence; no unresolved
  placeholders; useful compression without unsupported claims.
- LinkedIn: claim bindings, humanizer threshold, AI-tell rejection, and no
  accidental publication while provider state is pending.
- Presentation: exact total/content slide semantics, theme/colors/layers,
  readable layout, stable `slide_id`, and one-slide revision isolation.
- Infographic: native/fallback mode is truthful, safe SVG export, palette and
  accessibility token survival, and no `foreignObject`.
- Diagram: valid graph structure, readable labels, safe export, deterministic
  fallback labeling, and required diagram type preserved.
- Video: valid media files, scene-level retry/resume, audio ownership,
  provider reconciliation, and explicit partial/degraded output.

## 4. Test-quality measurement

Track these numbers per pipeline, not only total test count:

- contract coverage: valid, invalid, boundary, and unauthorized inputs;
- failure-injection coverage: provider error, timeout, cancellation, cache
  miss, stale lease, malformed output, and memory outage;
- artifact coverage: structural validation, visual inspection, and round-trip
  or checksum checks where applicable;
- release coverage: successful, partial, blocked, approval-pending, and retry
  states;
- isolation coverage: duplicate run, parallel child runs, restart recovery,
  and cross-case access attempts.

Use a small golden set of real-shaped, sanitized cases rather than a large
synthetic prompt list. Keep a holdout set that is not used to tune prompts.
Review trajectories and quality reports for every failed case; pass rate alone
does not reveal redundant tool calls, silent fallbacks, or evidence leakage.

## 5. Release thresholds

Before enabling a pipeline for real users:

- 100% hard-gate pass on the release fixture set;
- 0 duplicate logical runs in retry tests;
- 0 unauthorized evidence or memory writes;
- 0 silent fallback promotions;
- 0 missing or double-counted usage receipts;
- p95 latency and token cost recorded for both warm and cold runs;
- all partial/degraded outcomes visible in status, trajectory, and manifests.

Model preference, provider choice, and prompt changes should be accepted only
when the holdout quality is not worse and the operational metrics improve or
stay within the agreed budget.

## 6. Run and inspect one pipeline locally

Start the API with the repository environment, then submit a run. The
following example exercises the native PPT path with a hard two-slide
constraint. Use a new `task_id` and `metadata.run_id` for each benchmark case.

```powershell
$base = "http://127.0.0.1:8000"
$operator = "local-operator"
$case = "case-benchmark"
$task = "task-ppt-2-slides-001"
$headers = @{
  "x-operator-id" = $operator
  "x-case-id" = $case
  "x-classification-level" = "RESTRICTED"
}
$body = @{
  query = "Create exactly 2 pages about the case findings"
  user_id = $operator
  case_id = $case
  task_id = $task
  requested_pipelines = @("presentation")
  constraints = @{
    slide_count = 2
    page_count = 2
    theme_id = "ntro-briefing"
    color_palette = @("#0F172A", "#38BDF8")
  }
  metadata = @{ run_id = "run-ppt-2-slides-001" }
} | ConvertTo-Json -Depth 8

$queued = Invoke-RestMethod -Method Post -Uri "$base/runs" `
  -Headers $headers -ContentType "application/json" -Body $body
$runId = $queued.run_id
$runId
```

Poll the run and inspect every projection:

```powershell
do {
  $status = Invoke-RestMethod "$base/runs/$runId"
  "$($status.status) $($status.stage)"
  Start-Sleep -Seconds 2
} while ($status.status -notin @("succeeded", "partial", "failed", "cancelled", "completed"))

$dag = Invoke-RestMethod "$base/runs/$runId/dag" -Headers $headers
$trajectory = Invoke-RestMethod "$base/runs/$runId/trajectory" -Headers $headers
$observability = Invoke-RestMethod "$base/runs/$runId/observability" -Headers $headers
$telemetry = Invoke-RestMethod "$base/runs/$runId/telemetry"

$dag.nodes | Select-Object node_id, skill_id, status, lane_id, attempt_id
$trajectory.lanes
$trajectory.events | Select-Object event_type, stage, status, node_id, child_id, lane_id, fallback, provider_request_id
$observability.events | Where-Object { $_.event_type -like "memory.*" } |
  Select-Object event_type, backend, operation, query_hash, backend_result_count, accepted_result_count, trace_id, duration_ms
$telemetry
$status.response.artifacts
```

What each view proves:

| View | Use it to verify |
| --- | --- |
| `/runs/{id}` or status MCP tool | user-visible lifecycle, quality state, errors, returned artifact references |
| `/events` or `get_sudarshan_status` | ordered frontend progress and incremental polling cursor |
| `/dag` or `get_sudarshan_dag` | durable dependencies, child status, repair state, and parallel branches |
| `/trajectory` or `get_sudarshan_trajectory` | safe timeline and grouped parallel lanes for Harness display |
| `/observability` or `get_sudarshan_observability` | Cognee/memory lifecycle, provider receipts, cache, fallback, and timing metadata |
| `/telemetry` or `get_sudarshan_usage` | duplicate-safe token, cost, latency, and cache totals |

Cognee results are intentionally not printed into trajectory or operator
telemetry. A completed recall event proves which backend ran, the hashed query,
requested and accepted counts, bounded retrieval trace ID, and duration. The
actual bounded context must be inspected through the authorized evidence or
development memory boundary; never add raw case text to benchmark logs.

## 7. Focused test commands by pipeline

Run the focused contract tests first, then the full suite. These commands use
the checked-in tests and do not require live provider credentials:

```powershell
# Advisory, executive summary, and LinkedIn
.venv\Scripts\python.exe -m pytest -q pipelines/tests/test_advisory_pipeline.py pipelines/tests/test_text_pipelines.py tests/component/test_np09_pipelines.py

# Presentation/PPT, including exact count, theme, quality, and incremental edit
.venv\Scripts\python.exe -m pytest -q tests/pipeline/test_ppt_tasks.py tests/component/test_ppt_p0_contracts.py tests/component/test_presentation_quality.py tests/component/test_np06_incremental.py tests/component/test_ppt_master_adapter.py

# Infographic and diagram
.venv\Scripts\python.exe -m pytest -q tests/pipeline/test_infographic_render.py tests/component/test_json_renderer_contracts.py tests/component/test_diagram_adoption.py

# Video and provider lifecycle
.venv\Scripts\python.exe -m pytest -q tests/pipeline/test_video_pipeline.py tests/component/test_video_adapter.py tests/component/test_np09_pipelines.py

# Ingestion, memory, MCP, A2A, DAG, and trajectory
.venv\Scripts\python.exe -m pytest -q tests/component/test_np10_ingestion.py tests/component/test_np11_mcp_a2a.py tests/component/test_a2a.py tests/component/test_trajectory_projection.py tests/component/test_dag.py

# Release gate
.venv\Scripts\python.exe -m pytest -q --basetemp=.pytest-tmp-release
```

For each pipeline, record at least one successful, partial/degraded, blocked,
timeout/cancelled, malformed-output, and duplicate-retry case. A green unit
test is a contract result; it is not evidence that a live model produces
useful content. Live benchmarking additionally needs sanitized fixtures,
provider receipts, artifact inspection, and human review of the holdout set.
