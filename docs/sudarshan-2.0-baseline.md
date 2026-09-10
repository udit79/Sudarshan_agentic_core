# Sudarshan 2.0 implementation baseline

This file records the repository state before the durable execution-contract work.
It is intentionally factual and should be updated only when a ticket changes a
public boundary.

## Current execution path

```text
HTTP /runs or Harness MCP
  -> SudarshanApplication
  -> LangGraph PipelineOrchestrator
  -> memory recall + request understanding + prompt plan
  -> registered PipelineAdapter
  -> CrewAI flow or native video/renderer implementation
  -> PipelineResponse
  -> SQLite checkpoint/progress + audit log
```

## Current public routes

- `GET /health`
- `GET /pipelines`
- `POST /ingest`
- `POST /runs`
- `GET /runs/{run_id}`
- `GET /runs/{run_id}/events`
- `POST /runs/{run_id}/resume`
- `POST /runs/{run_id}/cancel`
- `GET /artifacts/{run_id}/{artifact_key}`

## Current Harness MCP tools

- `run_sudarshan`
- `get_sudarshan_status`
- `resume_sudarshan`
- `cancel_sudarshan`
- `get_sudarshan_health`
- `list_sudarshan_pipelines`
- `remember_sudarshan_context`
- `recall_sudarshan_context`

## Current pipeline registry

`advisory`, `linkedin_post`, `executive_summary`, `infographic`,
`presentation`, and `video`.

## Important current implementation facts

- `PipelineAdapter` is the existing top-level extension seam.
- Top-level multi-pipeline fan-out uses a bounded `ThreadPoolExecutor` with a
  maximum of eight workers.
- `SudarshanApplication` uses SQLite-backed LangGraph checkpoints and a
  SQLite-backed progress sink by default.
- The API starts the application call with FastAPI `BackgroundTasks`.
- The Node gateway stores authenticated task/quota projections in MongoDB and
  forwards execution to the Python API.
- PPT currently produces a complete `PresentationOutput` and renders basic
  title/content placeholder slides through `python-pptx`.
- Native video scene generation currently loops through scenes sequentially.

## Verification baseline

The targeted Python, pipeline, component, system, and API tests passed before
the execution-contract changes:

```text
51 passed, 2 warnings
```

The test command used a workspace-local `UV_CACHE_DIR` and disabled pytest's
cache provider. The warnings came from third-party dependencies and were not
introduced by the contract work.

