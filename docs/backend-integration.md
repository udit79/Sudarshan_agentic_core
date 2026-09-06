# Backend integration handoff

This document is the contract between the backend, frontend, and the
DeepSeek Harness integration. The Python application is the source of truth
for routing, memory policy, pipeline execution, approval, cancellation, and
artifact metadata. The Harness is the session/tool/runtime layer.

## Start the service

```powershell
Copy-Item .env.example .env
# Fill Cognee, CrewAI/model, and any provider settings in .env.
uv run python -m api.server
```

The API listens on `SUDARSHAN_API_HOST:SUDARSHAN_API_PORT` (default
`0.0.0.0:8000`). Use `SUDARSHAN_CORS_ORIGINS` for a comma-separated allow-list;
do not use `*` with credentials in a deployed NTRO environment.

## HTTP contract

All mutating requests require `X-Operator-Id`. `X-Case-Id` may supply the case
when it is not in the JSON payload. If `user_id` is present, it must match the
operator header. Classification is normalized to one of `UNCLASSIFIED`,
`RESTRICTED`, `CONFIDENTIAL`, `SECRET`, or `TOP SECRET`.

### Create a run

`POST /runs` returns `202 Accepted` immediately:

```json
{
  "query": "Create an executive summary of the case",
  "user_id": "operator-1",
  "case_id": "case-42",
  "task_id": "task-42-summary",
  "classification_level": "RESTRICTED",
  "distribution": "Authorized NTRO personnel",
  "requested_pipelines": ["executive_summary"],
  "metadata": {}
}
```

The response contains `status`, `run_id`, and `task_id`. Poll
`GET /runs/{run_id}` or subscribe to `GET /runs/{run_id}/events`.

### Status and events

`GET /runs/{run_id}` returns frontend-safe state only: stage, status, selected
pipelines, clarification questions, errors, and ordered lifecycle events. Raw
Cognee results, prompts, credentials, and model reasoning are not returned.
The SSE event payload is a `ProgressEvent` with `event_id`, `run_id`,
`task_id`, `pipeline`, `stage`, `status`, `progress`, `message`, and optional
`artifact_id`/`error_code`.

### Resume and cancel

```text
POST /runs/{run_id}/resume
{ "task_id": "task-42-summary", "answer": "Focus on maritime activity" }

POST /runs/{run_id}/cancel
{ "task_id": "task-42-summary" }
```

Resume is used for clarification or authorized approval decisions. Cancellation
is cooperative: a provider call already in progress may finish, but the graph
records cancellation at the next safe boundary.

## Harness/MCP contract

Register `integrations/deepseek_harness/sudarshan.cordis.yml` with the vendored
Harness. It starts the trusted Python MCP server and exposes:

- `run_sudarshan`
- `get_sudarshan_status`
- `resume_sudarshan`
- `cancel_sudarshan`
- `get_sudarshan_health`
- `list_sudarshan_pipelines`
- `remember_sudarshan_context`
- `recall_sudarshan_context`

The MCP server and HTTP API call the same process-scoped
`SudarshanApplication`; they do not create a second router or direct Cognee
tool. Never put Cognee, OpenAI, provider, or NTRO case secrets in a Harness
workflow, Cordis patch, or E2B sandbox.

## End-to-end memory path

1. `ingestion_pipelines.ingest_file(..., memory_manager=manager)` extracts a
   source, converts it to a `KnowledgeUnit`, and writes it through
   `MemoryManager` into the correct Case/User/System scope.
2. The router recalls bounded User/Case memory for request understanding.
3. After pipeline selection, the router recalls permitted User/Case/Task
   memory and passes only bounded, provenance-preserving context to the flow.
4. CrewAI agents get a scoped recall tool; they never get a Cognee client or
   credentials.
5. Task lifecycle events are written through `TaskMemoryWriter`.
6. Validated pipeline outputs are written back to Case memory according to the
   pipeline's release policy. Revisions create new task/artifact versions.

Cognee is configured through `COGNEE_BASE_URL`, `COGNEE_API_KEY`,
`COGNEE_TENANT_ID`, and `COGNEE_DATASET_NAME`. The local `MemoryStore` is an
idempotency/domain cache, not a replacement for Cognee.

## Pipeline and provider behavior

The default registry exposes `advisory`, `linkedin_post`, `executive_summary`,
`infographic`, `presentation`, and `video`. Multiple requested pipelines fan
out with isolated child task/run IDs and fan in under one parent response.

- Presentation output is native PPTX. Optional PPT Master intake enriches
  uploaded PPTX source content without executing arbitrary slide code.
- Infographic output is validated AntV syntax and optionally rendered to SVG
  through the checked-in Node SSR bridge.
- Video defaults to the in-process native generator. If
  `MONEYPRINTERTURBO_BASE_URL` is set, the adapter uses the upstream
  MoneyPrinterTurbo task API and returns `pending` while the provider job is
  running. Provider-pending is not treated as human approval.
- Human approval is entered only when an adapter returns `pending` with an
  approval resume seam or explicitly sets `human_approval_required=true`.

## NTRO deployment checklist

- Put Cognee and model/provider services behind the approved government
  network boundary; do not expose them to the browser.
- Replace header-only operator identity with the deployment's authenticated
  gateway/SSO identity and pass the verified operator/case claims into this
  service.
- Use approved encrypted-at-rest storage for the LangGraph checkpoint,
  progress-event, and audit databases. The local SQLite files are a
  single-instance deployment default.
- Set a strict CORS allow-list and terminate TLS at the approved gateway.
- Keep `CREWAI_DISABLE_TELEMETRY=true` unless telemetry is explicitly cleared.
- Configure `SUDARSHAN_LOAD_PLUGINS=true` only when the installed entry points
  are allow-listed and reviewed.
- Persist artifacts in an approved controlled store before production use;
  `artifacts/` is a local development default.
- Run the live Cognee, model, provider, artifact-store, and Harness smoke
  tests in the deployment environment with synthetic/non-sensitive data.

## Verification

```powershell
$env:UV_CACHE_DIR = (Join-Path (Get-Location) '.uv-cache')
uv lock --check
uv run pytest -q --basetemp .pytest-tmp-run -p no:cacheprovider
node deepseek-harness/node_modules/typescript/bin/tsc -b deepseek-harness/tsconfig.host.json
node deepseek-harness/node_modules/typescript/bin/tsc -b deepseek-harness/tsconfig.client.json
git diff --check
```

The upstream patterns used by the adapters are documented at [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo), [PPT Master](https://github.com/hugohe3/ppt-master), and [AntV Infographic](https://github.com/antvis/infographic).
