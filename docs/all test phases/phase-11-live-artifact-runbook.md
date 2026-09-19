# Phase 11 — One controlled live artifact run

Status: **prepared; do not mark Phase 11 complete until a real artifact is opened and checked**.

## WHAT

Run one sanitized G01 case through the existing `presentation` pipeline and
retrieve the resulting PPTX through the FastAPI artifact route.

## WHY

The earlier live executive-summary runs proved that the real provider and
telemetry path are reachable, but they ended before an artifact was released.
The presentation pipeline is the smallest currently registered route that both
has a deterministic PPTX renderer and a quality gate without an interactive
human-approval pause.

This is a **one-run diagnostic ceiling**, not a production token profile. The
large ceiling is intentional because the previous live receipt showed that the
original application budget was not a provider-spend ceiling. The observed
receipt, not the ceiling, is what belongs in the benchmark report.

## WHERE

- Sanitized request fixture: `tests/fixtures/phase11_g01_presentation_live_request.json`
- Offline contract test: `tests/component/test_phase11_live_presentation_request.py`
- HTTP admission: `POST /runs`
- Status: `GET /runs/{run_id}`
- Safe telemetry: `GET /runs/{run_id}/telemetry`
- Operator observability: `GET /runs/{run_id}/observability`
- Artifact manifest: `GET /artifacts/{run_id}/presentation/manifest`
- Artifact download: `GET /artifacts/{artifact_id}/download`
- PPTX renderer: `pipelines/ppt/renderer.py`

## INPUT

Use the already-ingested, sanitized G01 source under:

- `user_id`: `live-test-operator`
- `case_id`: `golden-g01`
- `task_id`: `task-g01-presentation-live-01`

The request must select exactly one pipeline: `presentation`. Do not add
`executive_summary`, `infographic`, `video`, or a second pipeline to this run.

## OFFLINE GATE

Run this before restoring the key:

```powershell
$runStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$base = Join-Path $env:TEMP "sudarshan-phase11-live-gate-$runStamp"
.venv\Scripts\python.exe -m pytest -q `
  tests/component/test_phase11_live_presentation_request.py `
  tests/component/test_provider_budget_profiles.py `
  tests/component/test_provider_spend_guard.py `
  tests/component/test_agentic_usage_capture.py `
  --basetemp=$base -p no:cacheprovider
```

Expected result at this checkpoint: **33 passed**. This proves the request is
sanitized, single-pipeline, two-slide constrained, and compaction-enabled. It
does not prove provider quality or artifact creation.

## KEY GATE

Only after the offline gate passes should the operator temporarily restore the
LLM key in the local `.env`. Do not paste the key into Postman, this document,
the request body, or chat. Keep the server terminal visible so it can be
stopped immediately with `Ctrl+C`.

The one-run diagnostic ceiling is:

| Field | Value | Meaning |
|---|---:|---|
| `provider_token_budget` | `100000` | hard application ceiling for this one run |
| `provider_input_token_budget` | `5000` | bounded dynamic input per declared provider call |
| `provider_output_token_budget` | `3000` | enough room for typed slide JSON per call |
| `provider_call_count` | `12` | conservative reservation count for the staged PPT route |
| `provider_budget_preflight` | `true` | reject before execution if the declared reservation cannot fit |
| `provider_context_compaction` | `true` | remove verbose intermediate raw task text where safe |
| `max_attempts` | existing explicit budget mode | no automatic provider retry after the first attempt |

The reservation is an accounting control, not a guarantee of provider billing.
The server must still return a safe failure if the provider receipt exceeds the
ceiling. Do not rerun automatically.

## POSTMAN BODY

Create one `POST` request to `{{fastapi_base}}/runs` with these headers:

```text
Content-Type: application/json
X-Operator-Id: live-test-operator
X-Case-Id: golden-g01
X-Classification-Level: RESTRICTED
```

Use this JSON body:

```json
{
  "query": "Create a concise two-slide NTRO briefing from the verified G01 findings. Slide one must summarize the verified observations. Slide two must list the explicit unknowns and follow-up review point. Use only permitted case evidence, preserve source references, and do not invent facts, policy, owners, or dates.",
  "user_id": "live-test-operator",
  "case_id": "golden-g01",
  "task_id": "task-g01-presentation-live-01",
  "classification_level": "RESTRICTED",
  "distribution": "Authorized NTRO personnel",
  "top_k": 6,
  "token_budget": 1500,
  "requested_pipelines": ["presentation"],
  "constraints": {
    "slide_count": 2,
    "page_count": 2,
    "theme_id": "ntro-briefing"
  },
  "metadata": {
    "run_id": "run-g01-presentation-live-01",
    "pipeline": "presentation",
    "provider_budget_preflight": true,
    "provider_token_budget": 100000,
    "provider_input_token_budget": 5000,
    "provider_output_token_budget": 3000,
    "provider_call_count": 12,
    "provider_context_compaction": true,
    "benchmark_case": "G01",
    "live_attempt_policy": "one controlled attempt"
  }
}
```

The HTTP response should be `202 Accepted`. Record the returned `run_id` and
admission time. A `202` means “queued,” not “artifact created.”

## OBSERVE THE RUN

Poll `GET {{fastapi_base}}/runs/run-g01-presentation-live-01` until the status
is `succeeded`, `partial`, or `failed`. Then retrieve all of these using the
same operator/case headers:

```text
GET /runs/run-g01-presentation-live-01
GET /runs/run-g01-presentation-live-01/telemetry
GET /runs/run-g01-presentation-live-01/observability
GET /runs/run-g01-presentation-live-01/trajectory
```

Do not treat a successful status alone as proof of quality. Confirm:

1. `status == "succeeded"`.
2. `quality_status == "passed"` or the equivalent presentation quality pass.
3. `artifact_count == 1`.
4. The response contains a presentation artifact path or reference.
5. Usage contains input/output/reasoning counters and latency.
6. The case/user/task ownership is G01 and `task-g01-presentation-live-01`.
7. The telemetry contains no raw prompt or memory text.

## OPEN THE ARTIFACT

First request the manifest:

```text
GET {{fastapi_base}}/artifacts/run-g01-presentation-live-01/presentation/manifest
```

Use the returned `artifact_id` in:

```text
GET {{fastapi_base}}/artifacts/{artifact_id}/download
```

Save the response as `.pptx` and open it in PowerPoint or LibreOffice. The
manifest checksum and file type must match the downloaded file. The two-slide
constraint must be visible in the opened deck.

## RESULT CLASSIFICATION

### PASS

The provider returns a valid structured presentation, the quality gate passes,
one PPTX is released, the manifest is retrievable, and the opened deck has two
readable slides containing only G01 evidence and explicit unknowns.

### FAIL

The system claims success but the artifact is missing, corrupt, wrong-sized,
wrongly scoped, unsupported by the evidence, or the usage projection is
inconsistent with the provider receipt.

### NOT YET IMPLEMENTED

The route does not expose enough information to retrieve or verify a live
artifact, or a required timing/usage field is absent. Do not replace the value
with an estimate.

### NEEDS DESIGN DECISION

The provider exceeds the one-run diagnostic ceiling, the output is technically
valid but visually poor, or the PPTX needs a human acceptance threshold that
the current automated gate does not define.

## AFTER THIS RUN

Keep the key enabled only for the explicitly planned run. Remove it again after
the run and before continuing with more cases. Save only the sanitized run ID,
status, timing, usage counters, artifact manifest metadata, and human review
score in the benchmark report. Never commit the source file, `.env`, key, raw
memory, or full provider prompt/output.

Infographics are intentionally deferred until this presentation artifact path
has been verified. That keeps the first live proof diagnosable.

### Post-fix provider attempt — unvalidated template selection

Run `run-g01-presentation-live-postfix-01` passed memory recall, prompt
crafting, and all three PPT agent stages. It was admitted with HTTP 202 in
**203 ms**. The provider receipt reported **31,525 input tokens** and
**10,515 output tokens** (**42,040 total**) with **32,406 ms** provider-stage
latency. No provider retry was attempted.

The run still failed before artifact publication because the generated typed
output selected a non-default template while no validated template contract
was supplied:

`non-default presentation templates require a validated template_contract`

The PPT output task now explicitly requires `native-default` unless a
validated template contract is supplied. Follow-up offline tests passed
**40**. The server was stopped immediately after the run; no further paid run
was started.

## LIVE ATTEMPT LOG

### Attempt 1 — network permission failure

Run `run-g01-presentation-live-01` was admitted with HTTP 202 in **70 ms**.
The server process could not open the outbound Cognee socket and returned
`WinError 10013`. Memory recall failed before provider generation. Recorded
provider tokens were **0**, no artifact was created, and 12 sanitized
observability/trajectory events were captured. This was classified as a
local runtime/network-permission failure, not a model-quality result.

### Recovery attempt — missing PPT constraint input

After restarting FastAPI with network access, memory recall and prompt
crafting succeeded. Run `run-g01-presentation-live-recovery-01` was admitted
with HTTP 202 in **172 ms**. The existing staged PPT task template required
the `{constraints}` variable, but the common text-generation boundary did not
provide it. The flow therefore failed before provider generation; recorded
provider tokens were **0**, no artifact was created, and 26 sanitized
observability/trajectory events were captured.

The product defect was fixed by passing the already-validated constraints into
the common CrewAI input boundary for both normal and budgeted requests. The
focused regression passed **34 tests**, and the full offline regression passed
**728 passed, 8 skipped, 47 warnings**. A post-fix live retry was then started;
its result is recorded below.

### Final authorized live attempt — template contract still rejected

Run `run-g01-presentation-live-final-01` was admitted once with HTTP **202**
in **71 ms**. Routing, memory recall, prompt crafting, and all three PPT
agent stages completed. The terminal state was **failed** after approximately
**59,208 ms** wall time, with no artifact and no quality report released.

The provider receipt reported **31,735 input tokens**, **10,225 output
tokens**, **21,760 cache-read tokens**, and **29,915 ms** provider latency.
The combined input/output total was **41,960 tokens**. The provider reported
usage directly; cost was unavailable, so no currency value is claimed.

The failure was the same renderer contract:
`non-default presentation templates require a validated template_contract`.
The prompt instruction to prefer `native-default` was not sufficient to
guarantee model output compliance. This is now classified as a product
boundary/design issue, not a connectivity, memory, timeout, or budget failure.
The server was stopped immediately afterward and no automatic retry occurred.

### Offline repair after the final live attempt

The product boundary was tightened additively in `PresentationFlow`: when no
validated custom template contract exists, an unsupported model-selected
template is normalized to the existing `native-default` renderer before the
quality gate and persistence steps. Slide content is preserved. Custom
template support is not claimed or invented.

The new fallback regression passed **6 tests**, the affected PPT/artifact
regression passed **32 tests**, and the post-repair full offline regression
passed **729 tests, with 8 skipped and 47 warnings**. This repair has not yet
been re-run against a
live provider because the one authorized paid attempt was already consumed.
Phase 11 therefore remains open pending a future explicitly authorized live
artifact run.
