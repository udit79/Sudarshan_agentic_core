# Sudarshan 2.0 frontend/backend feature matrix

Updated: 2026-09-11

This document translates the active execution tickets into parallel work for
the backend/platform and frontend teams. It is an implementation contract, not
a product wish list. “Complete locally” means the repository has a tested
slice; it does not mean staging or production promotion is complete.

## Non-negotiable boundary

The frontend is an authenticated operator client. It may render safe
projections, preview authorized artifacts, collect user decisions, and submit
commands. It must not call Cognee, CrewAI, model providers, provider SDKs,
skill internals, or the DeepSeek Harness directly.

The backend is the source of truth for identity, case ownership,
classification, evidence scope, routing, memory, budgets, scheduling,
cancellation, quality gates, artifact manifests, audit, MCP, and A2A. Native
Harness and ordinary MCP clients must join the same application boundary.

The frontend must never display raw prompts, raw memory, credentials, hidden
reasoning, unrestricted provider payloads, or unredacted source content.

## Status vocabulary

| Status | Meaning |
|---|---|
| Complete locally | Code and local tests exist; deployment or external evidence may remain |
| Partial/local slice | The contract or a vertical slice exists; the full ticket is not closed |
| Open | Planned work remains |
| Release gate | Implementation exists but promotion requires staging, benchmark, security, or human evidence |

## Existing baseline before remaining work

### Backend/platform already provides

- FastAPI application boundary with health, pipeline discovery, ingestion,
  asynchronous ingestion status/cancel, run submission/status/wait/resume/
  cancel, SSE events, telemetry, and authorized artifact manifest/download/
  preview routes.
- Node gateway with authentication, user-owned cases, quotas, idempotent
  transformation submission, task history, task refresh, SSE projection,
  artifact routes, and FastAPI fallback for local development.
- LangGraph request understanding/routing, CrewAI specialist pipelines,
  `SkillRuntime`, typed child plans, cancellation, budgets, cache, memory and
  quality projections.
- SQLite local control plane plus optional Redis control-plane seams,
  object-store contracts, artifact checksums/manifests, ingestion queues,
  usage receipts, safe observability, and MCP/A2A adapters.
- Native PPT, infographic, diagram, and video renderers with typed artifacts;
  PPT Master, AntV, and Diagram Design integrations remain governed native or
  optional boundaries.

### Frontend already provides

- Google OAuth gateway entry, authenticated case selection/creation, bounded
  file attachments, output-card selection, transformation submission, and
  session-only API-key setup for local development.
- Gateway/FastAPI mode detection, one-refresh retry, request errors, identity
  headers, idempotency keys, SSE progress subscription, event-cursor
  persistence, reconnect projection, and task history hydration.
- Progress bar, stage/status/quality/child/token/latency/cache/wait cards,
  waiting notices, cancellation, output tabs, safe result rendering, artifact
  preview/download, and recent-task history.

### Known frontend gaps

The current UI does not yet provide a complete parent/child execution DAG,
deep evidence drawer, interactive visual repair/editor workspace, durable
approval inbox, audit-log explorer, benchmark view, renderer promotion view,
or complete LinkedIn workspace. These are explicit ticket deliverables below.

## Ticket ownership matrix

### Platform, storage, control plane, and release tickets

| Ticket | Status | Backend/platform deliverables | Frontend deliverables | Shared acceptance |
|---|---|---|---|---|
| T39 | Complete locally; release gate | Shared queue/DAG leases, fencing, retries, idempotency, Redis/SQLite adapters, cursor ordering, restart recovery | Reconnect using opaque run/task IDs and last event cursor; show queued/capacity/retry states | No duplicate execution; stale workers cannot write; reconnect has no duplicate events |
| T40 | Complete locally; release gate | Opaque source/evidence/artifact IDs, checksums, object-store adapters, lineage, classification/scope checks | Use manifest/preview/download URIs only; show provenance and access errors | Restart-safe artifact resolution; unauthorized preview/download blocked |
| T41 | Complete locally; release gate | Atomic parent/child token, tool, wall-time, fan-out, concurrency reservations and usage receipts | Show safe aggregate usage, estimates, cache savings, and budget exhaustion; never show secrets | Parent/child accounting reconciles and concurrent workers cannot overspend |
| T42 | Complete locally; release gate | Hash-chained audit, safe dashboard projection, telemetry aggregation, redaction, retention/export | Run timeline, safe operator log, filters by stage/skill/status, restricted-detail affordance | Queue wait, provider wait, worker time, retries, cache, quality, and delivery are queryable |
| T43 | Partial/local slice; release gate | Dry-run and lineage-aware cleanup for leases, staging, previews, caches, and artifacts | Show cleanup/deletion state only as safe summaries; never expose filesystem paths | Failed/cancelled cleanup is repeatable and active lineage is preserved |
| T44 | Partial/local slice; release gate | Provider-neutral receipts for model, request ID, tokens, media units, latency, retry-after, estimates, and reconciliation | Display estimated/observed/reconciled cost separately with provider-neutral labels | Missing provider usage is explicitly estimated; invoice reconciliation is auditable |
| T45 | Partial/local slice | Publish parent/child status, wait reasons, telemetry, evidence references, artifact and quality projections | Full execution monitor, child lanes, wait reasons, evidence drawer, artifact cards, refresh/reconnect | Same monitor works for native Harness, gateway, and MCP-created runs |
| T46 | Partial/local slice; release gate | Object-backed ingestion, durable manifests, typed evidence/chunks/relationships, bounded modality fan-out, OCR/VLM policy | Upload progress, ingestion stage view, quality/partial state, retry/cancel/resume, source receipt | Restart resumes without reparsing; duplicate source/policy identity is idempotent |
| T47 | Partial/local slice; benchmark gate | Report archive schema and promotion metrics exist; full cross-artifact runner/corpus remains | Benchmark dashboard with per-artifact thresholds, tokens, cost, latency, cache, repair, and human correction | Promotion is blocked on quality, security, or cost threshold failure |
| T48 | Partial/local slice; release gate | Signed manifests, package hashes, trust tiers, dependency/capability grants, OS/container sandbox, resource limits | Skill install/verification state, trust warnings, denied-capability messages, no secret detail | Unsigned/tampered skills cannot execute; failures are typed and auditable |
| T49 | Partial/local slice; interoperability gate | MCP/A2A lifecycle parity, agent card, submit/status/wait/cancel/resume, policy and artifact propagation | External-run status and approval UI uses the same projection as native runs | External clients cannot bypass policy, budget, memory, quality, or cancellation |
| T50 | Partial/local slice; quality gate | Shared SVG/raster/PDF/PPTX/video integrity checks, renderer versions, QA reports, visual snapshots | Quality report panel, preview comparison, degraded/fallback badge, human approve/reject dialog | Off-canvas, overlap, overflow, unreadable text, missing media, and broken lineage fail |
| T51 | Partial/local slice | Typed child-task DAG, dependencies, budgets, fallback reconciliation, parent lineage, planner wiring | Child graph, dependency waits, optional/required child outcome, orphan detection | Independent children parallelize; failed optional children degrade explicitly |
| T52 | Partial/local slice; release gate | Release preflight, migration, backup/restore, rollback, health checks, runbooks, owner sign-off | Release readiness dashboard, failed-gate checklist, approval/sign-off record | End-to-end demo proves planning, parallel work, wait, repair, delivery, and safe logs |
| T53 | Complete locally; release gate | Capability-aware provider/model router, quota/rate-limit/auth classification, cooldown, degradation metadata | Provider health/capability display, explicit degraded output explanation, retry guidance | No retry storm; unavailable image/TTS quota produces a truthful fallback |

### Memory, skill, renderer, and lifecycle tickets

| Ticket | Status | Backend/platform deliverables | Frontend deliverables | Shared acceptance |
|---|---|---|---|---|
| T54 | Complete locally; release gate | L0/L1/L2 context selection, stage policy, token accounting, context references | Show context depth and safe source references, not raw memory | Token/quality trade-off measured on reviewed multimodal data |
| T55 | Complete locally; release gate | Lazy bounded skill/resource loading, allow-lists, package limits, cache identity | Skill/resource load state and bounded failure display | No skill can load unbounded instructions or cross case scope |
| T56 | Complete locally; release gate | Renderer capability registry, versions, fallbacks, promotion metadata | Renderer/version/fallback badge and comparison view | Degraded renderer is visible and never silently equivalent |
| T57 | Complete locally; release gate | Semantic diagram family contract and self-checker | Diagram type chooser and diagnostics view | Reviewed examples cover each enabled type and accessibility checks pass |
| T58 | Complete locally; release gate | Typed slide jobs, shared layout source, targeted PPT repair and quality workflow | Slide lane view, repair suggestions, slide-level accept/reject, rerender action | Editable PPTX and preview share layout; targeted repair avoids full regeneration |
| T59 | Complete locally; release gate | Provider-neutral video timeline, asset ledger, fingerprints, object-backed resume | Scene/media/timeline view, material provenance, missing-media and partial states | Long-video/codec/object-store resume tests pass |
| T60 | Complete locally; release gate | Memory lifecycle events, lessons, evaluation report and retention projection | Safe memory/evaluation summary and operator correction action | Reviewed benchmark connects lifecycle events to retention and quality |
| T61 | Complete locally | Versioned LinkedIn post/comment/reply/reshare/humanizer manifests, schemas, policies, failure cases | Skill/action selector shows draft versus write risk and contract | Draft skills cannot access external writes |
| T62 | Complete locally | Deterministic humanizer V2 findings with rule IDs, locations, severity, repair advice | Humanizer findings panel with explainable suggestions; no detector claims | Clean drafts are not rewritten without a finding |
| T63 | Complete locally | Provider-neutral social read/write adapter, receipts, scopes, timeout, cancellation, audit | Connector setup/status and manual-mode state; never collect provider secrets in skill UI | No skill imports provider SDK or bypasses approval/scheduler |
| T64 | Complete locally | LinkedIn provider/cache/timeout/retry/rate-limit configuration validation | Configuration status, missing-credential and draft fallback messaging | Startup validates shape without requiring credentials |
| T65 | Complete locally | Bounded post/comment/thread reads, scoped versioned cache, provenance, untrusted-content marking | Read/source drawer with freshness, scope, provenance, invalidation state | Retrieved text cannot change tools, targets, approval, or publication |
| T66 | Complete locally | Durable approval/resume/release, payload hash, actor, policy, idempotency, provider receipt | Approval inbox, diff, actor/policy display, approve/reject/resume states | No external write without an authorized approval event |
| T67 | Complete locally; release gate | LinkedIn child-plan execution and visual artifact/quality reconciliation | Parent/child status and visual child artifact in the post workspace | Child lineage is visible and failed visual child remains draft-only |
| T68 | Complete locally; benchmark gate | Offline LinkedIn end-to-end evaluation fixtures and reports | Evaluation result view and regression explanation | Grounding, humanizer, policy, and visual-child thresholds are archived |
| T69 | Complete locally; release gate | Semantic visual-child routing for infographic/diagram with typed fallback | Show why a visual child was selected and its quality state | Explicit intent routes correctly; fallback remains governed |
| T70 | Complete locally | Bounded voice-profile parsing and style-only application | Voice profile selection/edit with scope and provenance | Voice profile cannot create facts or publication authority |
| T71 | Complete locally | Comment/reply length, link, exclamation, parent-resolution policies | Inline policy warnings and repair suggestions | Top-level parent resolution and safe draft behavior are deterministic |
| T72 | Partial/local slice | Social boundary normalizes retry-after and classified provider receipts; durable retry/idempotency state machine remains | Retry-after/countdown, pending, rate-limit, duplicate, and cancellation states | Provider failures never become successful-looking publication |
| T73 | Partial/local slice | Durable timezone-aware schedule queue, approval gating, cancellation, due claims, provider-pending retry, and idempotent release; application/UI wiring remains | Calendar/scheduled item list, edit/cancel, pending/failed receipt | Same action cannot publish twice after restart |
| T74 | Complete locally | Backend projections for LinkedIn workspace, approvals, reads, comments, schedules | Full LinkedIn workspace: composer, humanizer, comments/replies, visual child, approvals | Existing post projection remains compatible |
| T75 | Partial/local slice | Opt-in durable read-only monitor with bounded polling, scope checks, pause/resume/cancel, retry-after handling, and non-actionable detection; suggestion workflow remains | Opt-in monitoring view with pause/stop and privacy scope | Monitoring has explicit budget, retention, and cancellation |
| T76 | Complete locally | Offline social provider test doubles and contract fixtures | Frontend integration tests run without provider credentials | Manual/draft mode and failure classes are testable offline |
| T77 | Complete locally; release gate | Non-blocking memory lifecycle hooks, scoped lessons, retention/error isolation | Safe lesson/correction confirmation; no raw memory exposure | Hook failure cannot fail the main run |
| T78 | Complete locally; release gate | Stable L0/L1/L2 context references with scope/source identity | Evidence/context links open only authorized projections | Context references survive retries and preserve source identity |
| T79 | Partial/local slice; release gate | Diagram self-checker for static safety, accessibility, geometry, density, and imports | Diagram diagnostics, repair action, and safe preview | Unsafe or inaccessible diagram cannot be promoted |
| T80 | Partial/local slice | Allow-listed infographic template/theme registry with explicit SVG/fallback modes; full design-token/export workflow remains | Template/theme selector, preview, contrast/density warnings | Templates cannot inject arbitrary code or unsupported claims |
| T81 | Complete locally; release gate | Video asset fingerprint cache with renderer/options/provenance scope | Cache hit/miss and material reuse information | Cache reuse never crosses authorization or renderer identity |
| T82 | Partial/local slice | Bounded fail-closed PPT repair patch contracts/applicator; visual QA integration and rerender loop remain | Issue list, patch preview, apply/reject, slide rerender | Repair is targeted and evidence-preserving |
| T83 | Complete locally; release gate | Reference provenance/license ledger and release attribution | Optional reference/version display for operators and release docs | No adapted reference is shipped without ledger/license review |

### Video, PPT Master, infographic, and Diagram Design tracks

| Ticket range | Status | Backend/platform deliverables | Frontend deliverables | Shared acceptance |
|---|---|---|---|---|
| V84–V95 | Complete locally; staging gates open | Governed media resolver, native scene rendering, subtitles/music/timeline contracts, FFmpeg QA, compatible adapter, provenance, cancellation, and benchmark artifacts | Scene progress, media provenance, quality/fallback state, preview, approval, and retry | Real codec/font/media, object-store, provider, host-loss, and human-visual evidence pass |
| PM-1–PM-2 | Complete locally | Optional PPT Master capability and bounded non-shell exporter with containment, timeout, cancellation, and required reports | Renderer capability/fallback badge; no default switch | Native renderer remains fallback; no external code copied |
| PM-3–PM-9 | Partial/local slices; release gates open | Typed evidence/source manifests, DeckPlan template/design/dependency contracts, canonical static SVG quality gate, dependency-aware slide jobs, and child-artifact reconciliation are local; external renderer consumption, visual promotion, MCP/A2A, rollback gates remain | Evidence-to-slide workspace and dependency metadata are typed locally; editor, slide lanes, visual diff, approval and rollback remain | PPT Master is enabled only after evidence, SVG/native quality, and promotion gates pass |
| IF-1–IF-3 | Complete locally | AntV adaptation ledger, pinned renderer version, cooperative cancellation, mandatory SVG quality gate | Infographic quality/fallback/version display | Invalid or text-missing SVG cannot be delivered as rendered output |
| IF-4–IF-9 | Partial/local slices; release gates open | Allow-listed template/theme contracts, typed structure compilers, fail-closed SVG export, optional explicit PNG converter boundary, and structural regression fixtures are local; PNG environment, browser visual regression, promotion, cache, and interoperability remain | Typed compiler/export boundary and live preview/event projection are local; full editor, quality diff, and approval remain | No arbitrary syntax/JS/remote asset escapes the boundary |
| DD-1–DD-2 | Complete locally | Adaptation ledger, accessible static SVG metadata, fail-closed safety checks in flowchart promotion | Accessibility/unsafe-output diagnostics and fallback state | Static SVG has title/description, labels, dimensions, and no executable/remote content |
| DD-3 | Complete locally; release gate | Allow-listed semantic type registry and deterministic type selection | Type chooser uses the same safe semantic registry | Unsupported diagram kinds do not become arbitrary renderer input; reviewed examples and human approval remain release evidence |
| DD-4–DD-9 | Partial/local slices; release gates open | Sanitized Mermaid/draw.io/Excalidraw adapters, initial style profile, static HTML/SVG export, structural checks, and isolated preview boundary are local; PNG, motion, visual regression, and approval remain | Basic safe import/export/preview boundaries are local; editor, PNG, motion, approval, and MCP/A2A remain | Static remains default; imported or animated content is sanitized and auditable |

## Frontend implementation backlog

The frontend team should implement these surfaces in this order:

1. **Contract client:** centralize run, ingestion, telemetry, event, artifact,
   approval, and error types in `frontend/api.js`; preserve gateway/FastAPI
   normalization and cursor replay.
2. **Execution monitor:** replace the current summary-only lane with a parent/
   child DAG view, dependency waits, queue/provider/approval waits, retries,
   budgets, cache, quality, renderer, and artifact lineage.
3. **Evidence drawer:** show only authorized evidence IDs, source reference,
   confidence, provenance, context level, and preview links.
4. **Artifact workspace:** tabs for PPT/infographic/diagram/video/LinkedIn,
   manifests, previews, quality reports, renderer version, degraded state,
   targeted repair, and human approval.
5. **Approval inbox:** clarification, visual approval, social approval,
   schedule approval, resume, reject, and cancel with payload/policy hashes.
6. **Ingestion workspace:** upload progress, typed modality stages, quality,
   partial results, cancellation, retry, and source-to-evidence lineage.
7. **LinkedIn workspace:** draft composer, humanizer, comments/replies,
   visual child, read cache, approval, scheduling, and provider state.
8. **Visual editors:** infographic templates/themes, diagram type/import/style
   profiles, PPT slide repair, and video scene/media inspection.
9. **Operations/release views:** audit-safe logs, benchmark reports, renderer
   promotion, skill trust/sandbox status, cleanup, rollback, and stop/go gates.

## Backend implementation backlog

The backend/platform team should implement these seams in this order:

1. Freeze the public projection schemas and event/status vocabulary.
2. Finish shared control-plane, object-store, budget, telemetry, retention,
   provider receipt, and ingestion release evidence: T39–T46.
3. Finish package trust/sandbox and independent MCP/A2A lifecycle parity:
   T48–T49.
4. Finish shared visual QA and typed child-plan wiring across every real PPT,
   LinkedIn, infographic, and video planner: T50–T51.
5. Finish model/provider capability routing and explicit degraded behavior:
   T53.
6. Finish social connector, read cache, approvals, retries, scheduling, and
   provider doubles: T63–T76.
7. Finish memory references/lifecycle and renderer-specific repair/template
   contracts: T77–T83, PM, IF, and DD open tickets.
8. Produce benchmark, backup/restore, rollback, security, and operating
   evidence for T47 and T52.

## Shared definition of done

Every frontend/backend ticket is complete only when:

- the request and response contract is versioned and fixture-tested;
- classification, case ownership, evidence scope, and authorization are
  enforced in the backend;
- long work returns a handle and exposes bounded wait, status, reconnect, and
  cooperative cancel;
- budgets, cache identity, renderer/provider version, quality, and lineage are
  visible in safe projections;
- optional work degrades with an explicit typed state and required work blocks
  delivery with an actionable error;
- raw prompts, memory, credentials, hidden reasoning, and unrestricted source
  content never enter frontend projections or safe logs;
- Python, Node, frontend, Harness, MCP, A2A, renderer, and failure-injection
  tests pass for the affected ticket;
- the ticket is marked complete in
  `docs/sudarshan-2.0-remaining-work-plan.md` and any new assumption is added
  to `docs/sudarshan-2.0-assumptions.md`.

## Current recommendation

Frontend can work immediately on T45 using the current projection APIs. Backend
should freeze T39–T42/T46 contract fixtures before frontend begins approval,
benchmark, or production renderer work. Do not make the frontend depend on
DeepSeek Harness-specific response shapes; the same UI projection must work for
native Harness, FastAPI, gateway, MCP, and A2A entry points.
