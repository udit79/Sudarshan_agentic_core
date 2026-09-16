# Sudarshan next execution plan

**Status:** audit-derived plan, 2026-09-16  
**Scope:** reliability, artifact correctness, memory, MCP/A2A portability, and
DeepSeek Harness trajectory integration.  
**Authority:** current source and tests; reference repositories remain design
inputs only.

The former T39–T90 backlog is archived at
[`docs/archive/sudarshan-2.0-remaining-work-plan-legacy-2026-09-16.md`](archive/sudarshan-2.0-remaining-work-plan-legacy-2026-09-16.md).
This plan replaces its stale active tickets. No ticket below claims that the
target is already implemented.

## Rules for every ticket

1. Sudarshan remains the scheduler, authorization, memory, budget, artifact,
   and quality authority. Harness, MCP, A2A, and provider SDKs are adapters.
2. Prompts may guide behavior; typed contracts and deterministic post-generation
   checks enforce behavior.
3. Local and remote children use the same typed envelope, lineage, budget,
   cancellation, artifact, quality, and usage receipts.
4. Every retry, fallback, partial result, cache decision, and uncertain provider
   outcome is visible and never silently promoted to success.
5. Each ticket needs a focused regression test and must not modify a reference
   repository.

## Priority order

```text
NP-01 execution identity/reconciliation
  ├─ NP-02 event and trajectory contract
  ├─ NP-03 usage reconciliation
  └─ NP-08 public DAG and child state
NP-04 request preparation and case memory
  └─ NP-05 deterministic artifact constraints
      ├─ NP-06 incremental PPT editing
      └─ NP-07 visual renderer promotion
NP-09 pipeline-specific release correctness
NP-10 governed ingestion and evidence memory
NP-11 MCP/A2A capability surface
NP-12 evaluation and release gates
```

## Tickets

### NP-01 — Execution identity, timeout, and reconciliation

**Owner:** backend/platform  
**Priority:** P0  
**Depends on:** current scheduler and control-plane contracts

Separate `request_fingerprint`, logical `run_id`, `attempt_id`, lease/fencing
token, and `provider_request_id`. Propagate cancellation from gateway/Harness
through scheduler, orchestrator, child runtime, and provider adapters.

**Acceptance criteria**

- Repeating the same admission request returns one logical run.
- Every worker execution receives a new durable `attempt_id`.
- A timed-out non-killable attempt becomes `uncertain`/`provider_pending` and
  is not blindly retried while it may still be alive.
- A stale or late attempt cannot write a terminal result, artifact, memory
  record, or external side effect after fencing.
- Gateway retries preserve the idempotency key and do not create another task.
- A failure-injection test proves that a late first attempt cannot overlap a
  side-effecting retry.

### NP-02 — Canonical event and Harness trajectory projection

**Owner:** backend/operations/Harness  
**Priority:** P0  
**Depends on:** NP-01

**Implementation status (2026-09-16):** Safe progress and observability events
are persisted locally/shared through the control-plane projection, and
`get_sudarshan_trajectory` plus `GET /runs/{run_id}/trajectory` expose a
redacted timeline with parallel-lane summaries. Direct wiring into an external
Harness trajectory UI/plugin and distributed event reconciliation remain
environment/deployment work; the durable DAG is still authoritative.

Define one redacted event contract for progress, observability, DAG, MCP, A2A,
and Harness trajectory. Add `source_sequence`, `node_id`, `parent_node_id`,
`child_id`, `attempt_id`, `lane_id`, `cache_status`, `fallback`, `artifact_id`,
`quality_report_id`, `provider_request_id`, and `usage_id` where applicable.

**Acceptance criteria**

- Harness receives trajectory rows from the Sudarshan event stream, not from
  model-generated tool narration.
- `(run_id, source_sequence)` or an equivalent event key deduplicates replay.
- Parallel child work renders as separate lanes with dependency state.
- Prompts, raw memory, provider payloads, credentials, and hidden reasoning are
  excluded.
- The durable scheduler/DAG remains authoritative if Harness is disconnected.

### NP-03 — Usage and token-counter reconciliation

**Owner:** backend/platform  
**Priority:** P0  
**Depends on:** NP-01 and NP-02

Make provider receipts, estimates, retries, cache reads/writes, orchestration
cost, and duplicate attempts distinguishable. Aggregate by unique `usage_id`
so runtime and progress projections cannot double-count one receipt.

**Acceptance criteria**

- `get_sudarshan_usage` exposes logical-run, attempt, provider, estimated, and
  reconciled counters separately.
- Provider usage is authoritative only when a provider receipt exists.
- Duplicate event projection does not increase token totals.
- Harness trajectory and Sudarshan telemetry show the same totals.

### NP-04 — Typed request preparation and bounded case memory

**Owner:** agentic/memory/backend  
**Priority:** P0  
**Depends on:** NP-01

Let DeepSeek interpret conversational wording and propose a typed request, but
keep Python validation and authorization authoritative. Replace the separate
request-understanding *agent* only by making request understanding a persisted,
validated phase. Use one bounded, redacted, provenance-bearing `ContextPack`.

**Acceptance criteria**

- Preparation returns an opaque server-held ID bound to user, case, task, and
  request fingerprint.
- Context is bounded, confidence-scored, evidence-linked, and redacted.
- The same memory is not recalled and injected twice through separate paths.
- Backend rejects unauthorized pipelines, changed case scope, invalid
  classification, and impossible output constraints.
- Rejected or unapproved output cannot become durable case FACT memory.

### NP-05 — Deterministic artifact-constraint contract

**Owner:** agentic/rendering  
**Priority:** P0  
**Depends on:** NP-04

**Implementation status (2026-09-16):** P0 enforcement slice implemented for
the native PPT path. `page_count` normalizes to total `slide_count`, request
constraints survive orchestrator/flow round-trips, themes are applied to
native PPT objects, and the emitted PPTX is reopened for deterministic color,
font, overflow, editability, z-order, and slide-count checks. A checked-in
visual-contract fixture protects the native layout signature. Rasterized
PowerPoint/LibreOffice smoke tests remain a separate environment-dependent
promotion step.

Normalize user constraints into typed fields before generation: total pages,
content pages, colors, theme, layers, output format, required diagram, and
revision scope.

**Acceptance criteria**

- “Exactly 2 pages” renders exactly two total pages.
- “2 content slides” has explicitly different semantics.
- Colors, layers, required visual outputs, and evidence links are validated
  after rendering.
- Prompt-only claims cannot mark an invalid artifact successful.
- Repair or blocked delivery is returned with machine-readable issue IDs.

### NP-06 — Incremental PPT and PPT Master round-trip

**Owner:** PPT/rendering  
**Priority:** P0  
**Depends on:** NP-05

**Implementation status (2026-09-16):** The native path records per-slide
source and rendered-part hashes, preserves and checks untouched slide XML,
marks downstream dependents as `invalidated` until explicitly regenerated,
validates template/master contracts, and enforces the post-render gate. The
PPT Master adapter only performs a local subprocess export and PPTX read-back
when a user-managed checkout is configured. PPT Master is not hosted,
installed, or downloaded by Sudarshan; set `SUDARSHAN_PPT_MASTER_ROOT` after
self-hosting/installing it. Without that configuration, native rendering is
the only available PPT path.

Use stable `slide_id`s, per-slide artifacts, dependency hashes, and a deck
manifest. Update only the requested slide and preserve untouched slide hashes,
notes, theme, and editable layers. Keep the PPT Master bridge optional and
local; it must never become a second orchestrator or an assumed hosted
provider.

**Acceptance criteria**

- One-slide revision does not rebuild or alter unrelated slides.
- Slide dependencies invalidate only affected child artifacts.
- Custom theme tokens reach SVG/PPTX and survive round-trip inspection.
- Untouched-slide hash and layout tests pass.

### NP-07 — AntV, diagram, and visual fallback promotion

**Owner:** rendering/platform  
**Priority:** P0  
**Depends on:** NP-02 and NP-05

Fix nested Python/Node deadlines by reserving shutdown headroom. Distinguish
native AntV, deterministic preview fallback, syntax-only output, and failure.
Unify diagram/infographic semantic IR adapters and register diagram capability
explicitly where it is intended to be callable.

**Acceptance criteria**

- Native renderer timeout leaves enough time for controlled fallback and
  process shutdown.
- Native versus fallback mode is asserted by tests; fallback is not silently
  promoted as native quality.
- Fallback SVG passes the same safe-export rules and cannot use rejected
  `foreignObject` content.
- Theme/palette/layer/accessibility tokens survive rendering.
- The full suite passes `test_json_renderer_contracts.py` without relying on an
  unasserted fallback.

### NP-08 — Public DAG and child-state projection

**Owner:** backend/orchestrator  
**Priority:** P0  
**Depends on:** NP-01 and NP-02

Expose the actual durable DAG for the normal run path, not only the PPT
vertical slice. Return nodes, edges, dependencies, attempts, repairs, output
references, quality state, and failure details through status and/or a graph
endpoint plus a safe MCP read operation.

**Acceptance criteria**

- Queued, running, partial, failed, completed, and restarted runs expose the
  same graph contract.
- Local and remote child execution produce the same graph/event shape.
- A disconnected Harness cannot erase or become the source of DAG state.

### NP-09 — Pipeline release correctness

**Owner:** pipeline teams  
**Priority:** P1  
**Depends on:** NP-05, NP-07, and NP-08

Close the pipeline-specific gaps found in the staged audit:

- Advisory/executive summary: deterministic evidence IDs, linkage, claim
  coverage, and approval-aware memory writes.
- LinkedIn: valid evidence bindings, deterministic humanizer release checks,
  and `provider_pending` publication reconciliation.
- Video: provider submit/status/reconcile/cancel, attempt-scoped scene cache,
  and explicit partial/degraded release state.
- Infographic/diagram: structural, accessibility, palette, layer, and native
  renderer checks before success.

#### MiniMax-H3 boundary: reference only, no new adapter

MiniMax-H3 is not hosted by this project. Running it would require a separate
GPU/model-serving deployment, so adding an H3-specific provider adapter now
would create another unsupported integration layer—the same overengineering
pattern this plan is intended to remove.

We therefore adopt **no MiniMax-H3 provider** in this implementation plan.
We retain only provider-neutral lessons in the existing video pipeline:

- provider jobs need durable status/reconciliation rather than blind resubmits;
- scene output needs explicit media validation and artifact checksums;
- audio ownership must be explicit so TTS and generated audio are not silently
  duplicated;
- higher-quality regeneration, if a future hosted provider actually exists,
  must be a typed dependent artifact stage rather than a hidden fallback;
- prompts and shot plans should receive bounded authorized context.

We are not adopting H3 weights, H3 mode fields, Hub canvas workflows, H3
memory, H3 scheduling, or an H3-specific adapter. If a real hosted provider is
selected later, it must first satisfy the existing generic provider contract;
that future decision is out of scope for NP-09.

**Acceptance criteria**

- Each pipeline has a failure-injection test for provider, cache, fallback,
  quality, and memory-release behavior.
- Degraded output is explicitly partial or blocked, never successful-looking.

### NP-10 — Governed ingestion and evidence memory

**Owner:** ingestion/data/memory  
**Priority:** P1  
**Depends on:** NP-04 and NP-08

Make asynchronous governed ingestion the production path. Restrict or clearly
label direct `ingest_file()` as test/local-only. Preserve partial extraction as
partial evidence and prevent unreviewed placeholder content from becoming a
durable FACT.

**Acceptance criteria**

- Source safety, budgets, leases, cache fingerprints, provenance, and quality
  receipts apply to every production ingestion.
- Partial/OCR/Whisper/VLM failures remain visible in evidence and memory state.
- Evidence search returns bounded provenance and authorization metadata.

### NP-11 — MCP profiles and portable A2A handoff

**Owner:** Harness/agentic/platform  
**Priority:** P1  
**Depends on:** NP-01, NP-02, and NP-08

Make `start_sudarshan_run` the canonical model-facing admission operation;
keep compatibility operations separate. Add typed response models and role
profiles. Derive lineage server-side. Add per-pipeline A2A cards only for
independently deployable agents, while preserving one authoritative
orchestrator.

**Acceptance criteria**

- A model cannot create duplicate work by choosing between overlapping start
  tools after a timeout.
- Child envelopes are identical for local and remote execution.
- Independent Presentation → Infographic/Diagram handoffs preserve budgets,
  evidence, attempts, artifacts, quality, cancellation, and reconciliation.
- Tool-selection evaluations cover create, revise-one-slide, wait, resume,
  approve, cancel, and artifact retrieval.

### NP-12 — Evaluation and release gate

**Owner:** evaluation/release/security  
**Priority:** P0  
**Depends on:** NP-01 through NP-11

Run the authoritative regression matrix before calling any ticket complete.

Required cases: duplicate admission, timeout with late provider result, stale
lease, exact two-page PPT, one-slide revision, custom colors/layers, native
AntV timeout, fallback rejection, public DAG after restart, parallel trajectory
lanes, usage deduplication, memory scope, partial ingestion, and local/remote
A2A parity.

**Release gate**

- No known P0 remains open.
- Full repository suite passes without hidden fallback success.
- Every ticket has source evidence, focused tests, and a verified status.
- Reference repositories remain unchanged.

## Immediate execution sequence

1. NP-01: stop duplicate side effects before enabling more retries.
2. NP-02 and NP-03: make trajectory and token accounting trustworthy.
3. NP-05, NP-06, and NP-07: enforce artifact correctness.
4. NP-08: expose the real DAG and child state.
5. NP-04, NP-09, and NP-10: close memory and pipeline release gaps.
6. NP-11: promote portable MCP/A2A boundaries.
7. NP-12: run the release matrix and update status from evidence.

