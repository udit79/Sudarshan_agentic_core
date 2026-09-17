# Phase 5 — Pipeline contract testing report

Date: 2026-09-17  
Scope: deterministic component and pipeline-contract boundaries only  
Source of truth: [`docs/pipeline-benchmarking.md`](pipeline-benchmarking.md)

## Mentor summary

**WHAT** — A pipeline contract defines the input it accepts, the typed output
it returns, and the failure states that the rest of Sudarshan can understand.

**WHY** — Each pipeline has different rules. A presentation has slide-count
and rendering requirements; a LinkedIn pipeline must remain draft-only; a video
pipeline has scene and media lifecycle states.

**WHERE** — Public routing is registered in
`pipelines/orchestrator/graph.py`; the shared request/response boundary is in
`pipelines/common/contracts.py`; pipeline-specific schemas and quality gates
live under each pipeline package.

**INPUT** — Sanitized request identity (`user_id`, `case_id`, `task_id`), query,
authorized context, and pipeline-specific constraints.

**OUTPUT** — A validated typed draft/artifact or an explicit `failed`,
`partial`, or `pending` response.

**TEST** — `tests/component/test_pipeline_contract_matrix.py` plus the
existing focused pipeline and lifecycle tests listed below.

**RESULT** — The new deterministic matrix passed **62 tests**. The existing
focused pipeline baseline passed **42 tests**. No provider credentials were
used and no product code was changed in this phase.

## Actual routes

The repository documents these unique executable capabilities in
`pipelines/README.md`:

| Route | Implementation | Contract-specific output or artifact |
| --- | --- | --- |
| `advisory` | `pipelines/advisory/crew.py` | Evidence-linked `AdvisoryOutput`, quality review, human approval before case write-back |
| `executive_summary` | `pipelines/executive_summary/crew.py` | Evidence-linked `ExecutiveSummaryOutput` |
| `linkedin_post` | `pipelines/linkedin/crew.py` | Draft-only `LinkedInPostOutput`, humanizer, optional image handoff |
| `presentation` | `pipelines/ppt/crew.py` | `PresentationOutput`, native PPTX, slide/theme/quality gates |
| `ppt` | Alias in `pipelines/orchestrator/graph.py` | Compatibility route to the presentation flow |
| `infographic` | `pipelines/infographic/crew.py` | AntV `InfographicOutput`, SVG quality gate, native/fallback mode |
| `video` | `pipelines/video/pipeline.py` | `VideoPackage`, scene media bundle, manifest, MP4 or partial result |
| `visual_flowchart` | `pipelines/ppt/child_skill.py` | Verified SVG/PPTX child artifacts and quality report |

`pipelines/diagram/` is not counted as a ninth top-level route because the
repository explicitly describes it as a reusable package rather than a
registered route.

## Contract matrix

`PASS` means an automated test currently proves the behavior. `PARTIAL` means
there is related shared or lower-level coverage but not a complete execution
test for every route. `NOT YET IMPLEMENTED` means the current architecture has
no safe, explicit test seam or product policy for that behavior.

| Pipeline | Accepted input | Required context | Output / validation | Artifact requirement | Current result |
| --- | --- | --- | --- | --- | --- |
| Advisory | `AdvisoryRequest` with non-empty query and identity | User/Case/Task context and evidence for recommendations/facts | `AdvisoryOutput`; evidence linkage, no placeholders, quality review | Markdown/case artifact after approval path | Contract PASS; live failure matrix pending |
| Executive summary | Same request envelope | Evidence for key findings and factual claims | `ExecutiveSummaryOutput`; evidence linkage, no placeholders | Validated summary delivery | Contract PASS; explicit low-context policy pending |
| LinkedIn | Same request envelope plus image/voice metadata when requested | Evidence/source references for public claims | `LinkedInPostOutput`; humanizer; always `draft_only` | Optional prompt/asset, never direct publication | Contract PASS; provider lifecycle pending |
| Presentation/PPT | Same request plus `RequestConstraints` | Case context sufficient for at least two slides | `PresentationOutput`; unique slide IDs/orders, exact-count/theme/render gates | Native PPTX and manifest | Contract PASS; live provider lifecycle pending |
| Infographic | Same request | Evidence and valid AntV syntax | `InfographicOutput`; directive, SVG safety/accessibility | SVG or explicit degraded/syntax-only state | Contract PASS; live renderer failure matrix pending |
| Video | Same request plus script/package/storyboard when supplied | Subject and enough material for scenes | `VideoPackage`/scene contracts; scene-level status and QA | Media bundle, manifest, MP4 or explicit partial | Contract PASS; provider integration pending |
| Visual flowchart | Same request plus optional flowchart metadata | Current child implementation supplies a default graph when omitted | SVG/PPTX child artifacts and quality report | Two registered artifacts | Basic child path exists; insufficient-context policy pending |

## Requested case coverage

| Requested case | Evidence in repository | Result |
| --- | --- | --- |
| Normal valid request | New matrix parameterizes all public routes | PASS |
| Missing required input | New matrix checks query, user, case, and task identity for every route | PASS |
| Insufficient context | Evidence fields are required for several output contracts, but no common pipeline policy returns an explicit low-context result | NOT YET IMPLEMENTED / design decision |
| Invalid constraints | `RequestConstraints`, theme validation, schema validators | PASS for defined constraints |
| Boundary constraints | Slide count, video scene duration, schema min/max fields | PASS for defined boundaries |
| Malformed model output | New matrix removes required fields and validates typed models | PASS at schema boundary |
| Provider failure | Shared flow catches exceptions; video provider job store has submit-unknown coverage | PARTIAL |
| Timeout | Renderer cancellation/timeout seams and video job lifecycle have lower-level coverage | PARTIAL |
| Retry | Shared text flow has a retry route; video provider reconciliation has coverage | PARTIAL |
| Partial result | Video partial scene result is tested in `tests/component/test_np09_pipelines.py` | PASS for video; pending for other routes where applicable |
| Duplicate request | Admission/control-plane tests cover duplicate logical admission | PASS at orchestration boundary; not a transformation-pipeline concern |
| Wrong-case evidence | Case-isolation tests and artifact evidence ownership checks cover storage/artifact boundaries | PARTIAL; text outputs lack a shared post-generation ownership verifier |
| Unsupported request | Unregistered route rejection is tested in `tests/pipeline/test_pipeline_contracts.py` | PASS at router boundary |
| Validation failure | Pipeline-specific Pydantic and quality gates reject invalid output | PASS at deterministic boundary |

## Tests added

`tests/component/test_pipeline_contract_matrix.py` adds 62 deterministic tests
covering:

- all public routes, including the `ppt` compatibility alias;
- shared request identity and query validation;
- presentation constraint matching and boundaries;
- valid versus malformed outputs for advisory, executive summary, LinkedIn,
  infographic, presentation, and video package contracts;
- evidence linkage and placeholder rejection;
- LinkedIn draft-only and model-self-reference protection;
- AntV syntax requirements;
- presentation slide identity;
- video scene duration boundaries;
- explicit success/failure `PipelineResponse` transport semantics.

Existing supporting tests remain important:

- `tests/pipeline/test_pipeline_contracts.py` — router response, unsupported
  route, pending provider job, revision, and fan-out contracts;
- `tests/component/test_np09_pipelines.py` — evidence linkage, humanizer,
  provider-pending video state, partial video scenes, and SVG quality;
- `pipelines/tests/test_advisory_pipeline.py` — advisory flow boundary;
- `pipelines/tests/test_text_pipelines.py` — text flow, LinkedIn, and summary
  rules;
- `pipelines/tests/test_infographic_pipeline.py` — infographic flow and syntax;
- `tests/pipeline/test_ppt_*.py` — presentation contracts and tasks;
- `tests/pipeline/test_video_pipeline.py` — video planning, fallback, retry,
  and bounded scene execution.

## Classification

### PASS

- Deterministic route/request contract matrix: 62 passed.
- Existing focused pipeline baseline: 42 passed.
- Typed output validation and pipeline-specific deterministic gates.
- No product-code fix was required by this phase.

### FAIL

- None after correcting one test assertion to match the product's actual,
  stable LinkedIn validation message.

### NOT YET IMPLEMENTED

- A uniform, explicit insufficient-context result for every pipeline.
- Full provider-failure and timeout injection for every transformation flow.
- A shared post-generation verifier that resolves every output evidence ID
  against the active User/Case/Task scope.

### NEEDS DESIGN DECISION

- What exact signal makes context “insufficient” for each pipeline?
- Should unsupported constraints be rejected or ignored per pipeline?
- Should conflicts prefer newest evidence, require human review, or produce a
  partial result?
- What claim/evidence binding is required for free-form narrative fields?

## Board update recommendation

Mark item 17 (**Pipeline contracts**) and item 19 (**Malformed model output**)
as component-complete. Keep item 18 (**Insufficient-context generation**)
open until the product behavior is explicitly defined and tested. Keep
provider/timeout/retry coverage open for the failure/recovery phases.

This phase did not require DeepSeek, Cognee, MongoDB, or other credentials.
Live provider tests should use local environment variables and sanitized
fixtures when the failure-injection and benchmark phases begin.
