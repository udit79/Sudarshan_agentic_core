# Phase 11 — Sanitized golden and holdout case set

## WHAT

This is a small, realistic, non-classified evaluation set for the Sudarshan
pipeline. A golden case has an expected evidence and artifact outcome. A
holdout case is kept separate and is not used to tune prompts, routing, or
quality thresholds.

The source text below is fictional and uses no real NTRO information.

## WHY

A single demo cannot show whether a pipeline remains grounded, scoped,
repeatable, and useful across different request shapes. These cases let us
compare providers and pipeline versions using the same inputs and constraints.

## WHERE

- Pipeline request boundary: `api/server.py` and
  `integrations/deepseek_harness/application.py`
- Evidence and memory scope: `memory/` and the ingestion/evidence modules
- Artifact boundary: `api/artifacts.py`
- Pipeline contract reference: `docs/all test phases/pipeline-contract-testing-report.md`
- Benchmark rules: `docs/pipeline-benchmarking.md`
- This catalogue: this document

## Evaluation rules

Every case uses a fresh `user_id`, `case_id`, `task_id`, and `run_id` during
execution. Expected evidence means the source document IDs, sections, dates,
or quoted facts that a valid answer must use. It does not mean the model should
repeat the entire source text.

Hard gates for every case:

- no unsupported factual claims;
- evidence stays inside the case scope;
- status is truthful;
- artifact type and manifest are correct;
- no raw memory or credentials appear in telemetry;
- partial or blocked output is not presented as complete.

## Golden cases

| ID | Source information | Operator request | Expected evidence | Pipeline | Constraints | Expected artifact properties | Failure conditions |
|---|---|---|---|---|---|---|---|
| G01 normal-report | One fictional two-page field report: date, location code `SITE-ALPHA`, three verified observations, and two explicit unknowns | “Summarize the verified findings and list the unknowns.” | All three observations plus the two unknowns, linked to source sections | `executive_summary` | 250–400 words; preserve uncertainty; no new facts | Readable text/Markdown; every finding has a source reference; no placeholders | Any invented location/person/date, omitted unknown, or missing provenance |
| G02 incident-report | Fictional incident timeline with detection, containment, impact estimate, and recovery timestamps | “Create an incident briefing for the duty operator.” | Timeline events, impact estimate, containment action, and recovery status | `executive_summary` | Chronological order; distinguish confirmed from estimated | Structured briefing with headings and timestamps; source-linked claims | Timeline reordered incorrectly, estimate presented as fact, or recovery overstated |
| G03 advisory | Verified observations plus three fictional response options with stated trade-offs | “Recommend the safest next action and explain alternatives.” | Observation IDs and option trade-offs; recommendation must be labelled | `advisory` | Evidence-linked recommendation; human approval remains required where configured | Markdown advisory; recommendation, rationale, risks, and approval state | Unsupported recommendation, missing trade-off, or automatic external publication |
| G04 research-document | Fictional research note containing definitions, method, limitations, and a short comparison table | “Produce a concise research brief for a technical reviewer.” | Definitions, comparison values, method, and limitations | `executive_summary` | Preserve limitations; do not upgrade notes into certainty | Text artifact with sections and table preserved or safely represented | Method/limitations omitted, table values changed, or unsupported conclusion |
| G05 multi-document | Three fictional documents: `DOC-A` baseline, `DOC-B` follow-up, `DOC-C` glossary; each has distinct facts | “Combine these documents into one case brief.” | Facts must retain their source document IDs; glossary definitions must not become new evidence | `executive_summary` + `presentation` | Cross-document synthesis; case scope fixed to one case | Summary plus PPTX; manifests reference only these three documents | Facts attributed to the wrong document, foreign-case content, or missing manifest links |
| G06 stale-updated | `DOC-OLD` reports a fictional deadline of 10 June; `DOC-UPDATE` dated later changes it to 18 June and explicitly supersedes old value | “Report the current deadline and explain the change.” | New deadline, update date, and supersession relationship; old value shown only as history | `executive_summary` | Latest active evidence wins; preserve stale provenance | Text artifact states current value and historical replacement | Old value presented as current, update ignored, or supersession invented |
| G07 low-context | One sentence: “A review may be needed.” No date, source, subject, or evidence | “Create a complete operational briefing.” | No sufficient evidence; system should ask for clarification or return an explicit insufficient-context result | `executive_summary` | Must not hallucinate; no forced artifact | `waiting_for_input`, `partial`, or clearly blocked result according to final policy; normally no deliverable | Successful-looking briefing with invented facts; policy must be resolved before release |
| G08 large-input | Sanitized fictional corpus made of repeated but numbered reports totaling near the configured ingestion limit | “Extract the recurring verified findings and produce a bounded summary.” | Sampled/chunked evidence with correct source references; repeated text must not multiply claims | `executive_summary` | Bounded context and token budget; preserve source map | Complete text artifact; no process crash; chunk/source counts visible in safe telemetry | Memory exhaustion, truncated provenance, duplicate claims, or silent partial success |
| G09 conflicting-evidence | `DOC-A` says a fictional count is 12; later `DOC-B` says 15 but does not supersede `DOC-A`; both cite different observation times | “Explain the discrepancy and advise what must be verified.” | Both claims, timestamps, and explicit unresolved conflict | `advisory` | Do not select a winner without evidence; recommend verification | Advisory marks conflict and avoids a definitive count | One value silently selected, conflict hidden, or fabricated resolution |
| G10 multiple-deliverables | One fictional case brief with verified findings, timeline, and a small visualizable trend table | “Create a summary, two-slide presentation, and infographic for review.” | All deliverables use the same permitted evidence set | `executive_summary` + `presentation` + `infographic` | Exactly 2 slides; consistent title/theme; infographic must use safe SVG rules | Three distinct artifacts, correct kinds, stable manifests, shared case/task ownership, matching evidence IDs | Wrong slide count, inconsistent facts, duplicate/foreign artifacts, or one failed child hidden as success |

## Holdout cases

These cases must not be used to tune prompts, thresholds, routing, or expected
wording. Run them only after the golden set and configuration are frozen.

| ID | Source information | Operator request | Expected pipeline | Evaluation focus |
|---|---|---|---|---|
| H01 | Fictional infrastructure inspection note with two confirmed observations and one explicitly unavailable measurement | “Prepare a reviewer brief and identify what cannot yet be concluded.” | `executive_summary` | Uncertainty preservation, evidence coverage, no invented measurement |
| H02 | Fictional maintenance log and follow-up note with a changed status but no explicit supersession field | “State the current status and flag any ambiguity.” | `advisory` | Conservative stale/conflict handling and clarification |
| H03 | Fictional multilingual source snippets containing a date, a count, and a named internal code | “Create a short case brief with source references.” | `executive_summary` | Unicode handling, exact values, provenance, and absence of unsupported translation claims |

## What we record per execution

Store only a sanitized benchmark record:

```json
{
  "case_id": "G01",
  "pipeline": "executive_summary",
  "run_id": "run-...",
  "status": "succeeded",
  "quality_status": "passed",
  "wall_ms": 0,
  "queue_ms": 0,
  "provider_ms": 0,
  "attempts": 1,
  "tokens": {"provider": 0, "estimated": 0, "reconciled": 0},
  "cache": {"hit": false},
  "artifact_count": 1,
  "artifacts": [{"artifact_id": "artifact-...", "sha256": "..."}],
  "evidence_reference_count": 0,
  "issues": []
}
```

Never place source text, raw memory, prompts, credentials, model reasoning, or
full provider payloads in benchmark output.

## Golden versus holdout

- Golden cases are for contract checks, initial quality thresholds, and fixing
  obvious product defects.
- Holdout cases are for the final unbiased evaluation.
- If a prompt or threshold changes after looking at a golden result, record the
  change and rerun the golden set.
- Do not change the system based on holdout results until the holdout results
  are recorded and reviewed.

## Phase 11 status

### Live diagnostic checkpoint — 2026-09-17

The first real API run for G01 (`run-g01-live-03`) returned HTTP-level and
orchestration success, including real provider-backed agent stages. However,
its event stream reported `Loaded 0 bounded User/Case memory records` and
`Recalled 0 permitted memory records`, so the generated summary correctly
avoided inventing facts but did not use the ingested G01 evidence. This is a
content-grounding failure, not a successful golden-case result.

The cause was isolated to the Cognee recall adapter: graph completion with
`only_context=true` returned plain context text without the explicit scope
metadata required by Sudarshan's fail-closed memory policy. The adapter now
uses Cognee's non-generative `CHUNKS` retrieval and recovers the returned
`belongs_to_set` marker into the existing scope/provenance fields. The live
same-case check then returned bounded `case:golden-g01` context, while a
different-case check returned zero results and no G01 content.

The restarted FastAPI end-to-end rerun was completed as
`run-g01-live-04`. Memory recall recovered one bounded permitted record and
the real executive-summary agents ran twice. The quality gate rejected both
drafts, so no artifact was released. The rejected response was preserved for
diagnosis, but it was not treated as a successful result or written back as a
case summary. No raw source text, credentials, or provider payloads are stored
in this report.

### PASS

- Sanitized case catalogue defined for all ten requested golden scenarios.
- Separate three-case holdout set defined.
- Expected evidence, pipeline, constraints, artifact properties, and failure
  conditions are recorded.
- Live Cognee same-case recall recovered bounded G01 context after the adapter
  fix; a different-case recall returned no G01 content.
- The offline G01 replay fixture can build a task-scoped, case-scoped
  grounding ContextPack with the expected facts, unknowns, and source
  reference (`tests/component/test_phase11_g01_fixture.py`).
- The first controlled live run returned non-zero provider counters and wall
  time through the sanitized telemetry projection.
- A fresh live G01 ingestion retry succeeded after the API was restarted in a
  network-capable process context: HTTP 201, evidence indexed, one chunk,
  complete source map, and `memory_persisted=true`.
- A sanitized Phase 11 benchmark-record builder now keeps admission, queue,
  wall, provider, usage, cache, artifact, and quality fields separate. Its
  focused matrix passed 3/3 tests; unavailable values remain `null` rather
  than being reported as zero.
- The machine-readable catalogue at
  `tests/fixtures/phase11_case_catalog.json` contains all 10 golden and 3
  holdout cases. `tests/component/test_phase11_case_catalog.py` passed **3
  tests in 0.06 seconds**, including disjointness, supported-pipeline
  assignment, required evaluation contracts, and secret-free catalogue
  checks.
- An explicit `provider_token_budget` now admits one provider attempt and
  denies retry admission after that attempt. The offline spend-guard matrix
  passed 5/5 tests. This contains retry multiplication but is not yet a
  provider-side total-token cap for the first request.
- Budgeted text execution now applies a conservative per-call completion cap
  and bounds dynamic query/context fields before the model boundary. The
  extended offline matrix passed 9/9 tests; the default unbudgeted path is
  unchanged.

### FAIL

- `run-g01-live-04` ended with `status=failed` after two quality-gate attempts.
  The live model output made unsupported conclusions, treated tasking metadata
  as evidence, and overstated confidence. `artifact_count=0` and no rejected
  draft was released as a successful artifact.
- The live run's aggregate telemetry reported zero provider tokens and zero
  latency despite real memory/provider work. This is a measurement gap, not
  evidence that the request was free.
- The measured run's quality gate rejected the output and released no artifact;
  Phase 11 is not a successful golden-case result yet.
- The next controlled G01 generation request was admitted with HTTP 202 but
  stopped after 4,061 ms with `PROVIDER_TOKEN_BUDGET_EXCEEDED:
  retry admission denied`. No artifact or provider request ID was returned;
  telemetry recorded zero tokens. The server log identifies the root cause:
  the configured GPT-5.4 route rejected `max_tokens` and requires
  `max_completion_tokens`; the spend guard then prevented a retry. This is a
  genuine compatibility defect at `pipelines/common/text_generation.py`, not
  a successful artifact result.
- `token_budget=1200` did not cap the observed 35,330 provider-reported tokens.
  This is a spend-control product gap, not a test weakness.
- The local guard cannot undo system-prompt or provider-side accounting that
  exceeds the first-request budget; a true total-token ceiling still requires
  provider receipt enforcement and a final prompt-size policy.

### Provider compatibility checkpoint — 2026-09-18

The live failure identified a real request-parameter defect: the configured
GPT-5.4 route was receiving the legacy `max_tokens` parameter. The targeted
fix in `pipelines/common/text_generation.py` keeps the existing budget and
retry policy, but sends GPT-5-family requests only the provider-native
`max_completion_tokens` parameter. Legacy model families retain the existing
`max_tokens` path.

The regression test checks CrewAI's prepared request dictionary, so it proves
the parameter that would be sent without spending provider credits. The
focused compatibility/provider tests passed **14/14**, affected pipeline
tests passed **107/107**, and the full offline regression passed **705**, with
8 skipped and 32 warnings. The prior live failure remains recorded as an
important baseline; it was not deleted or relabeled as a success.

### Controlled live rerun after the compatibility fix — 2026-09-18

The fresh run `phase11-g01-live-fixed-20260918-143649` confirmed that the
`max_completion_tokens` request reached GPT-5.4. The provider reported 1,145
prompt tokens and 240 completion tokens, for 1,385 total provider-reported
tokens. The run took 23,559 ms at the application/CrewAI wall-clock boundary.

It still failed safely because the structured response reached the 240-token
per-call cap and could not be parsed. No artifact was released, and the
existing spend guard denied a retry. This is now a separate budget-allocation
finding: the current 1,200-token total budget is incompatible with the
requested 250–400-word structured executive-summary constraint. No further
paid live run was started after this result.

### Budget-cap experiments — 2026-09-18

Two additional single-run experiments used the same sanitized G01 request:

- `provider_token_budget=3000` produced a 600-token per-call cap. The
  structured response reached that cap and failed parsing after 33,247 ms.
- `provider_token_budget=6000` produced a 1,200-token per-call cap. The first
  two analysis stages completed, but the final structured response reached the
  cap and failed parsing after 59,266 ms.

Both runs failed safely, released no artifact, and did not retry. These are
not reasons to keep increasing the live budget blindly. They show that the
existing five-way output allocation is not a reliable contract for the
executive-summary pipeline. An additive `provider_output_token_budget` request
override is now available in the common text-generation boundary; it changes
only the completion cap for a pipeline while retaining the existing total
budget and retry guard. It has been covered by offline regression tests but
has not yet been used in another paid live run.

### Final controlled G01 budget run — 2026-09-18

The authorized run `phase11-g01-live-budget12000-20260918-145924` used a
12,000-token total budget and a 2,400-token per-call output cap. The provider
accepted the corrected GPT-5.4 request. All four executive-summary stages
reached completion events, but the aggregate provider receipt reported 54,165
input tokens and 11,919 output tokens, or **66,084 observed tokens** including
13,056 cached input tokens. Wall time was **55,399 ms**.

The existing spend guard then marked the run failed and denied retry. No
artifact was released. This is a critical Phase 11 finding: increasing the
per-call output cap does not make the current multi-agent pipeline fit a
12,000-token total budget. The LLM key should now be removed again. No further
live generation should run until the pipeline is made cost-bounded or its
multi-agent prompt/context flow is reduced.

### Instrumentation checkpoint — 2026-09-18

The common CrewAI text-pipeline boundary now retains the returned
`CrewOutput.token_usage`, records separate retry-attempt counters, and exposes
one deduplicated aggregate usage record through the existing response and
observability projections. Crew wall time is recorded separately from
provider-only latency. Cost remains explicitly unavailable until pricing or a
provider billing receipt is configured.

The offline instrumentation matrix passed 4/4 tests, the affected telemetry
and pipeline regression passed 134 tests, and the full local regression passed
688 tests with 8 skipped and 32 warnings. This was the pre-live measurement
checkpoint; the first measured live run is recorded below.

### First measured usage run — 2026-09-18

The controlled run `run-g01-usage-20260918-01` was admitted with HTTP 202 in
114 ms and ended `failed` after two attempts. Safe telemetry recorded 29,430
input tokens, 5,900 output tokens, zero separate reasoning tokens, and 69,177
ms of CrewAI wall time. It recorded 48 observability events, one main
trajectory lane, and two usage records. No artifact was released because the
quality gate rejected ungrounded findings and unsupported procedural
recommendations. Cost remained unavailable.

This proves real provider usage is now visible. It also found that
`token_budget=1200` is not a hard provider-spend cap: the observed total was
35,330 tokens. No further live calls should run until spend-control policy is
decided. Trajectory and observability were available, but
`/runs/{run_id}/dag` returned 404 for this normal `/runs` run.

### NOT YET IMPLEMENTED

- Actual live execution of these cases.
- Successful live execution of G01 with a grounded artifact.
- Live execution of G02-G10 and the holdout cases.
- Automated benchmark runner and p50/p95 aggregation.
- Final claim/evidence scoring rubric and human review scores.
- DAG persistence/projection for the normal `/runs` route; the measured run's
  `/runs/{run_id}/dag` request returned 404 while observability and trajectory
  were available.
- Provider-side total-token enforcement, including system prompts and any
  hidden provider/tool calls, for the first request.
- One fresh live provider run after the compatibility fix; this is required to
  confirm that the request now reaches GPT-5.4 and to measure real provider
  latency, usage, cost, and artifact quality.
- A live run that completes a valid structured response and produces an
  artifact; the first corrected live rerun reached the provider but hit the
  output cap.

### NEEDS DESIGN DECISION

- Exact insufficient-context status and whether a blocked case may produce a
  clarification artifact.
- Minimum evidence coverage score for each pipeline.
- Whether operational task-event memory should be excluded from grounding
  context or carried with an explicit non-evidence type.
- Whether live quality rejection should expose a safe failure summary and
  quality status in the standard run projection.
- Whether G10 child failure makes the parent `partial` or `failed`.
- Exact visual-quality rubric for PPTX and infographic output.
- Whether `provider_token_budget` is a total request budget or an output budget,
  and the minimum per-call completion cap required by each pipeline contract.
- Whether the executive-summary contract should use a 2,400-token completion
  cap, or whether its schema/prompt should first be made more compact.
- Whether the current multi-agent executive-summary route is acceptable at an
  observed 66,084 tokens, or must be redesigned to enforce a true per-run
  provider ceiling before Phase 11 can be marked successful.

## Next execution order

1. Review and freeze the golden/holdout catalogue.
2. Configure local `.env` without sharing secrets.
3. Start FastAPI and verify the actual provider-backed service.
4. Execute G01 once through the real API and inspect every projection.
5. Execute G01 again with the same request identity to verify duplicate behavior.
6. Execute G05 or G10 to verify multi-document and multi-artifact flow.
7. Only after those pass, run the complete golden set repeatedly.
8. Run holdout cases last.
