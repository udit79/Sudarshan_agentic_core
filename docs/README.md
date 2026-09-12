# Documentation guide

This directory contains the implementation contract for Sudarshan Agentic Core.
The root README is the orientation and setup document. The engineering
handbook is the end-to-end guide; the focused documents below are the detailed
contracts and runbooks. When a document and the code disagree, update the
document and the assumption ledger in the same change.

## Start here

1. Read the [Sudarshan 2.0 engineering handbook](sudarshan-2.0-engineering-handbook.md)
   for the complete request lifecycle, HLD/LLD, parallelism, waiting,
   budgeting, skills, rendering, memory, Harness/MCP, security, deployment,
   and team workflow.
2. Read the root [README](../README.md) for the product boundary, setup,
   pipeline catalogue, testing, troubleshooting, team credits, and design
   gallery.
3. Read [pipeline orchestration](internal/pipeline-orchestration.md) for the
   internal graph, memory sequence, pipeline diagrams, model routing, quality
   gates, and artifact lifecycle.
4. Read [backend integration](backend-integration.md) for the Python API,
   ingestion, status, SSE, resume/cancel, and MCP contract. Read the
   [ingestion architecture](ingestion-architecture.md) for the multimodal
   evidence model, asynchronous ingestion jobs, and migration tickets.
5. Read [gateway integration](gateway-integration.md) for Node authentication,
   cases, transformations, tasks, quotas, and MongoDB behavior.
6. Read [frontend integration](frontend-integration.md) for Python API calls,
   uploads, polling, SSE, rendering, and security behavior.
7. Read [operations](operations.md) for setup, configuration, testing,
   troubleshooting, live smoke checks, and production requirements.
8. Read [skill authoring](skill-authoring.md) before adding or modifying a
   skill, manifest, child skill, tool profile, or evaluation fixture.
9. Read [artifact rendering and quality](artifact-rendering-and-quality.md)
   before changing PPT, infographic, video, image, or document generation.
10. Read [memory README](../memory/README.md) for Cognee, User/Case/Task
   boundaries, recall, write-back, and provenance.
11. Read [pipeline README](../pipelines/README.md) for pipeline-specific
   contracts and native media behavior.
12. Read [Harness UI composition](harness-ui-plugin.md) for the native
   DeepSeek web plugin boundary and white-label replacement path.
13. Read the [remaining-work execution plan](sudarshan-2.0-remaining-work-plan.md)
   for the post-T38 production, interoperability, frontend, security, and
   release backlog.
14. Read the [diagram-design adoption plan](diagram-design-adoption-plan.md)
   before extending diagram types, imports, visual QA, or diagram delivery.

Research citations are centralized in the [full 2.0 execution plan](sudarshan-2.0-full-execution-plan.md)
and its [Harness research companion](sudarshan-2.0-harness-research.md). New
documents should link to those sources instead of copying reference lists.

## Documentation map

| Question | Primary document | Supporting source |
| --- | --- | --- |
| What is the architecture? | [Engineering handbook](sudarshan-2.0-engineering-handbook.md) | [Full execution plan](sudarshan-2.0-full-execution-plan.md) |
| How does a request run? | [Backend integration](backend-integration.md) | [Pipeline orchestration](internal/pipeline-orchestration.md) |
| How do I add a skill? | [Skill authoring](skill-authoring.md) | `skills/*/manifest.json`, `skills/*/SKILL.md` |
| How do I add a visual output? | [Rendering and quality](artifact-rendering-and-quality.md) | `pipelines/ppt`, `pipelines/infographic`, `pipelines/video` |
| How do I extend diagrams safely? | [Diagram Design adoption plan](diagram-design-adoption-plan.md) | `pipelines/diagram`, `skills/visual-flowchart` |
| How do I use Cognee safely? | [Memory README](../memory/README.md) | `memory/context_builder.py`, `memory/memory_manager.py` |
| How does the frontend consume runs? | [Frontend integration](frontend-integration.md) | The landing shell hands authenticated users to the DeepSeek Harness web frontend. |
| How does the gateway enforce ownership? | [Gateway integration](gateway-integration.md) | `backend-node/src` |
| How are files converted into reusable evidence? | [Ingestion architecture](ingestion-architecture.md) | `ingestion_pipelines/` |
| How does Harness connect? | [Harness integration](../integrations/deepseek_harness/README.md) | [Harness UI plugin](harness-ui-plugin.md) |
| How do I deploy and troubleshoot? | [Operations](operations.md) | [Assumptions](sudarshan-2.0-assumptions.md) |
| What is actually complete? | [Current status](current-status.md) | [Assumptions](sudarshan-2.0-assumptions.md) |
| What remains before production? | [Remaining-work plan](sudarshan-2.0-remaining-work-plan.md) | [Current status](current-status.md) |

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

- [Operations](operations.md) records setup, configuration, testing,
  troubleshooting, and deployment requirements.
- [Design review](design-review.md) records factual improvements for the
  submitted architecture slides.
- [Full execution plan](sudarshan-2.0-full-execution-plan.md) records the
  research-backed architecture, phases, team roles, and release gates.
- [Harness research](sudarshan-2.0-harness-research.md) records the research
  and comparison behind the native Harness/MCP/ADK/A2A direction.
- [Team parallel guide](sudarshan-2.0-team-parallel-guide.md) divides work
  across backend, agentic, frontend, rendering, and evaluation teams.
- [Assumption ledger](sudarshan-2.0-assumptions.md) records deployment risks and
  evidence still required.
- [Remaining-work plan](sudarshan-2.0-remaining-work-plan.md) is the active
  post-T38 execution backlog and release checklist.

## Verification baseline

The repository's current local baseline is:

- Python: 212 passed, 1 skipped when run with a workspace-local pytest
  temporary root.
- Reference frontend: 3 projection/cursor tests passed and JavaScript syntax
  checks passed.
- DeepSeek Harness official brand plugin: 6 focused tests passed.
- Sudarshan brand plugin: 3 focused tests passed.
- Sudarshan brand and theme bundles: built successfully.
- Harness client TypeScript project: passed.
- `git diff --check`: passed.

These tests do not prove external MongoDB, Cognee, Google OAuth, OpenAI,
AntV SSR, or provider reachability. A live smoke test must be run only with
intentionally configured synthetic services. A workspace-local pytest root may
be required on locked-down Windows environments:

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp .pytest-tmp-current
```
