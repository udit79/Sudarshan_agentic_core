# Sudarshan next execution plan

**Status:** audit-derived plan, 2026-09-17
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
NP-13 fail-closed memory scope and case grounding
  ├─ NP-14 artifact ownership and case authorization
  ├─ NP-15 explicit user preferences and typed visual style
  │   └─ NP-19 consented preference feedback learning
  ├─ NP-16 stale-data lifecycle and source supersession
  ├─ NP-17 large-source resource controls
  └─ NP-18 artifact failure recovery
NP-12 evaluation and release gates (after NP-01–NP-18)
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

### NP-13 — Fail-closed memory scope and case grounding

**Owner:** memory/backend/security | **Priority:** P0 | **Depends on:** NP-04 and NP-10

The platform currently has User/Case/Task scope rules, but a memory result
without scope metadata can be accepted when the backend is assumed to have
applied its node filter. This ticket turns the claimed isolation boundary into
an explicit, testable contract for every pipeline, including Presentation.

**Implementation update (2026-09-17):** `MemoryManager` now rejects provider
results lacking explicit scope metadata, including results that only appear
inside an allowed Cognee node set. Focused regression coverage is present.
The graph and preparation boundary also validate ContextPack scope and every
serialized record before use. Provider-failure blocking remains a release
test for the complete ticket.

**Acceptance criteria**

- Every generation and ingestion request has an authenticated `user_id` and
  `case_id`; task scope is accepted only when it belongs to that case.
- A recalled result without verifiable scope metadata is rejected, except for
  an explicitly typed and verified system record.
- `ContextPack.scope`, every record, and the request context agree on User,
  Case, and Task identity before a pipeline starts.
- Cross-case identical queries and same-named sources never enter the current
  case context, cache, prompt, or task memory.
- Presentation tests prove that its output memory and evidence references are
  bound to the requested case, not merely to the run ID.
- A Cognee/node-filter failure produces a blocked or failed run; it cannot
  silently widen retrieval.

### NP-14 — Artifact ownership and case authorization

**Owner:** artifacts/backend/security | **Priority:** P0 | **Depends on:** NP-08 and NP-13

Generated artifacts currently carry run and classification metadata, while
artifact retrieval checks classification but does not consistently enforce the
owning User/Case/Task. Add the same authorization strength used by evidence
and source objects.

**Implementation update (2026-09-17):** New `ArtifactManifest` registrations
carry User/Case/Task ownership; object-store copies receive the same scope;
manifest, preview, download, run-artifact, and MCP retrieval paths enforce the
tuple. New registrations reject missing or partial ownership, and unowned
legacy sidecars are denied by the API/MCP boundary and must be inventoried and
quarantined or removed before release.

**Acceptance criteria**

- Artifact manifests and durable object metadata carry authenticated owner,
  case, task, and run lineage, or resolve them through an authorized durable
  run record.
- Manifest, preview, download, and run-artifact routes require matching
  operator/user/case scope before returning artifact metadata or bytes.
- A caller from another case cannot retrieve an artifact even when it knows
  the artifact ID and has sufficient classification clearance.
- Artifact IDs, quality reports, evidence IDs, and source hashes remain
  immutable and case-bound.
- Cross-case HTTP/MCP tests cover manifest, preview, download, and artifact
  retrieval by run.

### NP-15 — Explicit user preferences and typed visual style

**Owner:** request preparation/memory/PPT | **Priority:** P1 | **Depends on:** NP-04, NP-05, and NP-13

Natural-language statements such as “I like pink” are not currently converted
into a durable preference or a deterministic PPT theme. Add an explicit,
bounded preference path without treating every mention of a color as a saved
instruction.

**Acceptance criteria**

- A confirmed preference operation stores a versioned User-scoped profile with
  provenance and lifecycle metadata; ordinary case facts do not become style
  preferences.
- The user can view a bounded list of saved preferences showing the category,
  normalized value, version, scope, source, and last-updated time; raw memory
  graph content is never shown.
- The user can explicitly update or revoke a preference, and revocation takes
  effect for all future preparations without rewriting historical artifacts.
- Preparation may propose a preference from natural language, but only a
  confirmed typed value is persisted.
- Supported color names normalize through a fixed allow-list to canonical hex
  tokens; unsupported or ambiguous colors require clarification.
- A confirmed preference is injected as style guidance only and never as case
  evidence or a factual claim.
- Presentation rendering and post-render inspection prove that the selected
  palette reaches actual PPT objects and does not leak across users or cases.
- The MCP/API surface exposes one read operation for the current user's
  preferences and one explicit idempotent write/revoke operation; neither
  accepts arbitrary memory queries or another user's `user_id`.

### NP-16 — Stale-data lifecycle and source supersession

**Owner:** ingestion/data/memory | **Priority:** P0 | **Depends on:** NP-10 and NP-13

Parser-cache expiry exists, but durable evidence summaries do not consistently
expire or supersede older versions when a source changes. Make freshness an
explicit part of case evidence rather than relying on retrieval ranking.

**Implementation update (2026-09-17):** `EvidenceIndex` now maintains a
scope-bound logical source identity and version ledger, atomically replaces
prior indexed rows for a revised source reference, and uses the same identity
for its projected memory summary so re-ingestion does not create a second
active summary. Scheduler-owned local expiry runs at execution boundaries, and
remote records with expired or malformed expiry metadata are rejected during
recall. Live worker scheduling and remote-Cognee lifecycle verification remain
deployment gates.

**Acceptance criteria**

- Every indexed source has a stable identity based on authenticated scope and
  source hash; identical re-ingestion is idempotent.
- A changed source creates a new version and marks the prior evidence and
  projected memory as superseded or stale for that same case.
- Recall excludes expired, superseded, retracted, and unreviewed records by
  default, including records returned by Cognee without local cache state.
- A scheduled or worker-owned lifecycle pass applies expiry and records safe
  audit events; cleanup is not test-only.
- Tests prove that old case content cannot reappear after replacement and that
  another case’s source version is never considered a replacement.

### NP-17 — Large-source resource controls

**Owner:** ingestion/runtime/operations | **Priority:** P1 | **Depends on:** NP-10

The 50 MiB admission limit and stage budgets are real, but extraction and
parser-cache payloads can still hold large raw text and evidence structures in
memory. Bound post-admission resource use before increasing file limits.

**Acceptance criteria**

- Extraction enforces configured decompressed bytes, extracted characters,
  chunk count, temporary-disk, and wall-time limits per ingestion.
- Text and archive processing does not require retaining an unbounded full raw
  document in process memory or the stage cache.
- Cancellation and budget exhaustion leave no orphaned staged source or
  partially committed evidence/index state.
- Oversized-but-admitted sources return a visible partial/blocked status with
  a safe reason and no misleading successful artifact.
- Tests cover the 50 MiB boundary, archive expansion, extracted-text limits,
  cache cleanup, cancellation, and concurrent large ingestions.

### NP-18 — User-facing artifact failure recovery

**Owner:** pipeline/release/frontend | **Priority:** P1 | **Depends on:** NP-05, NP-07, NP-09, and NP-14

Quality gates correctly block invalid artifacts, but a failed run does not
always provide a usable next action or an explicit safe preview. Improve the
delivery contract without promoting degraded or failed output as successful.

**Acceptance criteria**

- Every artifact failure returns a stable issue code, quality report reference,
  safe explanation, and next action such as repair, retry, clarification, or
  download of an explicitly labelled draft.
- Automatic repair is bounded by the run attempt and budget policy; it cannot
  loop or create duplicate artifacts.
- Draft previews are clearly marked as failed/degraded and never enter durable
  Case memory as approved output.
- If no valid artifact exists, the UI/MCP response remains actionable and
  includes progress, failure state, and retry/revision guidance.
- Failure-injection tests cover renderer failure, child failure, quality
  rejection, timeout, and partial delivery for every artifact pipeline.

### NP-19 — Consented preference feedback learning

**Owner:** preference/memory/product  | **Priority:** P1 | **Depends on:** NP-15

The current system does not monitor user feedback or update preferences. This
ticket adds a controlled learning loop without silently profiling users or
turning case-specific edits into global preferences.

**Acceptance criteria**

- Explicit signals such as “I dislike pink,” a thumbs-down reason, or “always
  use dark themes” create a typed preference candidate tied to the
  authenticated user and the originating run/case.
- Repeated implicit signals such as manual revisions, rejected colors, or
  repeated retries may create a bounded suggestion, but never directly change
  the saved User Profile.
- Auto-learning is disabled by default and can be enabled only through an
  explicit user setting with a visible explanation of what signals are used.
- Before an inferred preference is saved, the user can accept, reject, edit,
  or dismiss the suggestion; every decision is auditable and reversible.
- Case/task feedback remains local to that case/task unless the user confirms
  promotion to a global User Profile preference.
- Silence, abandonment, one-off edits, and successful delivery without
  feedback are never treated as a dislike or preference update.
- Preference candidates and saved preferences are bounded, user-authorized,
  and excluded from evidence, factual case memory, provider prompts, and
  trajectory output unless the user explicitly asks to see them.
- Tests cover explicit like/dislike feedback, repeated edits, opt-in and
  opt-out behavior, cross-user isolation, case-to-user promotion, revocation,
  and duplicate feedback events.

### NP-12 — Evaluation and release gate

**Owner:** evaluation/release/security  
**Priority:** P0  
**Depends on:** NP-01 through NP-19

Run the authoritative regression matrix before calling any ticket complete.

Required cases: duplicate admission, timeout with late provider result, stale
lease, exact two-page PPT, one-slide revision, custom colors/layers, native
AntV timeout, fallback rejection, public DAG after restart, parallel trajectory
lanes, usage deduplication, memory scope, partial ingestion, and local/remote
A2A parity.

**Release gate**

- Release is permitted only when no known P0 remains open.
- NP-13, NP-14, and NP-16 are known P0 memory/data-integrity gates and
  must be closed before the repository can claim complete User/Case/Task
  isolation.
- Full repository suite passes without hidden fallback success.
- Every ticket has source evidence, focused tests, and a verified status.
- Reference repositories remain unchanged.

## Immediate execution sequence

1. NP-01: stop duplicate side effects before enabling more retries.
2. NP-02 and NP-03: make trajectory and token accounting trustworthy.
3. NP-05, NP-06, and NP-07: enforce artifact correctness.
4. NP-08: expose the real DAG and child state.
5. NP-13 and NP-14: close the case-memory and artifact authorization gaps.
6. NP-16: make stale-data handling explicit and automatic.
7. NP-04, NP-09, NP-10, NP-15, NP-17, NP-18, and NP-19: close remaining memory,
   pipeline, ingestion, preference, resource, and recovery gaps.
8. NP-11: promote portable MCP/A2A boundaries.
9. NP-12: run the release matrix and update status from evidence.

