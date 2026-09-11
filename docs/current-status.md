# Sudarshan 2.0 current status

Status is measured against the implementation on the `Sudarshan2.0` branch,
after T28 reliability work. This document separates local capability from
production readiness so demos, judging material, and engineering work use the
same claims.

## Executive status

| Area | Current state | Honest claim |
| --- | --- | --- |
| Agentic control plane | Implemented locally | LangGraph owns routing and lifecycle; specialist pipelines and typed child skills run behind bounded contracts. |
| Harness/MCP boundary | Implemented locally | DeepSeek Harness and external MCP clients use the same Sudarshan application boundary. |
| Python backend | Strong local vertical slice | Ingestion, memory, routing, pipelines, quality gates, artifacts, scheduler, cache, telemetry, audit, and recovery are wired and tested locally. |
| Reference frontend | Functional dashboard | Authenticated gateway mode, case/source flow, run progress, cancellation, artifact preview/download, and safe telemetry are available. |
| Production deployment | Release-candidate code present; deployment gates open | T43–T52 code paths and local tests are present. Live Redis/object-storage, provider reconciliation, signed-sandbox drills, real-corpus benchmarks, external MCP/A2A, visual approval, backup/restore, and release sign-off remain environment gates. |

## Frontend capabilities

The frontend is a gateway-first static application in `frontend/`. It is a
reference operator dashboard, not the security boundary; identity, ownership,
quotas, and artifact authorization belong to the gateway/backend.

The optional DeepSeek Harness web surface is composed separately: the
Sudarshan brand and theme are replaceable packages documented in
[Harness UI composition](harness-ui-plugin.md). This keeps product styling out
of the official Harness branding package and lets another compatible Harness
profile use the same Sudarshan application boundary.

### Available now

- Google OAuth login through the Node gateway with HttpOnly-cookie sessions.
- Authenticated case selection, case creation, task history, and refresh-safe
  task recovery.
- Source upload for text, PDF, common image formats, presentation formats,
  and common video formats. The backend remains the final extension and size
  validator.
- Pipeline selection for advisory, executive summary, LinkedIn draft,
  infographic, presentation/PPT, and video.
- Run submission with idempotent task identity and gateway/FastAPI fallback
  projection.
- Live progress through SSE, with polling fallback and `sessionStorage`
  cursor recovery after refresh or reconnect.
- Visible waiting states for clarification, approval, provider-pending work,
  and other safe-action boundaries.
- Cooperative Stop/cancel action. It requests cancellation at an orchestration
  boundary; it does not forcibly stop a provider thread.
- Artifact manifest, preview, open, and download behavior. Videos and images
  are previewed; PPTX, Markdown, SVG, and other files can be opened/downloaded.
- Quality status, failure notices, wait reasons, classification, and safe
  telemetry such as tokens, latency, cache, wait, artifact, and quality
  counters.
- Development-only one-time OpenAI key setup when enabled by the backend.
  The key is not stored in browser storage.

### Not yet a complete product UI

- No full parent/child execution graph or per-slide execution lane view.
- No interactive visual QA/repair editor for PPT, infographic, or diagram
  outputs.
- No operator-facing audit-log explorer with retention/access controls.
- No browser end-to-end test suite against live OAuth, MongoDB, Cognee, and
  provider services; current frontend tests focus on the API projection and
  cursor contract.
- Direct FastAPI fallback does not provide gateway-level user history,
  OAuth, quotas, or production ownership enforcement.

## Backend capabilities

### Implemented and tested locally

- FastAPI application boundary with health, pipeline discovery, ingestion,
  asynchronous run admission, status, bounded wait, SSE events, resume, and
  cooperative cancellation.
- Node gateway integration for OAuth, MongoDB-backed cases/tasks, ownership,
  quotas, idempotency, authenticated artifact delivery, and Python API proxying.
- User/Case/Task-scoped memory through `MemoryManager`, with Cognee kept behind
  the adapter boundary and bounded context packs, provenance, lifecycle, and
  prompt-injection markers.
- LangGraph request understanding, clarification, routing, fan-out/fan-in,
  checkpoints, cancellation, and safe result projection.
- CrewAI specialist pipelines for advisory, executive summary, LinkedIn,
  infographic, presentation, and video.
- Native media/rendering paths: editable flowchart SVG/PPTX, AntV SSR bridge,
  native video scene generation/composition, and quality reports.
- Typed skill contracts, versioned manifests, skill workspace resources,
  trust-tier checks, capability/tool allow-lists, side-effect approvals,
  bounded child execution, cooperative timeouts, and token/tool budgets.
- Durable local SQLite scheduler with leases, renewal, stale-lease recovery,
  retries, dead-letter state, cancellation, duplicate submission protection,
  and execution deadlines.
- T39 shared control-plane contract with an optional Redis lease/idempotency
  adapter and Redis Stream queue discovery; run and ingestion schedulers use
  separate stream names and can discover work admitted by another process,
  recover pending entries after consumer loss with `XAUTOCLAIM`, and retain
  entries for actively leased runs. The typed progress stream now has a
  Redis-backed sink with reconnectable per-run cursors; the application still
  defaults to SQLite. `DependencyDAG` and the PPT vertical accept the shared
  control plane for fenced node claims, dependent-node admission, and atomic
  per-run DAG snapshot replication. Exact-match cache entries and stampede
  claims use Redis in shared mode. Budget reservations and usage reconciliation
  for the main run controller use atomic Redis scripts in shared mode; provider
  estimates remain explicitly marked and are not billing truth. The ingestion
  queue is shared in Redis mode, but its parser/OCR/vision/summary/embedding
  stage budget and usage ledger now use Redis in shared mode; estimates remain
  explicitly separated from observed usage.
  Optional live Redis tests cover cross-process discovery and stale-worker
  fencing.
- Persisted dependency DAG with bounded parallel admission, dependency
  blocking, repair limits, and restarted-bridge dependent-node recovery.
- Verified artifact manifests, checksum validation, safe path checks, previews,
  classification access checks, and quality-gated delivery.
- Exact-match quality-gated cache with authorization-aware fingerprints,
  privacy-filtered metadata, TTL, and stampede leases.
- Allow-listed observability projections for run/task/skill usage, latency,
  cache, waits, quality, and artifacts; safe dashboard telemetry endpoint.
- Tamper-evident audit records, query hashing, recursive secret redaction,
  classification propagation, and first-slice source-content injection guards.
- DeepSeek Harness JSONL/MCP integration, skill discovery, local skill calls,
  durable background skill jobs, bounded waiting, artifact lookup, health, and
  memory tools.
- OpenViking-inspired L0/L1/L2 context selection with stage defaults,
  safe legacy fallback, retrieval trace reporting, and typed `ContextPack`
  context levels. Skill manifests also declare bounded reference loading,
  renderer capabilities, and checker ownership; the reference repositories
  remain design inputs rather than runtime dependencies.
- T56–T60 local slices are present: a shared renderer capability registry,
  semantic diagram-family planner, slide-job/presentation quality workflow,
  provider-neutral video timeline and asset ledger, plus content-free memory
  lifecycle events and offline retrieval/cost evaluation. These are locally
  tested contracts; visual approval, real-corpus measurements, and distributed
  deployment remain release gates.
- DeepSeek Harness web composition through replaceable Sudarshan brand and
  theme plugins; generated preview credentials and session state are ignored.
- Current source upload and extraction compatibility path for text, PDF, PPTX,
  image, and video. T31 contracts, T32 source safety, and the T33 local
  asynchronous admission slice, and T34 typed-evidence adapters for text,
  PDF, PPTX, image, and video are implemented; the T35 deterministic
  structure/chunk compiler, the T36 local evidence-index/projection slice, and
  the T37 budget/fingerprint-cache boundary are also implemented locally. The
  asynchronous ingestion worker now receives a normalized budget, skips a
  matching scoped parser-stage cache entry, and returns safe cache/budget
  receipts. Optional image/PDF/video provider failures now preserve explicit
  fallback metadata and can finish as `PARTIAL`. Scheduler status and health
  metrics include queue-wait telemetry. Shared indexing, full provider-usage
  reconciliation and production retrieval benchmarks remain open in T36–T38;
  T39–T42 now provide shared queue/budget/object-storage/observability seams.
  The
  ingestion receipt now separates preflight token estimates from provider
  response usage when available. T38 now has a deterministic multimodal
  benchmark and promotion gate comparing flat-text retrieval with typed
  evidence and recording extraction coverage, evidence recall/faithfulness,
  tokens, cost, P50/P95 latency, cache hits, queue wait, repairs, and
  human-correction time. It is an offline evaluation slice, not production
  benchmark evidence. Optional vision-provider stages now have a bounded,
  opt-in retry seam that re-charges each attempt and preserves fallback
  behavior for non-retryable failures. Skill-cache startup cleanup now removes
  expired cache references and abandoned generation claims without deleting
  artifact files. Asynchronous ingestion status now projects budget, estimated
  versus actual usage, cache state, fallback reasons, and evidence counts at
  the top level for reconnect-safe dashboards while retaining the legacy
  nested result. Scheduler terminal state and its completion event now commit
  atomically, preventing reconnect consumers from observing a terminal status
  before the final event.

### Backend work still required

These are real engineering gaps, not cosmetic follow-ups:

1. Run the live Redis/worker smoke suite and add kill-9, host-loss, concurrent
   duplicate-worker, lease-fencing, and
   abandoned-artifact cleanup tests against the production-like control plane.
2. Configure and drill S3/MinIO server-side encryption, versioned backup and
   restore; the adapter and local verified cache are implemented.
3. Operate the optional redacted telemetry collector and reconcile estimated
   usage with provider billing receipts.
4. Operate production key management, authenticated distributed authorization,
   and Docker/resource-limit drills for untrusted skills. The signing and
   sandbox policy code is present.
5. Run font/raster/video visual regression snapshots and human approvals. The
   shared deterministic visual-QA and renderer-promotion gate is present.
6. Wire every production PPT/LinkedIn/video planner to the typed child-plan
   adapter and run the external MCP/A2A lifecycle smoke test. The contracts,
   A2A boundary, fallback reconciliation, and monitor are present.
7. Complete the T34–T38 ingestion workstream in production-like infrastructure:
   shared evidence/object storage, modality provenance, structure-aware
   indexing, Cognee projection, cache/budget controls, security, and benchmark
   runs on reviewed real or sanitized sources. The local T38 evaluator and T47
   archive schema are ready, but are not a substitute for those runs.
8. Execute the T47 benchmark and T52 backup/restore, rollback, ownership, and
   final release sign-off gates.

## Request and data flow

```mermaid
sequenceDiagram
    participant O as Operator / Frontend
    participant G as Node Gateway
    participant A as FastAPI + SudarshanApplication
    participant H as DeepSeek Harness / MCP client
    participant C as LangGraph control plane
    participant S as SkillRuntime / CrewAI / renderers
    participant Q as Quality + Artifact policy
    participant D as Dashboard telemetry

    O->>G: authenticate, select case, upload source
    G->>A: scoped /ingest
    O->>G: submit transformation
    H->>A: MCP run or skill request
    G->>A: POST /runs
    A->>C: understand, recall, route
    C->>S: bounded parallel skills
    S->>Q: typed output, renderer, quality gate
    Q-->>A: manifest, status, safe events
    A-->>G: status / SSE / telemetry
    G-->>O: progress, wait state, preview, download
    A->>D: allow-listed usage and quality projection
```

## Verification snapshot

The current local verification snapshot is:

```text
Python: 252 passed, 7 skipped
T28 reliability focus: 21 passed
Frontend projection/cursor tests: 3 passed
Node gateway tests: 9 passed
JavaScript syntax checks: passed
git diff --check: passed
```

The Python suite is deterministic and uses a workspace-local pytest temporary
directory in the restricted development environment. It does not prove live
MongoDB, Google OAuth, Cognee, OpenAI, AntV SSR availability, or production
multi-host behavior.

## Source-of-truth documents

- [Engineering handbook](sudarshan-2.0-engineering-handbook.md)
- [Full execution plan](sudarshan-2.0-full-execution-plan.md)
- [Skill authoring](skill-authoring.md)
- [Artifact rendering and quality](artifact-rendering-and-quality.md)
- [Assumption ledger](sudarshan-2.0-assumptions.md)
- [Backend integration contract](backend-integration.md)
- [Frontend integration contract](frontend-integration.md)
- [Operations and deployment guide](operations.md)
- [Harness integration](../integrations/deepseek_harness/README.md)
- [Harness UI composition](harness-ui-plugin.md)
- [Remaining-work execution plan](sudarshan-2.0-remaining-work-plan.md)
