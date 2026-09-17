# Phase 6 — Artifact correctness and artifact quality

## WHAT

This phase checks the files produced after a pipeline runs. It separates two
questions:

- **Artifact correctness:** Is the file present, readable, the declared type,
  structurally valid, owned by the correct User/Case/Task, and linked to the
  expected evidence?
- **Artifact quality:** Is the content complete, grounded, readable, visually
  clear, consistent, and useful to a human?

Structural validity means that a file follows the format rules and can be
opened by a parser. It does not mean the file is persuasive, readable, or
visually well designed.

## WHY

A PPTX can open successfully while containing the wrong number of slides,
missing sections, unreadable text, or unsupported claims. The repository can
automate many safety and structure checks, but human review remains necessary
for visual hierarchy, typography at presentation distance, and whether the
artifact communicates well.

## WHERE

- Registration, immutable manifests, checksum verification, ownership, and
  quality-report persistence: `api/artifacts.py`
- Renderer declarations and inspection dispatch:
  `pipelines/common/renderers.py`
- Cross-format integrity checks:
  `pipelines/common/visual_qa.py`
- PPTX content and rendered-contract checks:
  `pipelines/ppt/presentation_quality.py`
- PPTX generation:
  `pipelines/ppt/renderer.py`
- Infographic SVG safety and accessibility checks:
  `pipelines/infographic/quality.py`
- Video media checks:
  `pipelines/video/quality.py`
- Observable timing, usage, cache, artifact, and quality references:
  `pipelines/orchestrator/observability.py`
- Offline harness boundary timing:
  `scripts/benchmark_harness.py`
- Benchmark rules and sanitized reporting requirements:
  `docs/pipeline-benchmarking.md`

## INPUT → OUTPUT

The tested flow is:

`validated pipeline output → renderer → artifact file → integrity/quality gate → immutable manifest → API-visible artifact reference`

The manifest carries `user_id`, `case_id`, `task_id`, `evidence_ids`,
`source_ir_hash`, checksum, size, renderer version, quality status, and quality
report reference. These fields are the provenance record: they explain where a
file came from and which scope owns it.

## Measurable artifact matrix

| Artifact / concern | Automated criterion | Human review still required | Current evidence |
|---|---|---|---|
| PPTX existence | Missing, empty, and corrupt packages fail | None for existence | `test_artifact_correctness_matrix.py` |
| PPTX file type | Declared `pptx` inspection parses the package; wrong declared type fails | None for file type | New regression test |
| PPTX structure | Required package parts exist and the package opens | PowerPoint compatibility across viewer versions | `visual_qa.py`, PPT tests |
| PPTX slide count | Actual count equals `RequestConstraints.slide_count` | Whether the chosen count is useful | New matrix and `presentation_quality.py` |
| PPTX required content | Required sections/text are present | Factual completeness and narrative quality | New matrix and existing PPT tests |
| PPTX theme/layout/editability | Background, accent layer, editable text, fonts, palette, z-order, and overflow proxies are checked | Visual hierarchy, spacing, contrast at distance, typography quality | `presentation_quality.py` and existing PPT tests |
| PPTX placeholders | `[insert` and `TBD` are rejected by the output contract | Whether a non-placeholder statement is still meaningful | New matrix and schema validator |
| SVG/infographic | Root, dimensions, closing tag, safety, required text, palette, accessibility, and renderer mode are checked | Visual clarity and chart interpretation | New matrix and `pipelines/infographic/quality.py` |
| PNG/JPG | Image decoder, dimensions, and non-empty file are checked | OCR, labels, readability, visual hierarchy | New matrix; OCR is not implemented |
| PDF | PDF parser and page count are checked; required text can be checked when supplied | Visual pagination and readability | New matrix and `visual_qa.py` |
| Video | Missing/empty output fails; `ffprobe` can check stream and duration | Narrative quality, pacing, subtitle legibility | New matrix and `video/quality.py` |
| Manifest/provenance | Owner, scope, evidence IDs, IR hash, checksum, and size survive registration | Whether the referenced evidence really supports every claim | New matrix and `api/artifacts.py` |
| Tamper resistance | Changed bytes fail checksum verification | None for byte-level tampering | New matrix |
| Artifact quality status | Failed gates are persisted as failed candidates with a quality report | Whether an operator should repair or reject | New matrix and `register_checked` |

## Test cases added

`tests/component/test_artifact_correctness_matrix.py` adds the smallest tests
for these real product questions:

1. Missing, empty, and corrupt PPTX files are rejected.
2. A rendered PPTX has readable package structure, required visible text, and
   a non-zero size.
3. A non-empty `.bin` file cannot pass as a declared PPTX.
4. A failed SVG quality check is recorded and is not promoted as passed.
5. User/Case/Task ownership and evidence references survive in the manifest.
6. A post-registration byte change is detected by checksum verification.
7. Exact slide count and required sections are enforced.
8. Density and long-text overflow proxies are reported.
9. PNG dimensions and decoder integrity are checked, while the test documents
   that OCR/readability is not claimed.
10. PDF page integrity is checked.
11. SVG safety and strict accessibility checks reject executable content.
12. Video missing/corrupt behavior is reported without treating bytes alone as
   proof of media quality.
13. Unresolved presentation placeholders are rejected.

## RESULT

### Focused test result

The final focused run after the product fix and PDF check passed:

```text
tests/component/test_artifact_correctness_matrix.py
13 passed in 4.68s
```

The matrix contains 13 test functions after the PDF test was added. The final
affected regression also passed:

```text
205 passed, 1 warning in 13.14s
```

The warning came from a Starlette/AnyIO deprecation notice and did not fail a
test.

### Product fix

`RendererRegistry.inspect` now accepts the declared artifact kind, and
`ArtifactStore.register_checked` passes that declaration into the integrity
inspector. This prevents a non-empty file with an unrelated suffix from being
treated as an untyped, automatically approved artifact. The change is small,
backward-compatible for existing callers, and limited to artifact inspection.

### Classification

**PASS**

- Artifact store manifests preserve ownership, evidence references, checksums,
  size, and source IR hash.
- Missing, empty, corrupt, wrong-type, and tampered artifacts are rejected or
  recorded as failed.
- PPTX structure, exact-count constraints, required sections, theme signals,
  editability signals, density, overflow proxy, and placeholders are covered.
- SVG safety/accessibility, PNG decoder/dimensions, and PDF page integrity have
  deterministic checks.

**FAIL**

- None in the final focused matrix or affected regression.

**NOT YET IMPLEMENTED**

- OCR or equivalent label verification for raster PNG/JPG artifacts.
- Full codec and duration validation when `ffprobe` is unavailable. This
  environment currently reports `ffprobe-unavailable`; the video inspector
  records that limitation instead of hiding it.
- Automated factual-grounding scoring and claim-by-claim evidence coverage for
  final presentation slides.
- Automated visual review of readability, hierarchy, typography at distance,
  and overall usefulness.

**NEEDS DESIGN DECISION**

- `PresentationOutput.SlideContent` does not currently carry evidence bindings,
  although `DeckPlan`/`SlideSpec` and `SlideManifest` do. Decide whether final
  slides must expose claim-level evidence IDs before adding a hard gate.
- Define the acceptance threshold for “quality” beyond structural checks:
  human rubric, model-assisted review, or both.
- Decide whether a missing `ffprobe` should remain a warning/partial result or
  fail video release in CI.

## Timing, cache, and latency plan

The benchmark specification requires warmup, repeated runs, p50/p95 wall time,
queue time, provider time, attempts, tokens, estimated cost, cache outcome,
artifact count, partial/failure rate, and concurrency. Phase 6 records the
artifact-side timing boundary; later benchmark phases combine all boundaries.

| Level | What to measure | Existing source / planned fixture |
|---|---|---|
| Component | pytest duration and artifact inspection/render duration | Focused pytest command; use `--durations=10` for slow tests |
| Pipeline | admitted run wall time, provider latency, renderer/quality duration | `ObservabilityEvent.duration_ms` and `TelemetryUsage.latency_ms` |
| System | HTTP/API request from upload or request admission through artifact response | FastAPI/API test client or a real API runner in the live phase |
| Harness | boundary dispatch, sandbox, MCP and end-to-end harness timing | `scripts/benchmark_harness.py`; extend only when live mode is authorized |

Current offline harness run:

```text
provider_calls=0
model_tokens=0
network_calls=0
adapter_health_dispatch_p50_local=0.0 ms (rounded)
renderer_count=8
timeout_detected=true
secret_redaction_passed=true
```

This is a local boundary benchmark, not evidence of OpenAI/DeepSeek latency or
cost. Real provider measurements require the later live benchmark gate.

Cache fixtures should live under a dedicated benchmark fixture directory, for
example `tests/fixtures/benchmark/`, and contain sanitized request fingerprints
and expected cache outcomes. They should not reuse a developer's live cache or
database. Latency fixtures should patch provider/renderer seams with bounded,
deterministic behavior so timeout and retry tests do not sleep unpredictably.

For the SIH chart, store one sanitized row per run with `run_id` hash, pipeline,
artifact kind, warm/cold label, cache status, wall p50/p95, provider p50/p95,
artifact inspection p50/p95, input/output tokens, estimated cost, and outcome.
Do not store raw prompts, memory text, credentials, hidden reasoning, or
sensitive evidence in benchmark logs. Matplotlib chart generation belongs to
Phase 13 after the timing data has real repeated-run coverage.

## Hands-on command

Run the focused Phase 6 matrix yourself:

```powershell
$runStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$base = Join-Path $env:TEMP "sudarshan-artifact-phase6-$runStamp"
.venv\Scripts\python.exe -m pytest `
  tests/component/test_artifact_correctness_matrix.py `
  tests/component/test_artifact_store.py `
  tests/component/test_presentation_quality.py `
  tests/pipeline/test_ppt_contracts.py `
  tests/pipeline/test_ppt_quality.py `
  tests/pipeline/test_infographic_render.py `
  tests/pipeline/test_infographic_export.py `
  tests/pipeline/test_video_pipeline.py `
  tests/component/test_video_adapter.py `
  tests/component/test_video_evidence.py `
  tests/component/test_video_timeline.py `
  -q --basetemp=$base -p no:cacheprovider
```

This is deterministic and does not require OpenAI, DeepSeek, Cognee, MongoDB,
or other provider credentials. Credentials become necessary for the separate
live API/data-flow phase, where we will explicitly label calls, capture
sanitized usage/latency, and protect secrets.

## Next step

Keep this checkpoint uncommitted until you run the command and confirm the
result. Once the focused and affected regression runs are green, Phase 6
correctness can be checked on the board. Artifact quality should remain open or
partial until the team completes a human visual review and resolves the final
slide-evidence decision.
