# Phase 11 Branch Handoff and Completion Route

Last updated: 2026-09-18

This document is the handoff point for another developer or coding agent. It
describes what this branch proves, what it does not prove, and the safest route
to finish Phase 11 without repeating uncontrolled provider calls.

## Current checkpoint

The branch is safe to review as a testing checkpoint. No server is running and
no live provider request is active.

Latest offline regression after the PPT repair:

```text
729 passed, 8 skipped, 47 warnings in 55.86s
```

The warnings are dependency deprecations/configuration warnings. They are not
test failures.

The latest authorized live run was:

```text
run-g01-presentation-live-final-01
```

It reached routing, memory recall, prompt crafting, and all three PPT agent
stages. It failed at the renderer boundary because the model selected a custom
template without a validated template contract. No artifact was released.

This means:

- the real provider path is reachable;
- the FastAPI run lifecycle is observable;
- memory and pipeline routing work for this case;
- successful live artifact generation is still **not proven**;
- Phase 11 must remain open.

## What has changed in this branch

The changes are additive and covered by tests:

- `pipelines/common/text_generation.py` passes validated request constraints
  into CrewAI task inputs and contains the benchmark budget/compaction hooks;
- `pipelines/ppt/tasks.py` tells the model to use `native-default` unless a
  validated custom template contract is supplied;
- `pipelines/ppt/crew.py` normalizes an unsupported model-selected template to
  `native-default` when no validated custom contract exists;
- focused PPT, spend-control, artifact, and live-request tests were added or
  extended;
- Phase 11 runbook, token report, and progress documentation record the live
  measurements and failure honestly.

The fallback does not add custom-template support. It uses the already existing
native renderer and preserves the generated slide content.

## Evidence already available

| Area | Current evidence | Status |
|---|---|---|
| Ingestion | Edge-case matrix and provenance tests | PASS offline |
| Memory | User/case/task behavior and outage tests | PASS offline; live consistency remains open |
| Isolation | Cross-user/case/task evidence and artifact checks | PASS offline |
| Pipeline contracts | Request/output/validation matrices | PASS offline; live provider behavior remains open |
| Artifact correctness | PPTX/SVG/PNG/PDF/video integrity and manifests | PASS offline |
| Failure/recovery | Provider, timeout, cancellation, retry, partial paths | PASS deterministic; live failures remain open |
| Execution safety | Duplicate, concurrency, restart fixtures | PASS deterministic; live process restart remains open |
| Observability | Status, events, DAG, trajectory, redaction | PASS offline and observed in live run |
| Telemetry | Latency, usage, cache, cost fields | PASS structurally; live cost unavailable |
| Phase 11 live artifact | Real G01 presentation attempt | OPEN: no artifact yet |

The phase-specific documents are in this folder. Start with:

1. `phase-11-live-artifact-runbook.md`
2. `phase-11-token-optimization.md`
3. `phase-11-golden-and-holdout-cases.md`
4. `quality-engineering-progress.md`
5. `first-half-quality-audit.md`

## Latest live measurement

The final authorized run was admitted once:

| Measurement | Value |
|---|---:|
| HTTP admission | 202 |
| Admission latency | 71 ms |
| Terminal status | failed |
| Approximate wall time | 59,208 ms |
| Provider model | gpt-5.4 |
| Provider input tokens | 31,735 |
| Provider output tokens | 10,225 |
| Cache-read tokens | 21,760 |
| Provider latency | 29,915 ms |
| Artifact count | 0 |
| Cost | unavailable; do not invent a value |

The exact failure was:

```text
non-default presentation templates require a validated template_contract
```

The provider usage was recorded as provider-reported. The cost was not
available, so reports must keep cost as `null`/unavailable.

## How to verify the current branch offline

This command does not use the LLM key or Cognee Cloud:

```powershell
$env:COGNEE_BACKEND = "local"
$runStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$base = Join-Path $env:TEMP "sudarshan-offline-$runStamp"

.venv\Scripts\python.exe -m pytest -q `
  --basetemp=$base `
  -p no:cacheprovider
```

Expected current result: **729 passed, 8 skipped, 47 warnings**.

## Route to complete Phase 11

### Step 1 — Review and commit the offline checkpoint

Review the diff, especially the `PresentationFlow` fallback. Do not commit a
claim that Phase 11 is complete. A suitable checkpoint title is:

```text
fix(ppt): add safe native template fallback after live G01 failure
```

### Step 2 — Prepare one future live run

Only when someone explicitly authorizes another paid request:

1. Temporarily restore the provider key in the local `.env`.
2. Confirm `.env` is ignored by Git.
3. Start FastAPI using the repository startup route.
4. Submit exactly one sanitized G01 `presentation` request.
5. Poll `GET /runs/{run_id}` until `succeeded`, `partial`, or `failed`.
6. Inspect telemetry, observability, trajectory, and the artifact manifest.
7. Download the artifact only if an artifact ID is returned.
8. Open and visually inspect the PPTX.
9. Stop FastAPI.
10. Remove/disable the provider key again.

The exact request body and endpoint headers are in
`phase-11-live-artifact-runbook.md`. Do not paste keys into Postman, JSON
fixtures, Markdown, or chat.

### Step 3 — Acceptance criteria for a successful live G01 artifact

Do not mark Phase 11 complete unless all of these are true:

- run status is `succeeded`;
- a PPTX artifact exists and downloads successfully;
- the manifest identifies exactly two slides;
- the artifact has the correct User/Case/Task ownership;
- source/evidence references are present and belong to `golden-g01`;
- no foreign-case content appears;
- quality status is passed;
- the file opens successfully;
- the visual review finds no obvious clipping, placeholders, or unreadable text;
- queue, wall, and provider timing are recorded separately;
- provider usage is recorded without exposing raw prompts or memory;
- cost is measured or explicitly recorded as unavailable.

A `202 Accepted` response alone is not success. It only proves admission to the
run queue.

### Step 4 — Expand only after G01 succeeds

After the first artifact is proven:

1. run the remaining sanitized golden cases;
2. run the separate holdout cases without tuning prompts against them;
3. execute the other artifact pipelines one at a time;
4. collect repeated latency and usage measurements;
5. refine the Matplotlib charts;
6. perform one controlled external-AI comparison using identical fixtures;
7. write the final Phase 14 report.

Do not start external comparison before the internal golden and holdout sets
have stable evidence and artifact measurements.

## Credential and spend rules

- Keep the provider key disabled during offline tests.
- Never put credentials in Postman collections, fixtures, Markdown, or logs.
- Never rerun a failed paid request automatically.
- Do not describe an unavailable cost as zero.
- Keep raw memory and sensitive evidence out of telemetry and benchmark charts.
- Use `pass@k` for provider availability experiments and `pass^k` for
  deterministic safety/isolation requirements.

## Handoff classification

| Item | Classification |
|---|---|
| Offline regression | PASS |
| PPT native-template fallback | PASS offline |
| Real provider reachability | PASS |
| Real memory path | PASS for observed bounded G01 path |
| Real PPT artifact | NOT YET PROVEN |
| Live provider cost | NOT MEASURED |
| Custom PPT template support | NEEDS DESIGN DECISION |
| Phase 11 overall | OPEN |

The next agent should begin by reading this document and the live runbook, not
by starting the server or restoring credentials.
