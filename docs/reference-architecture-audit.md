# Reference architecture audit

This audit compares the checked-in Sudarshan implementation with the local
reference repositories under `C:\Users\uditj\Downloads\sudarshan\references`.
The references are design inputs, not runtime dependencies. Sudarshan keeps its
own contracts, policy, scheduler, evidence boundary, and artifact manifests.

## Current adoption

| Reference | Adopted in Sudarshan | Remaining gap or deliberate boundary |
| --- | --- | --- |
| `agentmemory` | Scoped memory lifecycle, confidence/provenance, retract/forget, plugin-style skills, safe telemetry | Add a reviewed memory-evaluation corpus and optional non-blocking session lifecycle hooks; do not copy its coding-agent hooks into the NTRO backend. |
| `OpenViking` | L0/L1/L2 context selection, bounded context packs, source references, retrieval trace IDs, lazy skill references | No `viking://` filesystem is needed while Cognee Cloud remains the memory backend. Preserve the useful ideas through `context_uri`, tiered loading, and trajectory telemetry rather than introducing a second memory database. |
| `MoneyPrinterTurbo` | Provider-neutral video timeline, storyboard/assets ledger, material cache, subtitles, bounded parallel scene work, native renderer fallback | Keep the reference workflow behind Sudarshan's `VideoPackage`, budget, cancellation, object-store, and quality contracts. Do not execute its WebUI or copy its provider credentials. |
| `ppt-master` | Renderer capability registry, PPT adapter boundary, source/quality manifests, visual QA and editable-output policy | PM-3–PM-9 remain release work: structured SVG/page planning, template/layout validation, dependency-aware slide jobs, and visual regression. The external repository is not imported at runtime. |
| `infographic` / AntV | Declarative `InfographicIR`, pinned SSR adapter, SVG structural/text QA, deterministic fallback | Complete template registry, NTRO design tokens, streaming preview, and browser visual regression before promotion. |
| `diagram-design` | Semantic diagram registry, editorial/static-first output, safe HTML/SVG export, bounded imports, accessibility checks | Expand the semantic family and visual regression fixtures; optional motion remains opt-in and cannot change the static default. |
| `linkedin-skills` | Draft-only LinkedIn skill, humanizer boundary, approval/publish policy, typed child-plan support | Complete reviewed tone/humanizer evaluations and keep publish disabled unless an explicit approval/publish connector is configured. |

## What is connected to native Harness

The native path is now:

```text
Harness web profile
  -> Sudarshan Artifact Agent preset
  -> artifact MCP tool profile
  -> integrations.deepseek_harness.mcp_server
  -> allow-listed SudarshanHarnessAdapter
  -> SudarshanApplication
  -> LangGraph + CrewAI skills + Cognee Cloud + artifact/quality gates
  -> safe status/events/artifact manifests
  -> native OperationsBridge
```

The OperationsBridge now observes native Harness `tool/call` and `tool/result`
events. When `start_sudarshan_run` returns a `run_id`, it automatically binds
that run to the active Harness session, loads terminal artifact manifests, and
subscribes to `/runs/{run_id}/events`. The same backend remains usable through
external MCP and A2A adapters.

The native profile intentionally exposes fewer model-facing tools than the
external profile. It keeps lifecycle, skill discovery/dispatch, waiting, and
artifact retrieval while hiding direct evidence/memory-maintenance operations.
This is the token and policy advantage of the native composition; it is not a
second orchestrator.

## Cognee Cloud boundary

Cognee Cloud is now the product default. `MemoryManager` is still the only
memory gateway. It sends tenant-scoped requests with `X-Api-Key` and
`X-Tenant-Id`, and cloud mode rejects local/HTTP endpoints or missing
credentials. `COGNEE_BACKEND=local` is retained only as an explicit development
compatibility mode.

Exact evidence, authorization, lifecycle, and audit state remain in Sudarshan;
Cognee stores governed memory projections and retrieval context. The browser,
Harness agent, CrewAI agents, and renderers never receive Cognee credentials or
an unrestricted Cognee client.

## Remaining high-value work

1. Run live Cognee Cloud health/remember/recall tests with a sanitized tenant;
   never put the key in CI output.
2. Add a real native Harness browser smoke: start a run, observe automatic
   session binding, reconnect SSE, preview an artifact, and download it.
3. Complete PPT/infographic/diagram visual regression and human-promotion gates.
4. Benchmark memory retrieval quality and token savings against the current
   L0/L1/L2 policy; do not claim OpenViking or agentmemory performance without
   a reviewed corpus.
5. Add package-manifest/license checks for any future copied reference asset.

The implementation is therefore reference-informed and portable, but not a
full copy of any reference system. The strongest production gaps are live
Cloud validation, browser E2E evidence, and visual-quality promotion—not a
missing orchestration framework.
