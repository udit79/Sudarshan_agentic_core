# Phase 7 — Failure and recovery testing

## WHAT

This phase tests whether the system fails safely and communicates its state
clearly when a provider, pipeline, memory backend, cache, renderer, or worker
fails.

The key distinction is:

- **Failure detection:** the system notices that something went wrong.
- **Safe recovery behavior:** the system returns an honest status, avoids fake
  artifacts and unsafe memory writes, records bounded usage, and gives the
  operator enough information to act.

## WHY

An error message alone is not enough. A provider may fail after producing a
partial result, a retry may create a duplicate artifact, or a memory outage may
hide the original pipeline error. These tests check the complete lifecycle
instead of only checking for exceptions.

## WHERE

- Child execution, timeout, cancellation, cache claim release, and usage:
  `pipelines/orchestrator/skill_runtime.py`
- Frontend-safe lifecycle projection:
  `integrations/deepseek_harness/application.py` and
  `pipelines/orchestrator/progress.py`
- Sanitized operator/telemetry projection:
  `pipelines/orchestrator/observability.py`
- Provider error classification and cooldown:
  `integrations/providers/receipts.py` and
  `integrations/providers/router.py`
- External HTTP worker protocol:
  `integrations/providers/moneyprinterturbo/client.py`
- Memory write protection for generated output:
  `pipelines/common/release_gate.py`
- Cache entries, misses, leases, and expiry:
  `pipelines/orchestrator/cache.py`
- Durable queue, lease fencing, and restart recovery:
  `api/control_plane.py`, `api/scheduler.py`, and
  `tests/component/test_shared_scheduler.py`
- Video scene retry and partial packages:
  `pipelines/video/native_generator.py` and
  `tests/component/test_reliability.py`

## INPUT → OUTPUT

The Phase 7 failure flow is:

`controlled failure → internal result → public status/event → artifact and memory decision → retry or recovery`

The tests use local doubles and injected failures. They do not contact a real
provider. This makes the result repeatable and safe for ordinary development.

## Failure matrix

| Failure or recovery case | Expected safe behavior | Current evidence | Classification |
|---|---|---|---|
| Provider exception | Child fails with a typed failure result, no fabricated artifact, safe event | `test_failure_recovery_matrix.py` | PASS |
| HTTP error | Worker boundary raises a controlled error; provider classification can enter cooldown | New matrix and provider tests | PASS |
| Timeout | Status is failed with `CHILD_TIMEOUT`; no late artifact or usage event is accepted | New matrix and `test_skill_runtime.py` | PASS |
| Cancellation | Status is cancelled and cancellation event is visible | New matrix and existing video/client tests | PASS |
| Malformed provider response | Non-object worker data is rejected; no fake artifact is created | New matrix and provider client | PASS |
| Memory failure | Ingestion remains indexed but becomes partial; pipeline failure remains visible | `test_ingestion_application_cache.py`, `test_np10_ingestion.py` | PASS |
| Pipeline/adapter failure | Exception becomes failed child result with no artifact references | New matrix | PASS |
| Artifact rendering failure | Renderer failure is explicit and does not return a fake artifact | `test_reliability.py` | PASS |
| Retry | Transient optional stages retry within a bounded attempt budget | `test_ingestion_runtime.py`, video reliability tests | PASS |
| Retry after partial completion | Failed video scenes retry while successful scene work can be reused | `test_reliability.py`, `test_np09_pipelines.py` | PASS |
| Duplicate retry/admission | Cache claims and shared admission prevent duplicate expensive execution | `test_skill_runtime.py`, `test_shared_scheduler.py`, cache tests | PASS |
| Partial/degraded output | Partial output keeps artifact references and usage, is blocked from durable Case memory | New matrix and `release_gate.py` tests | PASS |
| Cache miss | Miss can claim work; quality-passed results are the only cacheable entries | `test_cache.py`, `test_skill_runtime.py` | PASS |
| Stale lease | Expired cache claims and scheduler leases can be reclaimed safely | `test_cache.py`, `test_shared_scheduler.py` | PASS for existing deterministic coverage |
| Process restart | Durable DAG/progress state can resume or replay after a new process | `test_reliability.py`, `test_shared_scheduler.py` | PASS for existing deterministic coverage; dedicated Phase 8 depth remains |

## New tests

`tests/component/test_failure_recovery_matrix.py` adds focused tests for:

1. Provider/pipeline exception behavior.
2. Partial status, artifact references, and usage accounting.
3. Timeout and parent cancellation.
4. Malformed external worker response.
5. HTTP error translation and provider cooldown classification.
6. Blocking failed, partial, pending, and degraded output from Case memory.
7. Application progress projection for partial status.

## RESULT

### Baseline

The existing failure/recovery baseline passed:

```text
51 passed in 13.35s
```

### Discovery and fix

The first new matrix run found this genuine defect:

```text
1 failed, 5 passed
partial result was emitted as skill.failed
```

The child runtime already returned `status="partial"` and preserved its
artifact and usage. However, the lifecycle event defaulted to
`skill.failed`, and the application progress contract did not accept
`partial`. An operator could therefore see a total failure even though a
recoverable/degraded result existed.

The smallest fix was applied in three projections:

- `SkillRuntime` emits `skill.partial` for a partial child result.
- The application maps `skill.partial` to frontend status `partial`.
- `ProgressStatus` and sanitized observability accept `partial`.

No retry policy, artifact creation policy, memory policy, or provider protocol
was redesigned.

### Final result

```text
58 passed in 13.57s
```

The affected regression after the lifecycle fix also passed:

```text
162 passed, 1 skipped, 1 warning in 17.40s
```

The skip is an existing optional test condition, and the warning is a
dependency/configuration warning. Neither indicates a test failure.

The final focused set includes the new matrix and the existing runtime,
scheduler, provider, cache, ingestion, video, renderer, reliability, and usage
tests.

### PASS

- Provider, HTTP, malformed-response, timeout, cancellation, memory, pipeline,
  and renderer failures have controlled outcomes.
- Partial results remain partial in child results, operator progress, and
  observability rather than being mislabeled as total failure.
- Failed/partial/degraded outputs cannot enter durable Case memory.
- Retry and duplicate prevention are bounded and backed by existing cache,
  admission, and scene-retry tests.
- Artifact references and usage are retained for partial results where they
  actually exist.
- Failure events do not include the injected provider response body or raw
  sensitive payload.

### FAIL

- None in the final deterministic Phase 7 evidence set.

### NOT YET IMPLEMENTED

- Real OpenAI/DeepSeek/MoneyPrinter HTTP failure tests with live provider
  request IDs, actual provider usage, and actual provider latency.
- Cross-process distributed retry storm testing under real Redis/control-plane
  failure.
- Automated billing reconciliation against real provider invoices.
- Fault injection during every possible artifact-write boundary.

### NEEDS DESIGN DECISION

- The generic child runtime still emits `CHILD_EXCEPTION` for an arbitrary
  adapter exception. Provider-specific adapters should classify provider errors
  at their own boundary; decide whether the runtime should additionally carry a
  stable provider failure class.
- Decide whether a partial child should cause a parent run to become partial,
  failed, or continue when the child is optional. The current application has
  pipeline-specific rules.
- Decide whether an expired/stale external provider job should be retried
  automatically or require operator reconciliation.

## Operator-visible behavior

The intended operator interpretation is:

| Status | Meaning |
|---|---|
| `failed` | The requested operation did not produce a releasable result. |
| `partial` | Some output exists, but one or more required/optional parts failed; do not treat it as complete. |
| `cancelled` | A user or parent run stopped the operation. |
| `pending`/`waiting` | Work is still in progress or waiting for a dependency/cache owner. |

The UI should show status, stage, error code, artifact references, and bounded
usage. It should not display raw provider payloads, prompts, raw memory, or
hidden reasoning.

## Live API clarification

The deterministic tests prove the local control flow now. They do not prove
that a real OpenAI/DeepSeek/Cognee/MoneyPrinter service returns the same error
shapes, latency, token counts, or request IDs.

The later live lane will require credentials and an explicit opt-in command.
It should run a sanitized fixture set against the real API, record provider
request IDs, input/output/reasoning tokens when available, estimated cost,
wall/provider latency, retries, cache status, and final artifact/quality status.
Credentials must come from environment variables or a secret manager and must
never be committed or written to reports.

## Hands-on command

Run the Phase 7 deterministic evidence set yourself:

```powershell
$runStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$base = Join-Path $env:TEMP "sudarshan-phase7-$runStamp"
.venv\Scripts\python.exe -m pytest `
  tests/component/test_failure_recovery_matrix.py `
  tests/component/test_skill_runtime.py `
  tests/component/test_shared_scheduler.py `
  tests/component/test_reliability.py `
  tests/component/test_provider_router.py `
  tests/component/test_provider_receipts.py `
  tests/component/test_cache.py `
  tests/component/test_distributed_cache.py `
  tests/component/test_ingestion_application_cache.py `
  tests/component/test_ingestion_runtime.py `
  tests/component/test_video_adapter.py `
  tests/pipeline/test_video_media.py `
  tests/pipeline/test_infographic_render.py `
  tests/component/test_usage_reconciliation.py `
  -q --basetemp=$base -p no:cacheprovider
```

## Next step

Keep the deterministic checkpoint separate from the live-provider benchmark.
After you personally rerun this command, commit the Phase 7 checkpoint. Then
continue to Phase 8 for duplicate execution, concurrency, and restart depth.
The real API lane should be introduced after the deterministic lifecycle and
observability gates are stable.
