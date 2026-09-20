# Phase 11 Branch Handoff and Completion Route

Last updated: 2026-09-20

This document is the handoff point for another developer or coding agent. It
describes what this branch proves, what it does not prove, and the safest route
to finish Phase 11 without repeating uncontrolled provider calls.

## Current checkpoint

The branch is safe to review as a testing checkpoint. No server is running and
no live provider request is active.

Latest offline regression after the PPT repair, offline artifact preview, and
redacted memory health-probe safety gate:

```text
746 passed, 8 skipped, 62 warnings in 52.26s
```

The warnings are dependency deprecations/configuration warnings. They are not
test failures.

The latest provider-accepted live run was:

```text
run-g01-presentation-live-main-20260920-02
```

It reached routing, memory recall, prompt crafting, and all three PPT agent
stages. It failed at the renderer-to-state hand-off because the runtime
rejected an undeclared `artifact_data` field. That defect was fixed by using
the declared `TaskState.artifact` field. The next retry
(`run-g01-presentation-live-main-20260920-03`) reached memory recall but Cognee
timed out before provider execution. No live artifact has been released.

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
- `scripts/run_phase11_offline_artifact.py` provides an explicitly labelled,
  no-provider artifact proof from a local source file and operator prompt;
  `tests/component/test_phase11_offline_artifact.py` covers its manifest,
  provenance, scope, and visible-text checks.
- `SudarshanApplication._memory_health_probe()` provides an opt-in bounded
  memory reachability check for the live-run operator gate; it returns no raw
  memory and reports `degraded` health when the check is unreachable.
- `SudarshanApplication` now binds selected ingestion evidence IDs into the
  existing scoped `ContextPack`, preserving source-task provenance and rejecting
  foreign User/Case evidence. The focused binding/API/receipt tests pass **24**.
- The controlled live run reached provider-backed PPT rendering with explicit
  ingestion evidence, then exposed a `PPTIssue.code` versus `issue_code`
  validation-listener defect. The additive fix is covered by the focused PPT
  regression, and the full offline suite now passes **744** tests.
- The grounding stage now reuses a non-empty admission-bound explicit evidence
  pack instead of replacing it with a fresh semantic recall. This closes the
  live-observed gap where `evidence_refs` were authorized but the provider saw
  an empty grounding context. Two focused tests cover the selection boundary;
  the full offline suite now passes **746** tests.

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
| Phase 11 live artifact | Real G01 presentation attempt | OPEN: failed draft produced; no approved artifact released |

The phase-specific documents are in this folder. Start with:

1. `phase-11-live-artifact-runbook.md`
2. `phase-11-token-optimization.md`
3. `phase-11-golden-and-holdout-cases.md`
4. `quality-engineering-progress.md`
5. `first-half-quality-audit.md`
6. `phase-11-evidence-binding.md`

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

### Latest controlled rerun after the validation-listener fix

Run `run-g01-presentation-live-20260920-06` was admitted with HTTP **202**
in **112 ms**. The sanitized G01 source ingested successfully, Cognee
projection succeeded, and the explicit ingestion evidence reference was sent
into the presentation request. The provider completed the presentation
stages, the PPTX renderer produced a real two-slide file, and the repaired
validation listener completed without the previous `PPTIssue.issue_code`
crash.

The run still ended as **failed**, because the quality gate correctly rejected
the draft. Slide 2 had six bullets against the five-bullet density budget, and
the generated `[E2]`/`[E3]` evidence labels were unresolved inside the deck.
The system therefore did not release a quality-approved artifact. A failed
draft file exists for forensic inspection at:

```text
artifacts/presentations/task-g01-recovery-01-brief_20260920T115257Z.pptx
```

The file is a valid 2-slide PPTX (36,527 bytes), but it is not a deliverable.
The generated text remained conservative and did not invent G01 facts; the
traceability and density failures are product-quality failures that must be
fixed before claiming a successful live artifact.

| Measurement | Value |
|---|---:|
| HTTP admission | 202 |
| Admission latency | 112 ms |
| Terminal status | failed |
| Safe event count | 28 |
| Provider model | gpt-5.4 |
| Provider input tokens | 32,430 |
| Provider output tokens | 9,145 |
| Cache-read tokens | 21,760 |
| Provider latency | 26,515 ms |
| Provider attempts | 1 |
| Released artifact count | 0 |
| Cost | unavailable; do not invent a value |

The terminal summary reported internal artifact records while public telemetry
reported zero released artifacts. For reporting, the authoritative release
result is zero because the run failed and no manifest-backed deliverable was
released.

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

Expected current result: **746 passed, 8 skipped, 62 warnings**.

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
| Ingestion-to-resolver evidence binding | PASS offline and observed in live request |
| Live evidence binding through provider/PPT render | PASS for request hand-off; release-quality traceability still open |
| Custom PPT template support | NEEDS DESIGN DECISION |
| Phase 11 overall | OPEN |

The next agent should begin by reading this document and the live runbook, not
by starting the server or restoring credentials.
