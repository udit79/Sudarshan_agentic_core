# Pipelines

Pipelines transform authorized case context into typed drafts or artifacts.
The LangGraph orchestrator owns routing, lifecycle, budgets, retries,
cancellation, parallel fan-out, and delivery. Pipeline code owns specialist
generation and pipeline-specific quality checks.

## Registered routes

The default registry is built in
[`pipelines/orchestrator/graph.py`](orchestrator/graph.py):

| Route | Implementation | Output | Status |
| --- | --- | --- | --- |
| `advisory` | `advisory/crew.py` | Reviewed advisory and Markdown artifact | Local |
| `executive_summary` | `executive_summary/crew.py` | Evidence-linked summary | Local |
| `linkedin_post` | `linkedin/crew.py` | Humanized draft and optional image | Draft-only |
| `presentation` | `ppt/crew.py` | Native PPTX and manifest | Native local path; exact-count, theme, editability, and post-render gates are covered; office visual smoke remains external |
| `ppt` | Alias of `presentation` | Same as presentation | Compatibility only |
| `infographic` | `infographic/crew.py` | AntV syntax and SVG | Native/fallback local path |
| `video` | `video/pipeline.py` | Storyboard, media bundle, and MP4 | Native local path plus optional worker |
| `visual_flowchart` | `ppt/child_skill.py` | Verified SVG/PPTX child artifact | Child capability |

The `diagram/` package provides semantic diagram IR, validation, import, style,
and export utilities. It is not a separate top-level pipeline route yet.

## Shared lifecycle

```text
authenticated request
  -> bounded User/Case/Task context
  -> typed prompt plan
  -> pipeline or child skill
  -> Pydantic output validation
  -> deterministic quality gate and repair
  -> renderer/provider, when needed
  -> artifact manifest and safe progress events
  -> approved Case/Task memory write-back
```

The current runtime still has a request-understanding graph phase. The planned
NP-04 migration to a persisted preparation phase is not complete until the
graph no longer calls `RequestUnderstandingAgent`.

Memory access is always through `MemoryManager`; agents never receive Cognee
credentials or a Cognee client. Case-memory write-back is allowed only after
the pipeline release gate. Task events may be written during execution.

## Pipeline notes

### Advisory

Uses structured intelligence, evidence/provenance checks, a quality critic,
and an explicit human release gate before writing the approved advisory to
case memory.

### Executive summary

Uses the shared text-generation flow. Key findings and factual claims must
reference evidence IDs. It returns a validated summary; frontend delivery and
editing remain outside the pipeline.

### LinkedIn

Produces a draft only. The humanizer checks claim bindings, AI-tell signals,
and release thresholds. Direct publication is intentionally not implemented.
Image generation is optional and may return a prompt fallback when no image
provider is configured.

### Presentation/PPT

The renderer enforces the explicit slide count and maintains stable slide IDs,
per-slide hashes, dependency invalidation, and manifests. Targeted edits copy
an existing local PPTX and preserve unrelated slide parts. Structural
insertion/reordering and true native layer/z-order preservation remain
explicitly bounded cases. PPT Master is only an optional local bridge: it is
not hosted or installed by Sudarshan and requires a user-managed checkout via
`SUDARSHAN_PPT_MASTER_ROOT`.

### Infographic

AntV SSR is the native renderer. The deterministic fallback is marked
degraded, and unsafe SVG content, missing dimensions, missing text, and
invalid renderer modes are rejected. Palette validators exist, but a user
request must still be connected to `required_palette`/`allowed_palette` for
custom colors to become an enforced pipeline constraint.

### Video

The default path plans a storyboard, creates bounded scene media, composes a
local package, and records a quality report. MoneyPrinterTurbo is an explicit
optional compatibility worker, not the default and not a MiniMax provider.
Provider-pending, retry, cancellation, partial-scene, and reconciliation
behavior require live worker and media-fixture verification before production.

### Visual flowchart and diagrams

`visual_flowchart` is a typed child skill used by parent skills such as PPT and
LinkedIn. `pipelines/diagram/` contains the reusable semantic IR and safe SVG/
HTML exporter. A standalone diagram-agent route, diagram-specific MCP/A2A
projection, and broad reviewed visual corpus are not complete.

## Run focused checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp .pytest-tmp-current `
  pipelines/tests/test_advisory_pipeline.py `
  pipelines/tests/test_text_pipelines.py `
  pipelines/tests/test_infographic_pipeline.py `
  tests/pipeline/test_ppt_tasks.py `
  tests/pipeline/test_video_pipeline.py `
  tests/component/test_np06_incremental.py `
  tests/component/test_np09_pipelines.py
```

Use [pipeline benchmarking](../docs/pipeline-benchmarking.md) for frozen
fixtures, hard gates, failure injection, latency, tokens, cache behavior, and
release thresholds. Use [pipeline observability](../docs/pipeline-observability.md)
to inspect progress, parallel lanes, provider events, and Cognee operation
metadata.
