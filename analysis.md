# Sudarshan Agentic Core Backend Analysis

This document describes the backend currently implemented in this repository.
It is the practical companion to `docs/backend-integration.md` and
`docs/frontend-integration.md`.

## 1. What is completed

### Application boundary

`integrations/deepseek_harness/application.py` provides the single trusted
application boundary used by both the HTTP API and the DeepSeek Harness. It
owns one process-scoped orchestrator, validates requests, preserves durable
run IDs, and exposes run, status, resume, cancel, memory, health, and ingestion
operations.

Backend callers should use this boundary rather than importing a pipeline crew,
calling Cognee directly, or duplicating routing logic.

### Node/Express production gateway

`backend-node/` is the browser-facing service. It adds the production
application concerns around the Python transformation service:

- Google OAuth2/OpenID Connect login and automatic MongoDB user upsert;
- short-lived access cookies and rotating, revocable refresh tokens;
- MongoDB Atlas-backed users, cases, tasks, OAuth state, and rate-limit buckets;
- authenticated case ownership and task isolation;
- an `/api/v1/transform` contract accepting identity, input data, and selected
  output types;
- asynchronous task polling with optional `?wait=true` output delivery;
- task resume/cancel and proxied SSE progress events;
- `js-tiktoken` input/output token accounting;
- MongoDB-backed token/request quotas shared by gateway instances;
- `Idempotency-Key` protection against duplicate transformations;
- Helmet, strict CORS, request IDs, structured logging, readiness checks, and
  graceful shutdown.

The gateway does not implement a second pipeline router. It forwards
transformation requests to Python `POST /runs`, then reads the safe Python run
projection to return validated transformed outputs.

### HTTP API

`api/server.py` implements the FastAPI service with:

- health and registered-pipeline discovery;
- authenticated source-file ingestion;
- asynchronous run creation;
- durable run status polling;
- server-sent progress events;
- clarification/approval resume;
- cooperative cancellation.

`api/middleware.py` adds:

- `X-Operator-Id` enforcement for all `POST`, `PUT`, and `DELETE` requests;
- classification response headers;
- `nosniff` and HSTS response headers;
- tamper-evident API audit entries without reading or persisting request bodies.

### Orchestration and routing

`pipelines/orchestrator/graph.py` uses LangGraph as the deterministic control
plane. It currently supports:

- bounded User/Case memory recall before request understanding;
- pipeline selection from explicit names or supported natural-language terms;
- clarification interrupts when the request is ambiguous;
- bounded User/Case/Task recall after routing;
- validated prompt-plan generation;
- parallel fan-out for up to eight requested pipelines;
- isolated child task/run identities for multi-pipeline requests;
- fan-in with `succeeded`, `partial`, `failed`, `pending`, and `cancelled`
  parent statuses;
- approval and clarification resume seams;
- cooperative cancellation;
- durable SQLite LangGraph checkpoints by default;
- optional reviewed plugin loading through the `sudarshan.pipelines` entry
  point group.

The default registered pipelines are:

| Name | Purpose | Delivery |
| --- | --- | --- |
| `advisory` | Case-grounded advisory/assessment | Structured advisory output |
| `linkedin_post` | Professional LinkedIn content | Structured post, optional image asset |
| `executive_summary` | Executive case summary | Structured summary |
| `infographic` | Validated visual summary | Structured data, optional SVG rendering |
| `presentation` | Case briefing deck | Native PPTX artifact |
| `ppt` | Legacy alias for presentation | Native PPTX artifact |
| `video` | Case briefing video | Native local video or optional provider job |

### Pipeline and provider boundaries

Each pipeline owns its CrewAI agents, output schema, quality gate, rendering,
and validated Case-memory write-back. The central router only sees the stable
`PipelineAdapter`/`PipelineResponse` contract.

The video pipeline uses the in-process native generator by default. If
`MONEYPRINTERTURBO_BASE_URL` is configured, it calls the external worker only
through `integrations/providers/moneyprinterturbo/client.py`. Provider-pending
jobs remain `pending` and are not treated as human approval.

### Memory and ingestion

The memory layer is implemented in `memory/`:

- `MemoryManager` is the only Cognee boundary;
- User, Case, and Task scopes are enforced through `AccessContext`;
- memory writes carry source and provenance metadata;
- recalls are bounded by `top_k` and token budget;
- a local `MemoryStore` provides domain/idempotency caching;
- `CogneeHttpAdapter` owns Cognee REST payloads, headers, retries, and errors.

`ingestion_pipelines/` supports text, PDF, image, PPTX-family, and video
sources. Uploads are streamed to a bounded temporary file, extracted, converted
to a `KnowledgeUnit`, written to Case memory, audited, and deleted.

### Security, policy, and audit

The backend currently provides:

- classification normalization to `UNCLASSIFIED`, `RESTRICTED`,
  `CONFIDENTIAL`, `SECRET`, or `TOP SECRET`;
- distribution metadata and handling instructions;
- recursive output sanitization for AI/tool/prompt self-references;
- removal of forbidden response metadata such as API keys, raw memory, and
  chain-of-thought fields;
- operator/user and operator/case identity checks at the HTTP boundary;
- SHA-256 integrity hashes for local audit records;
- audit records for API requests, ingestion, run start/completion, approval,
  and cancellation.

The local SQLite stores are development/single-instance defaults. Production
deployments must replace them with approved durable, encrypted storage and an
authenticated gateway/SSO identity source.

### Harness/MCP integration

`integrations/deepseek_harness/mcp_server.py` exposes:

- `run_sudarshan`
- `get_sudarshan_status`
- `resume_sudarshan`
- `cancel_sudarshan`
- `get_sudarshan_health`
- `list_sudarshan_pipelines`
- `remember_sudarshan_context`
- `recall_sudarshan_context`

The local JSONL bridge is available through
`integrations/deepseek_harness/runner.py`. The Harness does not receive Cognee
credentials, provider credentials, raw memory, or model reasoning.

### Dependency bootstrap and verification

`startup.ps1` is now the canonical one-command setup/start script. It installs
dependencies, initializes MongoDB Atlas collections/indexes, warms the
orchestrator registry, and starts the Python API, Node gateway, and static
frontend. It installs:

1. the locked Python environment through `uv sync --locked`;
2. the pinned AntV infographic renderer through `npm ci`;
3. the vendored DeepSeek Harness workspace through `pnpm install
   --frozen-lockfile`;
4. the Node/Express gateway through `npm ci`.

`setup.ps1` remains as a compatibility alias. The current repository test
  baseline is `90 passed, 1 skipped`; the Node gateway also has four focused
validation/token tests.

## 2. HTTP API endpoints

The default server listens on `http://localhost:8000`.

All mutating endpoints require:

```text
X-Operator-Id: <authenticated operator ID>
```

The following headers are also supported:

```text
X-Case-Id: <case ID>
X-Classification-Level: RESTRICTED
```

The case and classification headers provide defaults. If a JSON/form identity
is supplied, it must not conflict with the authenticated header identity.

### `GET /health`

Returns the application readiness projection and registered pipelines.

Example response:

```json
{
  "status": "ok",
  "memory_system": "connected",
  "registered_pipelines": 7,
  "pipelines": [
    "advisory",
    "linkedin_post",
    "executive_summary",
    "infographic",
    "presentation",
    "ppt",
    "video"
  ],
  "routing_engine": "langgraph"
}
```

This is an operational projection; it confirms that the application and
registry initialize. It does not replace a deployment-specific live Cognee,
model, provider, or artifact-store smoke test.

### `GET /pipelines`

Returns the pipeline names currently registered by the application.

```json
{
  "pipelines": ["advisory", "linkedin_post", "executive_summary", "infographic", "presentation", "ppt", "video"]
}
```

### `POST /ingest`

Accepts `multipart/form-data` with a required `file` field.

Optional form fields:

| Field | Meaning | Default |
| --- | --- | --- |
| `user_id` | Must equal `X-Operator-Id` | Operator ID |
| `case_id` | Case receiving the source | `X-Case-Id` |
| `task_id` | Ingestion task identity | Generated |
| `classification_level` | NTRO classification | `RESTRICTED` |

Supported extensions are `.txt`, `.pdf`, common image formats, PPTX-family
formats, and `.mp4`, `.mov`, `.avi`, `.mkv`, `.webm`. The default maximum upload
size is 50 MiB and is configured with `SUDARSHAN_MAX_INGEST_BYTES`.

PowerShell example:

```powershell
$headers = @{
  "X-Operator-Id" = "operator-1"
  "X-Case-Id" = "case-42"
  "X-Classification-Level" = "RESTRICTED"
}
$form = @{
  file = Get-Item .\sample_data\sample_text.txt
  task_id = "ingest-case-42"
}
Invoke-RestMethod http://localhost:8000/ingest -Method Post -Headers $headers -Form $form
```

Successful response: `201 Created`.

```json
{
  "status": "succeeded",
  "document_id": "doc-...",
  "source_reference": "sample_text.txt",
  "doc_type": "text",
  "user_id": "operator-1",
  "case_id": "case-42",
  "task_id": "ingest-case-42",
  "classification_level": "RESTRICTED",
  "content_characters": 1234,
  "memory_persisted": true,
  "ingested_at": "2026-09-06T00:00:00+00:00"
}
```

The raw extracted source is not returned. Common errors are `401` missing
operator identity, `403` identity mismatch, `413` oversized upload, `415`
unsupported extension, `422` invalid input, and `502` extraction or memory
failure.

### `POST /runs`

Validates and queues an advisory request. It returns `202 Accepted`; execution
continues through the application boundary and LangGraph.

Request body:

```json
{
  "query": "Create an executive summary of the case",
  "user_id": "operator-1",
  "case_id": "case-42",
  "task_id": "task-summary-42",
  "classification_level": "RESTRICTED",
  "distribution": "Authorized NTRO personnel",
  "requested_pipelines": ["executive_summary"],
  "metadata": {}
}
```

`requested_pipelines` may be empty when the router should infer the output
from the query. Explicit pipeline names must be present in `GET /pipelines`.
Multiple names run in parallel and return isolated child results under one
parent run.

Accepted response:

```json
{
  "status": "queued",
  "run_id": "run-...",
  "task_id": "task-summary-42",
  "pipeline": null,
  "pipelines": ["executive_summary"]
}
```

Always preserve `run_id`; it is required for polling, SSE, resume, and cancel.

### `GET /runs/{run_id}`

Returns frontend-safe durable state. It includes stage, status, selected
pipelines, clarification questions, errors, and ordered progress events. It
does not return raw Cognee context, prompts, credentials, or model reasoning.

Possible status values include `queued`, `running`, `waiting_for_input`,
`waiting_for_approval`, `pending`, `succeeded`, `partial`, `failed`,
`cancelled`, and `not_found`.

### `GET /runs/{run_id}/events`

Returns an SSE stream with `Content-Type: text/event-stream`.

Progress events are sent as:

```text
event: progress
data: {"event_id":"evt-...","run_id":"run-...","task_id":"task-...","pipeline":"executive_summary","stage":"memory_recall","status":"running","progress":40,"message":"Recalled permitted memory records","requires_action":false,"artifact_id":null,"error_code":null,"timestamp":"..."}

```

The stream may also send `heartbeat` and `error` events. The parent stream
closes after `completed`, `failed`, or `cancellation`. A provider `pending`
state is not automatically an approval request.

### `POST /runs/{run_id}/resume`

Resumes a clarification or approval interrupt for the same run and task.

Clarification example:

```powershell
$headers = @{ "X-Operator-Id" = "operator-1" }
$body = @{ task_id = "task-clarify-42"; answer = "Create an advisory focused on the case decision." } |
  ConvertTo-Json
Invoke-RestMethod http://localhost:8000/runs/run-42/resume -Method Post `
  -Headers $headers -ContentType "application/json" -Body $body
```

Approval example:

```json
{
  "task_id": "task-42",
  "decision": "approved",
  "reviewer_id": "reviewer-1",
  "comment": "Approved for authorized release"
}
```

When `reviewer_id` is supplied, it must equal the authenticated
`X-Operator-Id`. The gateway remains responsible for the reviewer's actual
authorization.

### `POST /runs/{run_id}/cancel`

Requests cooperative cancellation.

```powershell
$headers = @{ "X-Operator-Id" = "operator-1" }
$body = @{ task_id = "task-42" } | ConvertTo-Json
Invoke-RestMethod http://localhost:8000/runs/run-42/cancel -Method Post `
  -Headers $headers -ContentType "application/json" -Body $body
```

The response status is one of `requested`, `cancelled`, `already_terminal`,
or `not_found`. A provider call already in progress may finish before the
orchestrator observes cancellation at its next safe boundary.

## 3. How to run the backend

### Prerequisites

- PowerShell 7 or Windows PowerShell with script execution allowed;
- Python 3.13 or newer;
- Node.js LTS/npm;
- network access for the initial dependency installation;
- a reachable Cognee deployment for real memory operations;
- configured model credentials for generation pipelines.

### Configure the environment

From the repository root:

```powershell
Copy-Item .env.example .env
```

Set at least the MongoDB Atlas, JWT, Google OAuth, Cognee, and model values in `.env`:

```dotenv
COGNEE_BASE_URL=http://localhost:8011
COGNEE_API_KEY=<cognee-key>
COGNEE_DATASET_NAME=sudarshan_memory
OPENAI_API_KEY=<openai-key>
CREWAI_MODEL=openai/gpt-5.4
CREWAI_DISABLE_TELEMETRY=true
```

For Cognee Cloud, also set `COGNEE_TENANT_ID`. Do not commit `.env` or put
credentials in frontend requests, Harness prompts, request metadata, or
artifacts.

### Install all dependencies in one command

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\startup.ps1
```

For a Python-only local check, optional components can be skipped:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\startup.ps1 -SkipAntV -SkipHarness -SkipNodeGateway
```

### Start all local services

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\startup.ps1
```

Use `-NoStart` when only dependency installation and database schema/index
initialization are needed. Startup logs are written to
`artifacts/.state/startup-logs/`.

The host and port can be changed with `SUDARSHAN_API_HOST` and
`SUDARSHAN_API_PORT`. The default is `0.0.0.0:8000`.

### Perform a smoke test

```powershell
$headers = @{ "X-Operator-Id" = "operator-1" }
Invoke-RestMethod http://localhost:8000/health -Headers $headers
Invoke-RestMethod http://localhost:8000/pipelines -Headers $headers
```

### Use the local Harness JSON bridge

After setup, one JSON object can be sent to the trusted Python bridge:

```powershell
'{"query":"Create an executive summary","user_id":"u-1","case_id":"c-1","task_id":"t-1","requested_pipelines":["executive_summary"]}' |
  uv run python -m integrations.deepseek_harness.runner
```

For a registered Harness deployment, use the MCP server configuration in
`integrations/deepseek_harness/sudarshan.cordis.yml`.

## 4. Run lifecycle

The normal lifecycle is:

```text
POST /runs
  -> queued
  -> request memory recall
  -> request understanding/routing
  -> task memory recall
  -> prompt crafting
  -> pipeline execution
  -> completed / pending / failed
```

If the request is ambiguous, the lifecycle pauses at
`waiting_for_input`. Send an answer to `/resume`; the same run refreshes
request memory and routes again.

If an adapter returns a pending result with a resume adapter, the lifecycle
pauses at `waiting_for_approval`. Send an authorized decision to `/resume`.

For multiple pipelines, the parent run remains the client-facing identity and
each child receives its own task/run identity. Read the `responses` map in the
application result rather than assuming the legacy `response` field represents
every child.

## 5. Current deployment limitations

- The default SQLite checkpoint, progress, audit, and CrewAI flow stores are
  intended for local development or a single backend instance.
- The current API uses development header identity. A production gateway must
  provide verified SSO/operator/case claims.
- Provider calls are cooperative-cancellation boundaries; an in-flight
  external call cannot always be force-stopped.
- MoneyPrinterTurbo is optional and remains a separate service when enabled.
- PPT Master is an optional ingestion-enrichment checkout, not a required
  Python dependency.
- Live Cognee, model, provider, artifact-store, and Harness checks require
  intentionally configured synthetic test data and credentials.

## 6. Verification commands

```powershell
$env:UV_CACHE_DIR = Join-Path (Get-Location) ".uv-cache"
uv lock --check
uv run pytest -q --basetemp .pytest-tmp-run -p no:cacheprovider
git diff --check
```

The current deterministic backend suite completes with `90 passed, 1 skipped`.
