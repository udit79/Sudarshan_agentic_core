# Sudarshan 2.0: Team-Parallel Implementation Guide

This guide is the execution companion to [Sudarshan 2.0 Full Execution Plan](sudarshan-2.0-full-execution-plan.md). It defines how the frontend, backend, agentic, rendering, memory, and evaluation teams can work in parallel on the `Sudarshan2.0` branch.

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
| Memory/evaluation | Cognee scopes, retrieval traces, benchmarks | bounded context pack + metrics |
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

### Shared API/MCP projection

```text
POST /runs
GET  /runs/{run_id}
GET  /runs/{run_id}/events?after={sequence}
POST /runs/{run_id}/resume
POST /runs/{run_id}/cancel
GET  /artifacts/{artifact_id}/manifest
GET  /artifacts/{artifact_id}/preview
```

MCP tools map to the same operations: `start_sudarshan_run`, `get_sudarshan_status`, `wait_sudarshan`, `resume_sudarshan`, `cancel_sudarshan`, and `get_sudarshan_artifact`.

## 4. Backend guide

### Work packages

- **Run coordinator:** submit asynchronously, persist before execution, assign IDs, validate skill/policy/budget, compile a typed DAG, return immediately.
- **Event store:** append monotonic events, build a current run projection, support replay with `after_sequence`, redact before persistence.
- **Scheduler:** begin with an in-process queue, then add leases, heartbeats, timeouts, retry classes, idempotency, and concurrency groups.
- **Artifact service:** store binaries outside the event table, create immutable manifests/checksums/previews, enforce classification on download.
- **MCP/API adapter:** keep synchronous compatibility, add async run tools, return structured data/resources, test stdio and Streamable HTTP.
- **Memory gateway:** keep `MemoryManager` as the only Cognee gateway; add scopes, provenance, freshness, confidence, retrieval traces, and reviewed writes.

### Backend acceptance tests

1. One idempotency key creates one run.
2. Submission returns before long work completes.
3. Status survives process restart.
4. Event sequences are monotonic and replayable.
5. Cancelling a queued run prevents admission.
6. A running run reaches a safe cancelled state.
7. Only retryable errors retry.
8. Failed children block dependent nodes.
9. Artifact access checks authorization and classification.
10. Credentials never appear in events or artifacts.
11. Waiting runs resume with structured input.

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
- Define `PresentationSpec` and `FlowchartSpec` schemas.
- Compile a typed DAG with evidence, rendering, and QA nodes.
- Keep skill bodies compact and tools allow-listed.
- Add planner, validator, token, and repair fixtures.

### Rendering team

- Implement theme tokens and canonical geometry.
- Render the same geometry to SVG and editable PPTX shapes/connectors.
- Add snapshots for process, decision, architecture, timeline, and swimlane diagrams.
- Add overflow, edge-crossing, contrast, and font-size validators.

### Memory/evaluation team

- Build cases with known claims and contradictions.
- Add retrieval traces and scope checks.
- Define memory write, review, supersession, and deletion states.
- Compare no memory, raw retrieval, scoped graph retrieval, and improved experience retrieval.
- Measure groundedness, context tokens, stale-memory rate, and case isolation.

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
