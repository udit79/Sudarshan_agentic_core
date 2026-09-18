# Benchmark Results Checkpoint

Date: 2026-09-18  
Scope: completed local tests, the recorded live G01 run, and the offline
harness boundary benchmark  
Status: reporting layer complete; live quality and human review remain open

## WHAT

This checkpoint turns existing test evidence into a reusable benchmark
dataset and separate Matplotlib charts. It is a reporting layer, not a new
runtime path.

## WHY

Test counts, system timing, provider usage, and artifact quality answer
different questions. Combining them into one score would hide important
limits. The dataset therefore keeps objective automated results, live-run
measurements, and human evaluation in separate fields.

## WHERE

- Source dataset: `benchmark-results.json`
- Spreadsheet-friendly export: `benchmark-results.csv`
- Chart-to-record mapping: `chart-manifest.json`
- Generator: `scripts/build_benchmark_results.py`
- Validation: `tests/component/test_benchmark_results_report.py`

The source values are linked to the existing phase reports and test commands;
no raw prompts, memory text, credentials, or hidden reasoning are copied into
the dataset.

## INPUT

The dataset contains eight records:

- ingestion matrix: 17 passed, 1 skipped, 0 failed, 620 ms;
- memory matrix: 53 passed, 0 skipped, 0 failed, 390 ms;
- artifact/pipeline focused checks: 131 passed, 0 skipped, 0 failed, 6,300 ms;
- Phase 11 focused checks: 26 passed, 0 skipped, 0 failed, 20,420 ms;
- latest full local regression: 703 passed, 8 skipped, 0 failed, 58,100 ms;
- offline G01 replay: 1 objective grounding check passed;
- Phase 11 catalogue readiness: 3 checks passed in 60 ms; all 10 golden and
  all 3 holdout cases are present, disjoint, sanitized, and contract-defined;
- live G01 ingestion recovered successfully with HTTP 201, one evidence item,
  one chunk, complete source mapping, and `memory_persisted=true`;
- offline Harness boundary: 26 MCP tools, 7 artifact-profile tools, 8
  renderers, 0 provider calls, 0 model tokens, and 0 network calls;
- recorded live G01 usage run: one failed quality-gated run.

The suite timings are test-process durations. They are not presented as
end-user API latency.

## OUTPUT

The generated charts are intentionally separate:

1. `objective-test-outcomes.png` — passed/failed/skipped automated checks.
2. `offline-test-suite-duration.png` — measured local suite runtimes.
3. `live-g01-token-usage.png` — provider-reported input/output/reasoning
   tokens for the one recorded live run.
4. `live-g01-timing.png` — admission, memory-recall, and CrewAI wall timing
   observations. The y-axis is logarithmic so the 114 ms admission value is
   visible beside the longer stages.
5. `offline-harness-capabilities.png` — offline harness capability counts.

Every chart lists its source record IDs and data columns in
`chart-manifest.json`. The CSV is an export, not a second source of truth.

## Objective versus human evaluation

Objective results currently include test outcomes, structural/contract
assertions, recorded run status, token counters, and observed timings.

Human evaluation is explicitly `not_run` for every record. Therefore this
checkpoint does not claim readability, visual hierarchy, usefulness,
truthfulness beyond the automated G01 replay assertions, or PPT quality from
automation alone.

## Important actual live result

The recorded live G01 run admitted in 114 ms and reported 29,430 input tokens,
5,900 output tokens, and 0 reasoning tokens, for 35,330 provider-reported
tokens across two attempts. CrewAI wall time was 69,177 ms. The quality gate
failed the output for unsupported/ungrounded content and released zero
artifacts. Provider-only latency and reconciled cost were unavailable.

This is a useful safety result: the system rejected the bad result instead of
publishing it. It is not a successful product-quality result.

### Current controlled live attempt

After the successful ingestion retry, one G01 executive-summary request was
admitted with HTTP 202 and stopped after 4,061 ms. The configured GPT-5.4
route rejected the provider request because the application supplied
`max_tokens` while the model requires `max_completion_tokens`. The spend guard
then denied retry admission. No artifact was released, no provider request ID
was returned, and telemetry recorded zero tokens. This demonstrates safe retry
containment, but it does not prove that an external provider billed zero
tokens; the provider receipt was unavailable.

The exact application boundary is
`pipelines/common/text_generation.py`, where the budgeted LLM is constructed
with `max_tokens`. This is a genuine provider-compatibility defect that must be
fixed or explicitly configured around before further live artifact runs.

### Compatibility fix checkpoint — 2026-09-18

The defect is now fixed narrowly at that same boundary. For GPT-5-family
models, the application keeps `max_tokens` empty and injects only
`max_completion_tokens` into CrewAI's provider request parameters. Other model
families keep the legacy `max_tokens` behaviour.

The tests inspect the prepared request dictionary without making a network
call. Results: **14 focused provider/spend tests passed**, **107 affected
pipeline tests passed**, and the full offline regression passed **705 tests,
8 skipped, 32 warnings**. No API key was needed for these checks. A new live
run is still required before calling G01 generation successful.

### Budget-cap experiments — 2026-09-18

Two additional single-run G01 experiments were recorded. A total budget of
`3000` created a 600-token per-call cap and failed after 33,247 ms when the
structured response reached that cap. A total budget of `6000` created a
1,200-token per-call cap; the first two analysis stages completed, but the
final structured response still reached the cap and failed after 59,266 ms.

Both runs released no artifact and did not retry. The common text-generation
boundary now accepts an additive `provider_output_token_budget` override so a
pipeline can declare its contract-specific completion requirement without
changing the existing default allocation. This override is covered offline;
no further paid run was started with it.

### Final controlled G01 budget run — 2026-09-18

The authorized run used `provider_token_budget=12000` and
`provider_output_token_budget=2400`. GPT-5.4 accepted the corrected request,
and all four executive-summary stages reached completion events. However, the
provider-reported aggregate was **54,165 input tokens + 11,919 output tokens =
66,084 observed tokens**, including 13,056 cached input tokens. Wall time was
**55,399 ms**.

The run failed safely when the spend guard observed usage above the configured
budget. No artifact was released and no retry was attempted. Currency cost is
still unavailable. This result proves that the current multi-agent route is
not yet cost-bounded; it does not prove the artifact pipeline is production
ready.

### Corrected live rerun result — 2026-09-18

Run `phase11-g01-live-fixed-20260918-143649` reached the real GPT-5.4
provider with the corrected `max_completion_tokens` parameter. The provider
reported 1,145 prompt tokens and 240 completion tokens, for 1,385 total
tokens. Application/CrewAI wall time was 23,559 ms.

The run failed safely because the structured response hit the 240-token
per-call cap and could not be parsed. No artifact was released, and the
existing spend guard denied a retry. This is a new budget-allocation finding,
not a recurrence of the previous `max_tokens` incompatibility. The recorded
cost remains unavailable.

## TEST

Run the reporting validation:

```powershell
.venv\Scripts\python.exe -m pytest -q tests\component\test_benchmark_results_report.py -p no:cacheprovider
```

Regenerate the CSV, manifest, and charts:

```powershell
.venv\Scripts\python.exe scripts\build_benchmark_results.py
```

The current validation result is **3 passed**. The generator makes no API,
provider, database, or Cognee calls.

The Phase 11 catalogue validation result is **3 passed in 0.06 seconds**. It
proves offline case-set readiness, not live model execution.

## RESULT

The measurement/reporting layer is ready for the SIH presentation as an
honest checkpoint. It can show what is already measured and clearly labels
what is not.

Still unavailable or not yet measured:

- reconciled currency cost;
- provider-only latency;
- repeated live p50/p95 values;
- successful live golden-case artifact quality;
- human PPT readability/visual-quality scores;
- holdout quality and external-provider comparison;
- frontend end-to-end timing.

Those values must come from future controlled runs or human review. They must
not be filled with estimates merely to make the charts look complete.
