# Sudarshan 2.0: Team-Parallel Implementation Guide

This guide is the execution companion to [Sudarshan 2.0 Full Execution Plan](sudarshan-2.0-full-execution-plan.md). It defines how the frontend, backend, agentic, rendering, memory, and evaluation teams can work in parallel on the `Sudarshan2.0` branch.

## 0. Post-H-series handoff

The H-series implementation is complete locally. H-01 through H-08 now cover
the native Harness profile, replaceable MCP adapter, skill discovery profile,
live OperationsBridge projection, sandbox contract, lifecycle parity tests,
and the offline cost/latency/quality benchmark. There is no remaining
H-series architecture rewrite for the agentic team.

This is a local implementation completion, not production approval. The open
work is deployment evidence and product integration:

| Lane | Continue with | Do not redo |
|---|---|---|
| Agentic/Harness | T51 real planner wiring and one complete cross-skill DAG; T49 independent MCP/A2A staging proof; skill manifests, typed child plans, and evaluations | Do not replace LangGraph, CrewAI, Sudarshan lifecycle, or the native Harness adapter; do not edit vendored Harness core |
| Backend/platform | T39–T46 and T48–T52 staging gates: shared control plane, object storage, receipts, sandbox runtime, external interop, visual QA, release/rollback | Do not create a second scheduler or make Harness session history the source of truth |
| Frontend/native Harness | T45 execution monitor, artifact/evidence workspace, approvals, reconnect, audit-safe logs, and release views | Do not call Cognee, model providers, CrewAI, skill internals, or Harness internals directly from browser code |
| Rendering/evaluation | T50 visual regression and human approval; PPT/video/infographic/diagram corpus and promotion thresholds | Do not change renderer contracts without fixtures and a compatibility review |

Before starting work after the integration commit:

1. Pull the committed baseline and create a short-lived branch from it.
2. Read this guide, the [remaining-work plan](sudarshan-2.0-remaining-work-plan.md),
   and the [frontend/backend matrix](frontend-backend-feature-matrix.md).
3. Run the affected contract/component tests using a writable pytest root on
   locked-down Windows:

   ```powershell
   .\.venv\Scripts\python.exe -m pytest -q --basetemp .pytest-tmp-team
   ```

4. Select one ticket, record its assumption in
   `docs/sudarshan-2.0-assumptions.md`, and add or update its shared fixture
   before changing a public field.
5. Mark the ticket only as `Complete locally` until the required staging,
   benchmark, security, or human-approval evidence exists.

The source-of-truth rule is unchanged: Sudarshan owns identity, routing,
budgets, scheduling, memory access, quality gates, cancellation, and artifact
promotion. Harness, MCP, A2A, CrewAI, providers, and renderers are adapters.
The frontend receives safe projections and artifact manifests; it never parses
assistant text to infer execution state.

## 1. First vertical slice

The first cycle should prove one complete path:

```text
Harness request → durable run → progress events → parallel DAG
→ PPTX with one editable flowchart → quality verdict → preview/download
```

Do not wait for every pipeline. One reliable vertical slice is more valuable than several disconnected prototypes.

## 2. Team lanes

| Team | Owns | First-cycle deliverable |
|---|---|---|
| Backend/control plane | runs, events, queue, workers, MCP/API, artifacts | durable run service |
| Frontend/native Harness | run card, Execution Monitor, artifacts, approvals | operator UI |
| Agentic/skills | manifests, typed plans, validators | presentation + flowchart contracts |
| Rendering | slide IR, flowchart IR, SVG/PPTX | editable flowchart slide |
| Memory/evaluation | Cognee scopes, evidence projection, retrieval traces, benchmarks | bounded context pack + ingestion/retrieval metrics |
| Ingestion/data | manifests, modality plugins, evidence blocks, source safety, ingestion jobs | one PDF/PPTX/video source compiled into reusable evidence |
| Platform/security | local setup, CI, auth, secrets | reproducible safe environment |

Each team may use mocks, but public contract changes require cross-team review.

## 3. Shared contracts to lock first

Create transport-neutral schemas before teams build independently.

### Run summary

```json
{
  "run_id": "run_01J...",
  "task_id": "task_01J...",
  "case_id": "case-123",
  "skill_id": "presentation.case-brief",
  "skill_version": "2.0.0",
  "execution_version": "2026.1",
  "status": "running",
  "stage": "rendering",
  "progress": 72,
  "requires_action": false,
  "quality_status": "pending",
  "artifact_count": 1,
  "child_count": 5
}
```

Statuses: `accepted`, `queued`, `planning`, `running`, `waiting_for_input`, `waiting_for_approval`, `retrying`, `validating`, `completed`, `failed`, `cancelled`.

### Safe event

```json
{
  "event_id": "evt_01J...",
  "run_id": "run_01J...",
  "sequence": 42,
  "stage": "rendering.flowchart",
  "status": "succeeded",
  "progress": 72,
  "child_id": "flowchart-layout-1",
  "message": "Flowchart preview rendered",
  "artifact_id": "artifact_01J...",
  "error_code": null,
  "requires_action": false
}
```

Events must not contain credentials, raw private memory, unrestricted prompts, hidden reasoning, or unbounded provider output.

### Artifact manifest

```json
{
  "artifact_id": "artifact_01J...",
  "run_id": "run_01J...",
  "kind": "pptx",
  "name": "case-brief.pptx",
  "uri": "/artifacts/artifact_01J.../download",
  "preview_uri": "/artifacts/artifact_01J.../preview",
  "sha256": "...",
  "classification_level": "RESTRICTED",
  "quality_status": "passed",
  "source_ir_hash": "...",
  "renderer_version": "ppt-renderer@2.0.0"
}
```

### PPT planning and intermediate artifacts

The Harness central agent owns the deck-level plan. Workers own bounded slide tasks. No worker writes the final PPTX directly.

```text
DeckPlan → SlideTask[] → SlideContentIR[] → VisualTask[] → VisualIR[]
         → DeckAssembler → PPTX/SVG → QualityReport → RepairPatch?
```

Minimum contracts for the first vertical slice:

- `DeckPlan`: audience, objective, slide specs, evidence IDs, visual intent, dependencies, theme, budget, and quality policy.
- `SlideTask`: slide ID, narrative role, compact context pack, evidence references, token/deadline reservation, and parent run ID.
- `SlideContentIR`: title, claims, notes, layout intent, citations, confidence, and unresolved questions.
- `VisualTask` and `VisualIR`: semantic visual type, graph/chart/infographic data, renderer target, source hash, and citations.
- `RepairPatch`: slide ID, diagnostics, bounded edits, and claim IDs that must remain unchanged.

The deck plan should include a visual hint for each slide, then a post-content visual router may upgrade or correct that hint. This keeps slide workers parallel while still allowing the system to discover that a slide needs a diagram or infographic.

### Shared API/MCP projection

```text
POST /runs
GET  /runs/{run_id}
GET  /runs/{run_id}/events?after={sequence}
GET  /runs/{run_id}/wait?timeout_ms={n}&after_sequence={sequence}
POST /runs/{run_id}/resume
POST /runs/{run_id}/cancel
GET  /artifacts/{run_id}/{artifact_key}/manifest
GET  /artifacts/{artifact_id}/manifest
GET  /artifacts/{artifact_id}/download
```

The current compatibility tool is `run_sudarshan`. The target asynchronous MCP surface is `start_sudarshan_run`, `get_sudarshan_status`, `wait_sudarshan`, `resume_sudarshan`, `cancel_sudarshan`, and `get_sudarshan_artifact`. Add the target names without removing `run_sudarshan` until external Harness compatibility tests pass.

## 4. Backend guide

### Work packages

- **Run coordinator:** submit asynchronously, persist before execution, assign IDs, validate skill/policy/budget, compile a typed DAG, return immediately.
- **PPT DAG compiler:** compile `DeckPlan` into slide tasks; run independent slides concurrently, serialize declared dependencies, and enforce slide/visual concurrency groups.
- **Event store:** append monotonic events, build a current run projection, support replay with `after_sequence`, redact before persistence.
- **Scheduler:** the local slice now persists admission, idempotency, queued/retrying cancellation, worker leases, heartbeat renewal, stale-lease recovery, retry classes, backoff, dead-letter state, optional execution deadlines, callback cancellation signals, and health counts; provider adapters must honor those signals and use bounded network/process operations. Next add crash injection and a distributed broker/lease store when deployment topology requires it.
- **Artifact service:** store binaries outside the event table, create immutable manifests/checksums/previews, enforce classification on download.
- **MCP/API adapter:** keep synchronous compatibility, add async run tools, return structured data/resources, test stdio and Streamable HTTP.
- **Memory gateway:** keep `MemoryManager` as the only Cognee gateway; add scopes, provenance, freshness, confidence, retrieval traces, and reviewed writes.
- **Ingestion boundary:** keep the current `/ingest` compatibility path while
  adding the asynchronous manifest/job path described in
  [Ingestion architecture](ingestion-architecture.md). The backend owns source
  validation, bounded staging, job status, idempotency, cancellation, and safe
  ingestion events. It must not pass raw files or unrestricted extraction text
  directly to the Harness.

### Backend acceptance tests

1. One idempotency key creates one run.
2. Submission returns before long work completes.
3. Status survives process restart.
4. Event sequences are monotonic and replayable.
5. Cancelling a queued run prevents admission.
6. A running run reaches a safe cancelled state.
7. Only retryable errors retry.
8. Failed children block dependent nodes.
9. A healthy long-running worker renews its lease; an expired worker lease is reclaimed after restart.
10. Artifact access checks authorization and classification.
11. Credentials never appear in events or artifacts.
12. Waiting runs resume with structured input.
13. A cancellation request reaches a compatible worker/provider, and media subprocesses terminate on cancellation or timeout.

### Backend boundaries

```text
api/                         transport handlers and DTOs
orchestration/               coordinator, DAG, status projection
execution/                   queue, leases, workers, retry policy
artifacts/                   manifests, storage, previews, checksums
memory/                      MemoryManager and Cognee adapter
policies/                    auth, classification, release rules
integrations/deepseek_harness/ MCP server and native adapter
```

Pipeline code returns typed domain results; it does not format frontend responses.

## 5. Frontend and native Harness guide

### Work packages

- **Submission:** show selected skill/version and required inputs; generate an idempotency key; move to a run card immediately after acceptance.
- **PPT monitor:** show deck-plan progress, slide lanes, child visual skills, dependency waits, render/QA/repair stages, and the final artifact lineage.
- **Run card:** show skill, status, stage, progress, elapsed time, quality state, artifacts, and required action; support cancel, resume, approve, retry, and open artifact.
- **Execution Monitor:** build active list, run detail, timeline, parent/child tree, parallel lanes, artifact panel, evidence/quality panel, and audit actions.
- **Event stream:** connect with `run_id`, retain the last sequence, reconnect with `after_sequence`, merge idempotently, and fall back to bounded polling.
- **Artifact workspace:** show slide thumbnails, flowchart SVG, PPTX/PDF/video links, artifact versions, quality verdicts, evidence links, and unresolved gaps.

The UI must render from `RunSummary`, `RunEvent`, `ArtifactManifest`, and `QualityReport`. It must never parse assistant text to discover progress.

### Frontend acceptance tests

1. `queued` appears before work starts.
2. Progress updates without duplicate rows.
3. Reconnect resumes from the last sequence.
4. Waiting-for-input shows the required action.
5. Cancel reflects server confirmation and prevents duplicate requests.
6. Failure shows a safe error code and recovery action.
7. Artifact cards appear only after a manifest exists.
8. Unauthorized actions are hidden or disabled.
9. No prompt, private memory, credential, or hidden reasoning appears.
10. Native Harness and standalone monitor share the same state model.

## 6. Agentic, rendering, memory, and evaluation guides

### Agentic/skills team

- Define `presentation.case-brief` and `visual.flowchart` manifests.
- Define `DeckPlan`, `SlideTask`, `SlideContentIR`, `VisualTask`, `VisualIR`, `RepairPatch`, `PresentationSpec`, and `FlowchartSpec` schemas.
- Compile a typed DAG with evidence, rendering, and QA nodes.
- Keep skill bodies compact and tools allow-listed.
- Add planner, validator, token, and repair fixtures.
- Implement the first hierarchical PPT flow: one deck planner, bounded slide workers, visual routing, and selective final review. Keep the current sequential flow behind a feature flag.
- Extract the current video pipeline into `video.brief`, `video.script`, `video.storyboard`, `video.assets`, `video.timeline`, and `video.qa` stages.
- Define `EvidenceLedger`, `ContextPack`, `VideoTimelineIR`, `InfographicIR`, and `DiagramIR` before adding more agents.
- Ensure the central agent passes compact stage artifacts, not full transcripts, to scene workers; give every worker a budget, deadline, cache key, and parent run ID.
- Treat ingestion as a reusable platform capability, not a separate skill
  implementation for every output type. Skills request evidence by ID and
  modality (`search_text`, `search_visual`, `search_table`,
  `search_video_segment`, `get_evidence`); they do not call Cognee or reparse
  source files.
- Implement diagram/mind-map grammar selection and graph validation; renderer-specific source such as AntV or Mermaid must be compiled from the typed IR.

### Rendering team

- Implement theme tokens and canonical geometry.
- Render the same geometry to SVG and editable PPTX shapes/connectors.
- Add snapshots for process, decision, architecture, timeline, and swimlane diagrams.
- Add overflow, edge-crossing, contrast, and font-size validators.
- Add deterministic FFmpeg/ffprobe checks for video duration, codecs, audio presence, scene order, caption safe areas, and manifest hashes.
- Add infographic SVG/PNG visual QA for overflow, contrast, bilingual text, density, and accessibility metadata.
- Use a shared diagram layout/export layer for SVG, HTML, PNG, and PPT embedding; record a fidelity ledger when detail is reduced.

### Ingestion/data team

- Implement the canonical `IngestionManifest`, `EvidenceBlock`,
  `ExtractionEvent`, and `QualityReport` contracts without removing the
  legacy `IngestedDocument` path.
- Refactor PDF/PPTX/image/video extractors to preserve page, slide, region,
  and timestamp provenance; return typed evidence before producing summaries.
- Add source hashing, parser/model/config fingerprints, targeted fallback
  routing, bounded modality budgets, cache reuse, partial-result semantics,
  and prompt-injection markers.
- Add fixtures for scanned PDFs, table-heavy PDFs, slide decks, infographics,
  repeated video frames, scene boundaries, extraction failures, and partial
  ingestion.
- Do not make Cognee the raw artifact store. Project governed summaries,
  entities, relationships, and evidence references through `MemoryManager`.

### Memory/evaluation team

- Build cases with known claims and contradictions.
- Add retrieval traces and scope checks.
- Define memory write, review, supersession, and deletion states.
- Compare no memory, raw retrieval, scoped graph retrieval, and improved experience retrieval.
- Measure groundedness, context tokens, stale-memory rate, and case isolation.
- Implement L0/L1/L2 `ContextPack` loading over the existing `MemoryManager` and Cognee adapter; keep run state outside Cognee.
- Benchmark full-context versus top-k Cognee versus progressive context packs for video scene planning and infographic generation.
- Evaluate agentmemory-inspired episodic capture only behind privacy, deletion, scope, and license checks; treat OpenViking as a progressive-context design reference until legal review is complete.
- Convert LinkedIn into composable parent/child skills: grounding, hook planning, post writing, visual selection, humanizer audit, quality gate, and approval/publish.
- Define `SkillCall` and `SkillResult` fixtures so `linkedin.post` can call `diagram.flowchart` or `infographic` without passing the full conversation.
- Require semantic diffs for humanizer patches; factual changes must return through evidence and quality gates.

### Platform/security team

- Provide local configuration without committed secrets.
- Add secret scanning, auth fixtures, classification tests, and concurrent-run load tests.
- Define retention, deletion, backup, and restore behavior.

## 7. Shared fixtures

Create these before frontend and backend diverge:

```text
tests/contracts/run-summary.running.json
tests/contracts/run-summary.waiting.json
tests/contracts/run-summary.completed.json
tests/contracts/run-events.ndjson
tests/contracts/artifact-manifest.pptx.json
tests/contracts/quality-report.failed.json
tests/contracts/quality-report.passed.json
tests/contracts/flowchart.ir.json
tests/contracts/evidence-ledger.json
tests/contracts/context-pack.json
tests/contracts/video-timeline.ir.json
tests/contracts/infographic.ir.json
tests/contracts/diagram.ir.json
tests/contracts/video-quality-report.json
tests/contracts/skill-call.json
tests/contracts/skill-result.json
tests/contracts/humanization-report.json
tests/contracts/deck-plan.json
tests/contracts/slide-task.json
tests/contracts/slide-content.ir.json
tests/contracts/visual-task.json
tests/contracts/visual-decision.json
tests/contracts/repair-patch.json
```

The frontend can build against static fixtures while the backend implements the service. The backend can validate against the same fixtures without a browser.

## 8. Branch and pull-request strategy

The requested working branch is `Sudarshan2.0`. Create short-lived branches from it:

```text
Sudarshan2.0/backend-run-contract
Sudarshan2.0/backend-scheduler
Sudarshan2.0/frontend-execution-monitor
Sudarshan2.0/frontend-artifact-workspace
Sudarshan2.0/agentic-skill-runtime
Sudarshan2.0/ppt-flowchart-ir
Sudarshan2.0/ppt-renderer
Sudarshan2.0/cognee-memory-policy
Sudarshan2.0/evaluation-baseline
```

Rules:

- Contract changes require backend, frontend, and agentic review.
- Every public-field change needs fixtures and tests.
- UI PRs use fixtures and do not wait for the production queue.
- Backend PRs include API/MCP examples and replay tests.
- Rendering PRs include visual snapshots.
- Skill PRs include schemas and benchmark cases.
- Memory PRs include scope, provenance, freshness, and deletion tests.
- Keep PRs small and independently mergeable.

## 9. First two weeks

### Days 1–2: contract lock

Agree on run, event, artifact, quality, skill, status, and redaction contracts. Backend publishes fixtures. Frontend renders fixtures. Agentic team defines the first skill manifests.

### Days 3–4: foundations

Backend builds the in-memory run store and endpoints. Frontend builds run list/card/detail. Agentic builds presentation/flowchart plan fixtures. Rendering builds the flowchart IR parser and SVG proof of concept. Evaluation builds the baseline scorer.

### Days 5–7: integration

Backend emits safe events. Frontend consumes SSE/polling. Agentic runtime submits a fixed presentation DAG. Renderer creates one flowchart preview and artifact manifest. Quality records a verdict.

### Days 8–10: recovery

Add reconnect/replay, cancellation, retry, artifact preview/download, one intentional visual failure, targeted repair, and token/latency/cache counters.

### Days 11–14: demo slice

Run the complete flow through the native Harness or API. Show parallel stages, waiting behavior, editable flowchart output, evidence references, quality report, and baseline metrics.

## 10. Definition of done

- Frontend and backend work independently from shared fixtures.
- A user receives a durable run ID.
- The monitor shows live and replayed progress.
- One parallel DAG executes successfully.
- One editable flowchart slide is generated.
- Quality checks can fail the run.
- Targeted repair creates a new artifact version.
- Cognee retrieval is scoped and provenance-bearing.
- The native Harness displays the run and artifact.
- A second MCP client can use the basic run contract.
- Baseline quality, cost, latency, and recovery metrics are recorded.
