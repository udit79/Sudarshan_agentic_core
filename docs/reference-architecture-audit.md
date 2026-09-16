# Reference architecture audit

This audit compares the checked-in Sudarshan implementation with the local
reference repositories under `C:\Users\uditj\Downloads\sudarshan\references`.
The references are design inputs, not runtime dependencies. Sudarshan keeps its
own contracts, policy, scheduler, evidence boundary, and artifact manifests.

## Current adoption

| Reference | Adopted in Sudarshan | Remaining gap or deliberate boundary |
| --- | --- | --- |
| `agentmemory` | Scoped memory lifecycle, confidence/provenance, retract/forget, plugin-style skills, safe telemetry | Add a reviewed memory-evaluation corpus and optional non-blocking session lifecycle hooks; do not copy its coding-agent hooks or 54-tool surface into the NTRO backend. See [ledger](reference-adaptations/agentmemory.md). |
| `OpenViking` | L0/L1/L2 context selection, bounded context packs, source references, retrieval trace IDs, lazy skill references | No `viking://` filesystem is needed while Cognee Cloud remains the memory backend. Preserve the useful ideas through `context_uri`, tiered loading, and trajectory telemetry rather than introducing a second memory database. The main checkout is AGPL-3.0; see [ledger](reference-adaptations/openviking.md). |
| `MoneyPrinterTurbo` | Provider-neutral video timeline, storyboard/assets ledger, material cache, subtitles, bounded parallel scene work, native renderer fallback | Keep the reference workflow behind Sudarshan's `VideoPackage`, budget, cancellation, object-store, and quality contracts. Do not execute its WebUI or copy its provider credentials; make every degradation visible. See [ledger](reference-adaptations/moneyprinterturbo.md). |
| `MiniMax-H3` | Candidate audiovisual provider: mode-specific prompt shaping, reference anchors, native stereo audio, and optional 768p→2K regeneration as dependent provider stages | Not an agent runtime: the checkout is model/VAE code, API examples, and Hub-only skills with no case memory, durable scheduler, generic MCP/A2A, or application renderer. Use an external H3 worker/provider adapter; keep Sudarshan lifecycle, memory, assembly, and quality authority. See [audit ledger](reference-adaptations/minimax-h3.md). |
| `ppt-master` | Renderer capability registry, bounded local adapter, source/quality manifests, visual QA and editable-output policy | PPT Master is not hosted or imported at runtime. It is usable only when the user installs/self-hosts the exporter and sets `SUDARSHAN_PPT_MASTER_ROOT`; otherwise native PPT rendering is authoritative. See [ledger](reference-adaptations/ppt-master.md). |
| `infographic` / AntV | Declarative `InfographicIR`, pinned SSR adapter, SVG structural/text QA, deterministic fallback | Complete template registry, NTRO design tokens, streaming preview, and browser visual regression before promotion. AntV themes/layers are not proof that PPT palette/layer constraints survived export. See [ledger](reference-adaptations/antv-infographic.md). |
| `diagram-design` | Semantic diagram registry, editorial/static-first output, safe HTML/SVG export, bounded imports, accessibility checks | Expand the semantic family and visual regression fixtures; optional motion remains opt-in and cannot change the static default. The reference is a skill/static-output pack, not a DAG scheduler. See [ledger](reference-adaptations/diagram-design.md). |
| `linkedin-skills` | Draft-only LinkedIn skill, humanizer boundary, approval/publish policy, typed child-plan support | Complete reviewed tone/humanizer evaluations and keep publish disabled unless an explicit approval/publish connector is configured. See [ledger](reference-adaptations/linkedin-skills.md). |

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

## Portable pipeline-agent boundary

Harness is one client of the Sudarshan orchestrator, not the home of the
pipeline implementations. The existing `SkillManifest`, `ChildTaskSpec`,
`SkillResult`, and artifact/quality contracts are the portable boundary for
local or remote execution. The target scale-out shape is:

```text
Sudarshan Orchestrator Agent
  -> Presentation Agent
       -> Infographic Agent or Diagram Agent
  -> Video Agent
  -> LinkedIn Agent
  -> Advisory Agent
```

The orchestrator mediates scope, budget, dependency, idempotency,
cancellation, and artifact lineage. A child may execute through the current
local adapter or through an A2A agent card without changing the parent task
contract. Other systems can call the same A2A agents without loading Harness.
Per-pipeline cards and the local-vs-A2A adapter are still release work; the
current A2A surface is the global run/status/cancel boundary.

The trajectory improvement is additive: emit the same run, child, dependency,
artifact, quality, retry, and usage lifecycle to a governed Harness trajectory
projection. The durable Sudarshan DAG remains the execution authority.

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
5. Add per-pipeline A2A cards, local-vs-remote child dispatch, mediated
   cross-agent handoffs, and a shared local/remote lifecycle event bridge.
6. Add package-manifest/license checks for any future copied reference asset.

The implementation is therefore reference-informed and portable, but not a
full copy of any reference system. The strongest production gaps are live
Cloud validation, browser E2E evidence, and visual-quality promotion—not a
missing orchestration framework.
