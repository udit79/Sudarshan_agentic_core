# Agentic System Performance and Cost Measurement Report

Date: 2026-09-18  
Scope: Sudarshan quality-engineering benchmark work  
Status: Measurement design complete; live measurement is partial

## WHAT

This report defines the parameters that can be measured to evaluate an
agentic system as a product, not only as a collection of passing unit tests.
It separates correctness, quality, speed, reliability, resource use, and
cost.

An agentic run is a request that may include memory retrieval, planning,
multiple agent/model calls, tools, child pipelines, validation, retries, and
artifact rendering. One request can therefore have several timings and token
receipts.

## WHY

The system must answer five practical questions:

1. Did it produce the correct and permitted result?
2. How long did each part take?
3. How many model/tool resources did it consume?
4. Did retries, parallel branches, or cache behavior change the cost?
5. Is the result good enough to show or deliver to an operator?

A successful HTTP response alone cannot answer these questions.

## Measurement truth levels

Every benchmark field must be labelled with one of these states:

| State | Meaning | Example |
|---|---|---|
| Measured | Captured from the actual run | Cognee recall duration from an observability event |
| Provider-reported | Returned by the model/provider receipt | Actual input and output tokens |
| Estimated | Calculated before or without a provider receipt | Ingestion token estimate |
| Configured | A limit, not an observed result | `max_model_tokens=6000` |
| Unavailable | The system has not captured the value | Live provider latency in `run-g01-live-04` |

Never report an unavailable value as zero. Zero tokens or zero cost can mean
that the usage event was not recorded.

## Core timing parameters

### Request and harness level

| Parameter | Definition | How to calculate |
|---|---|---|
| `admission_ms` | API time to accept the request | response timestamp - request timestamp |
| `queue_ms` | Time waiting before worker execution | worker start - queue admission |
| `wall_ms` | Complete user-visible run duration | terminal timestamp - admission timestamp |
| `orchestration_ms` | Graph/harness processing time | graph start to graph finish, excluding provider time where available |
| `wait_ms` | Time spent waiting for input, approval, dependency, or cache | sum of waiting intervals |
| `retry_count` | Additional attempts after the first attempt | total attempts - 1 |
| `peak_concurrency` | Maximum simultaneous children or provider calls | maximum active count observed |

`wall_ms` is the main user-experience measure. `queue_ms` explains waiting
before work starts. `provider_ms` explains model/provider delay. These must not
be collapsed into one number when diagnosing a slow run.

### Stage level

Record separate durations for:

- ingestion upload and admission;
- parsing/extraction;
- OCR and vision, when applicable;
- chunking and source-map creation;
- embedding or memory projection;
- user/case/task memory recall;
- request understanding;
- prompt planning;
- each agent/model step;
- tool calls;
- quality validation;
- artifact rendering;
- artifact validation;
- manifest registration;
- final response publication.

The repository already exposes stage events and memory durations through the
observability path. Provider and artifact timings must be emitted by the
corresponding producer before they can be claimed as measured.

## Token and cost parameters

### Token fields

For every provider receipt, record:

- provider;
- model;
- input tokens;
- output tokens;
- reasoning tokens, when supplied;
- cache-read tokens;
- cache-write tokens;
- tool-call count;
- provider request ID;
- finish reason;
- attempt ID;
- latency;
- whether the value is measured or estimated.

The repository contracts already define these fields in
`pipelines/orchestrator/contracts.py` through `UsageRecord` and
`TelemetryUsage`.

### Cost fields

Use provider pricing configuration outside the test result itself:

```text
input_cost      = input_tokens      × input_price_per_token
output_cost     = output_tokens     × output_price_per_token
reasoning_cost  = reasoning_tokens  × reasoning_price_per_token
tool_cost       = tool_calls        × tool_price_per_call
provider_cost   = input_cost + output_cost + reasoning_cost + tool_cost
```

If pricing is unavailable, report `cost_status=unavailable`. Do not write
`0.0` and imply that the request was free.

Report both:

- `estimated_cost`: preflight or calculated estimate;
- `reconciled_cost`: provider-reported or billing-confirmed value.

Retries must be counted separately. A two-attempt run can consume roughly two
sets of provider resources even when only one artifact is finally returned.

### Credit protection rules

Before any live benchmark:

1. Run the deterministic regression suite.
2. Use a fresh `run_id` and one known case.
3. Set a hard token and wall-time budget.
4. Perform one warm-up only when explicitly approved.
5. Stop if usage receipts are missing.
6. Do not repeat failed live requests automatically while usage is unknown.
7. Keep API keys in `.env`; never include them in fixtures, reports, or logs.

The current `.env` contains an OpenAI configuration, and the text route is
configured through `CREWAI_MODEL`. The current telemetry gap means this
repository cannot yet prove the exact live credit consumption from the run
summary alone.

## Memory and Cognee parameters

Measure:

- recall request count;
- requested `top_k`;
- token budget;
- backend result count;
- accepted in-scope result count;
- rejected out-of-scope result count;
- retrieval duration;
- context-pack construction duration;
- context estimated tokens;
- cache hit/miss/wait;
- memory write count by User/Case/Task scope;
- memory write failures;
- memory projection duration;
- provenance completeness;
- cross-case and cross-user rejection count.

Raw memory text must not enter benchmark telemetry. Hashes, IDs, counts,
scope labels, and source references are sufficient for performance reporting.

## Pipeline and agent parameters

For each pipeline, report:

- request admission status;
- selected pipeline and route confidence, if available;
- number of agents/tasks;
- model calls per attempt;
- tool calls per attempt;
- sequential versus parallel execution;
- attempt count;
- validation failures;
- quality-gate failures;
- partial/degraded status;
- artifact count;
- final status;
- evidence coverage;
- unsupported-claim count;
- human approval state.

Useful derived measures:

```text
success_rate       = successful_runs / total_runs
hard_gate_rate     = runs passing every hard gate / total_runs
retry_rate         = runs_with_retry / total_runs
partial_rate       = partial_runs / total_runs
failure_rate       = failed_runs / total_runs
artifact_rate      = runs_with_artifact / total_runs
cost_per_success   = total_reconciled_cost / successful_runs
tokens_per_success = total_provider_tokens / successful_runs
```

For model quality, also record:

- evidence precision: cited evidence that actually supports the claim;
- evidence recall: required evidence represented in the artifact;
- unsupported claim rate;
- constraint adherence rate;
- artifact completeness rate;
- human quality score;
- holdout quality score.

## PPT/PPTX parameters

PPT generation needs both machine checks and human visual review.

### Automated PPT measurements

- artifact exists;
- file type is PPTX;
- file opens with the PPTX parser;
- exact slide count;
- slide IDs are unique;
- required text and sections exist;
- theme ID and renderer version;
- manifest ownership: User/Case/Task;
- evidence reference count and validity;
- file size;
- SHA-256 checksum;
- render duration;
- structural validation duration;
- render retry count;
- placeholder count;
- overflow or missing-content warnings, where detectable;
- duplicate artifact admission count.

### Human PPT measurements

Score separately on a fixed rubric:

- readability;
- typography;
- visual hierarchy;
- layout balance;
- consistency;
- factual correctness;
- evidence visibility;
- theme adherence;
- usefulness to the operator;
- absence of distracting or misleading visual elements.

An editable, structurally valid PPTX is not automatically readable or useful.

## Ingestion performance parameters

For each source type and size band record:

- upload bytes;
- content characters;
- media type;
- parser duration;
- OCR/vision duration and calls;
- chunk count;
- evidence count;
- relationship count;
- source-map completeness;
- memory projection duration;
- cache hit/miss;
- estimated and actual ingestion tokens;
- total wall time;
- partial/failure reason.

Compare empty, low-context, normal, boundary-size, large, malformed, and
unsupported inputs separately. A large file that completes safely is different
from a large file that silently truncates.

## Reliability and concurrency parameters

Measure:

- duplicate admission rate;
- duplicate artifact rate;
- retry amplification factor;
- stale-lease recovery time;
- restart recovery time;
- cancellation acknowledgement time;
- provider timeout rate;
- late provider response handling;
- child failure propagation;
- parent partial/failure correctness;
- usage double-count rate;
- concurrent branch isolation failures;
- cache stampede/wait count.

The important question is not only whether an error is caught. It is whether
the final status, usage, memory writes, artifacts, and operator message all
describe the same outcome.

## Pass@k and pass^k

Use the two measures for different purposes:

| Measure | Meaning | Best use |
|---|---|---|
| `pass@k` | At least one of k attempts succeeds | Provider availability or exploratory model quality |
| `pass^k` | All k attempts succeed | Isolation, contracts, determinism, duplicate safety |

Do not use `pass@k` to claim reliable production behavior. For security,
ownership, artifact correctness, and status consistency, use `pass^k`.

## Percentiles and comparison

For each metric, store every sanitized run value and calculate:

- minimum;
- median/p50;
- p90;
- p95;
- maximum;
- standard deviation when the sample is large enough.

Never compare only averages. Agentic systems often have retries and long-tail
provider delays, so p95 is more useful for an operator-facing promise.

Compare warm and cold runs separately, and compare serial and permitted-
parallel runs separately.

## Sanitized benchmark record

The benchmark record should remain compatible with the existing guide:

```json
{
  "case_id": "G01",
  "pipeline": "executive_summary",
  "run_id": "run-example",
  "status": "failed",
  "quality_status": "failed",
  "truth_level": "measured_with_missing_provider_usage",
  "wall_ms": 0,
  "queue_ms": 0,
  "orchestration_ms": 0,
  "provider_ms": null,
  "memory_ms": 0,
  "artifact_ms": null,
  "attempts": 2,
  "tokens": {
    "input": null,
    "output": null,
    "reasoning": null,
    "estimated": null,
    "reconciled": null
  },
  "cost": {
    "estimated": null,
    "reconciled": null,
    "status": "unavailable"
  },
  "cache": {"hits": 0, "misses": 0, "waits": 0},
  "artifact_count": 0,
  "evidence_reference_count": null,
  "issues": ["quality_gate_rejected", "provider_usage_not_recorded"]
}
```

The zeros above are placeholders in a schema example only. A real benchmark
record must use `null` or an explicit unavailable status when a value was not
measured.

## Current live evidence: G01

Run: `run-g01-live-04`  
Pipeline: `executive_summary`  
Final status: `failed`  
Attempts: `2`  
Artifacts: `0`

Observed:

- User/Case memory recall completed;
- task-oriented memory recall completed;
- real agent stages executed twice;
- quality gate rejected both drafts;
- no rejected artifact was released;
- memory recall events contained durations of approximately 8–9 seconds;
- the run duration was approximately 123 seconds from its recorded lifecycle
  timestamps;
- aggregate provider tokens, provider latency, and cost were not recorded;
- zero telemetry values must therefore be treated as missing measurements, not
  as zero usage.

This is a useful failure record because it proves the safety gate worked while
also exposing that provider usage accounting is not yet complete.

## Instrumentation checkpoint — 2026-09-18

The missing measurement boundary was fixed without making another live model
call. CrewAI's returned `CrewOutput.token_usage` is now retained at the common
text-pipeline boundary and projected through the existing `PipelineResponse`
metadata and progress/observability event. Retry attempts receive distinct
usage IDs; the pipeline-level aggregate receives one stable usage ID, so the
same aggregate is not counted twice by the existing telemetry deduplicator.

The recorded fields are limited to provider/model labels, input/output/
reasoning/cache counters, attempt IDs, and CrewAI wall time. The timing field
is labelled `latency_scope=crew_wall_time`; it must not be described as
provider-only latency. Cost is explicitly `estimated_cost=null` with
`cost_status=unavailable` until a configured pricing table or provider billing
receipt exists. Missing provider counters are marked
`usage_status=unavailable` and are never interpreted as zero-cost execution.

Offline proof:

- usage normalization and retry aggregation: 4 focused tests passed;
- affected telemetry/pipeline regression: 26 passed;
- pipeline regression: 134 passed;
- full local regression: 685 passed, 8 skipped, 32 warnings.

This proves the instrumentation path and its safety properties. It does not
yet prove that the configured live provider returns non-zero usage counters;
one explicitly approved, budgeted live run is still required for that.

## Current readiness

### Ready locally

- deterministic full regression;
- typed usage and telemetry contracts;
- safe observability events;
- memory timing events;
- artifact IDs and checksums;
- PPT structural validation;
- ingestion budget estimates;
- retry, cache, isolation, and concurrency test doubles;
- sanitized golden and holdout catalogue.

### Requires live measurement

- actual OpenAI input/output/reasoning tokens;
- reconciled OpenAI cost;
- actual provider latency;
- real PPT generation and render time;
- real cache hit rate;
- live model quality across golden cases;
- deployed frontend-to-backend timings.

## Recommended next order

1. Keep the current Phase 11 checkpoint; do not run an unbudgeted live call.
2. Configure or verify a pricing source before claiming cost numbers.
3. Run one explicitly approved, token-budgeted G01 request and inspect its
   sanitized usage projection.
4. Capture the sanitized benchmark record with wall, memory, orchestration,
   and provider-usage truth levels kept separate.
5. Run the PPT path once with an exact slide-count constraint.
6. Review the PPT structurally and visually.
7. Run the remaining golden cases and calculate p50/p95 only after the values
   are genuinely recorded.

## Source files

- `docs/pipeline-benchmarking.md`
- `docs/pipeline-observability.md`
- `pipelines/orchestrator/contracts.py`
- `pipelines/orchestrator/observability.py`
- `pipelines/common/usage_capture.py`
- `pipelines/common/text_generation.py`
- `pipelines/advisory/crew.py`
- `tests/component/test_agentic_usage_capture.py`
- `tests/component/test_observability_telemetry_matrix.py`
- `tests/integration/test_openai_budgeted.py`
- `docs/all test phases/phase-11-golden-and-holdout-cases.md`
