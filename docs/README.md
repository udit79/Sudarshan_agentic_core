# Documentation guide

This directory contains the implementation contract for Sudarshan Agentic Core.
The root README is the orientation and setup document; the files below are the
technical source of truth.

## Start here

1. Read the root [README](../README.md) for the product boundary, setup,
   pipeline catalogue, testing, troubleshooting, team credits, and design
   gallery.
2. Read [pipeline orchestration](internal/pipeline-orchestration.md) for the
   internal graph, memory sequence, pipeline diagrams, model routing, quality
   gates, and artifact lifecycle.
3. Read [backend integration](backend-integration.md) for the Python API,
   ingestion, status, SSE, resume/cancel, and MCP contract.
4. Read [gateway integration](gateway-integration.md) for Node authentication,
   cases, transformations, tasks, quotas, and MongoDB behavior.
5. Read [frontend integration](frontend-integration.md) for Python API calls,
   uploads, polling, SSE, rendering, and security behavior.
6. Read [operations](operations.md) for setup, configuration, testing,
   troubleshooting, live smoke checks, and production requirements.
7. Read [memory README](../memory/README.md) for Cognee, User/Case/Task
   boundaries, recall, write-back, and provenance.
8. Read [pipeline README](../pipelines/README.md) for pipeline-specific
   contracts and native media behavior.

## System ownership

| Area | Source of truth | Must not be duplicated by |
| --- | --- | --- |
| Authentication, user/case ownership, quotas | Node gateway | browser or pipeline |
| HTTP API and file upload boundary | FastAPI | Harness workflow |
| Routing and lifecycle | LangGraph orchestrator | gateway or Harness |
| Memory scope and Cognee access | MemoryManager | agents or frontend |
| Specialist collaboration | CrewAI pipeline flows | gateway |
| Session/tool/runtime integration | DeepSeek Harness | pipeline internals |
| Preview, editing, and delivery UI | frontend | backend renderer |

## Terminology

- **Application boundary**: SudarshanApplication, used by HTTP and Harness/MCP.
- **Request understanding**: identifies intent, audience, constraints, and
  requested pipelines; it does not receive authority to override the request
  using memory.
- **Prompt plan**: validated pipeline-specific instructions created after
  routing and bounded recall.
- **Pipeline crafter**: a specialist planning role inside a pipeline. Current
  cross-pipeline coordination is typed and deterministic; unrestricted
  crafter-to-crafter LLM dialogue is not enabled by default.
- **Quality gate**: structured critic output that approves or rejects a
  pipeline artifact.
- **Provider pending**: an external worker is still executing. It is distinct
  from clarification or human approval.
- **Artifact**: a validated output reference and its durable files, not raw
  model reasoning.

## Contract rules

1. All externally submitted identity must be authenticated at the gateway or
   application boundary.
2. All memory access must go through MemoryManager and AccessContext.
3. All pipeline outputs must satisfy their Pydantic contract before delivery or
   Case-memory write-back.
4. Pipeline dependencies must be explicit; dependency cycles are rejected.
5. Frontend code must never receive provider credentials, raw Cognee context,
   or hidden model reasoning.
6. Provider-specific behavior belongs behind integrations/providers or a
   pipeline adapter.
7. Local SQLite state is for development/single-instance use; production
   requires approved shared durable storage.
8. Documentation diagrams must match the implemented call order: request
   understanding, routing, recall, prompt plan, then pipeline execution.

## Operational documents

- [MVP status](internal/mvp-status.md) records what is implemented and what
  still requires live deployment work.
- [Design review](design-review.md) records factual improvements for the
  submitted architecture slides.

## Verification baseline

The repository's offline baseline is:

- Python: 90 passed, 1 skipped at the last verification.
- Node gateway: 4 focused tests passed.
- Reference frontend: JavaScript syntax checks passed.
- Harness application boundary: 12 focused integration tests passed.

These tests do not prove external MongoDB, Cognee, Google OAuth, OpenAI, or
MoneyPrinterTurbo reachability. A live smoke test must be run only with
intentionally configured services.
