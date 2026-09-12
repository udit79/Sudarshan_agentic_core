# Operations and deployment guide

This document contains the detailed setup, configuration, service contracts,
testing, troubleshooting, and deployment requirements for Sudarshan Agentic
Core. The root README is intentionally shorter and links here for operational
depth.

## Prerequisites

- Windows PowerShell 7 for the supplied bootstrap script.
- Python 3.13 or newer.
- Node.js compatible with the gateway and Harness lockfiles.
- npm and pnpm available, or permission for the setup script to install them.
- MongoDB Atlas access when the Node gateway is enabled.
- Cognee Cloud or self-hosted endpoint credentials for live memory operations.
- OpenAI credentials for live model and media operations.
- Redis 7+ and the optional Python extra (`pip install -e ".[redis]"`) when
  running more than one scheduler process.

## Local setup

@@@powershell
Copy-Item .env.example .env
# Fill .env before starting; never commit it.
pwsh -NoProfile -ExecutionPolicy Bypass -File .\startup.ps1
@@@

The bootstrap installs the locked Python environment, AntV renderer, Node
gateway, and DeepSeek Harness dependencies. It then initializes MongoDB
collections/indexes and starts:

| Service | Default URL | Responsibility |
| --- | --- | --- |
| FastAPI | http://127.0.0.1:8000 | Python application and orchestrator |
| Node gateway | http://127.0.0.1:8080 | OAuth, cases, quotas, browser API |
| Landing app | http://127.0.0.1:4173 | Public landing, About, and sign-in UI |
| DeepSeek Harness | http://127.0.0.1:3080 | Authenticated application frontend |

When services are started, `startup.ps1` writes
`artifacts/.state/sudarshan-processes.json` containing only service names,
PIDs, ports, and log paths. This is used by shutdown so it stops the processes
started by Sudarshan rather than unrelated applications using the same ports.
The startup also creates the presentation, video, quality-report, and memory
event state directories used by the native renderers and lifecycle layer.

Useful switches:

@@@powershell
.\startup.ps1 -NoStart
.\startup.ps1 -SkipHarness # optional: start backend and landing without Harness
.\startup.ps1 -SkipNodeGateway
.\startup.ps1 -SkipAntV
.\startup.ps1 -SkipInstall
.\startup.ps1 -OpenBrowser
@@@

For frontend-only work:

@@@powershell
npm run dev -- --host 127.0.0.1 --port 4173
Start-Process http://localhost:4173/
@@@

Do not open the frontend with file://; cookies and CORS require an HTTP
origin.

For manual service debugging:

@@@powershell
uv run python -m api.server
Push-Location backend-node; npm start; Pop-Location
Push-Location 'landing page\landing page'; npm run dev -- --host 127.0.0.1 --port 4173; Pop-Location
Push-Location deepseek-harness; node --import tsx/esm apps/cli/src/bin.ts web --no-open --port 3080; Pop-Location
@@@

## Configuration

.env.example is the authoritative configuration template.

| Group | Variables | Purpose |
| --- | --- | --- |
| Cognee Cloud | COGNEE_BACKEND=cloud, COGNEE_BASE_URL, COGNEE_API_KEY, COGNEE_TENANT_ID, COGNEE_DATASET_NAME | tenant-scoped memory backend; local mode is explicit development-only |
| Models | CREWAI_MODEL, CREWAI_FAST_MODEL, role-specific model variables | strong/fast CrewAI routing |
| OpenAI media | OPENAI_API_KEY, OPENAI_IMAGE_MODEL, OPENAI_TTS_MODEL, OPENAI_TTS_VOICE | image, speech, video assets |
| Python API | SUDARSHAN_API_HOST, SUDARSHAN_API_PORT, SUDARSHAN_CORS_ORIGINS | orchestrator service |
| State and audit | LANGGRAPH_CHECKPOINT_DB_PATH, CREWAI_FLOW_DB_PATH, SUDARSHAN_AUDIT_DB_PATH | local durable state |
| Shared control plane | SUDARSHAN_CONTROL_PLANE, SUDARSHAN_REDIS_URL, SUDARSHAN_CONTROL_PLANE_PREFIX | Redis Stream discovery, leases, fencing, idempotency, progress replay, DAG state, and ingestion budgets |
| Object storage | SUDARSHAN_OBJECT_STORE_MODE, SUDARSHAN_OBJECT_STORE_ROOT | restart-safe source/artifact copies and metadata catalog |
| Observability | SUDARSHAN_OBSERVABILITY_DB_PATH, SUDARSHAN_OBSERVABILITY_RETENTION_SECONDS, SUDARSHAN_TELEMETRY_ACCESS_LEVEL | safe telemetry collector, retention, and dashboard clearance |
| Sandbox | SUDARSHAN_SANDBOX_MODE, SUDARSHAN_SANDBOX_RUNTIME, SUDARSHAN_SANDBOX_CONTAINER_IMAGE, SUDARSHAN_ALLOW_LOCAL_SANDBOX | container-backed renderer/validator boundary; local execution is explicit development-only opt-in |
| Gateway | MONGODB_URI, MONGODB_DB_NAME, PYTHON_API_BASE_URL, PYTHON_API_TIMEOUT_MS, PYTHON_INGEST_TIMEOUT_MS | browser-facing backend and Python request/upload timeouts |
| Google OAuth | GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_CALLBACK_URL | sign-in |
| Browser security | JWT_ACCESS_SECRET, JWT_REFRESH_SECRET, COOKIE_SECURE, CORS_ORIGINS | sessions and origin policy |
| Optional worker | MONEYPRINTERTURBO_BASE_URL and related variables | legacy asynchronous video mode |

### Shared scheduler deployment

SQLite is the safe default for one local process. For multiple scheduler
processes, install the optional Redis extra and point every process at the same
Redis instance:

@@@powershell
python -m pip install -e ".[redis]"
$env:SUDARSHAN_CONTROL_PLANE = "redis"
$env:SUDARSHAN_REDIS_URL = "redis://localhost:6379/0"
$env:SUDARSHAN_OBJECT_STORE_MODE = "durable"
@@@

Stop the services through the manifest:

@@@powershell
.\stop-servers.ps1
@@@

If the manifest is missing or stale, inspect the port owners first. The
explicit fallback is available with `-ByPort`:

@@@powershell
.\stop-servers.ps1 -ByPort -Ports 4173,3080,8000,8080
@@@

Use a unique `SUDARSHAN_CONTROL_PLANE_PREFIX` per environment. Redis Streams
provide admission discovery and pending-entry recovery; SQLite remains each
worker's local execution projection. Redis also coordinates cache claims and
run-level and ingestion stage budget reservations. Do not use the Redis mode as
a billing ledger; provider reconciliation is still a separate step.
Artifact storage remains a separate deployment concern.

Durable local object storage keeps immutable source, evidence, and artifact
copies below `SUDARSHAN_OBJECT_STORE_ROOT` and indexes them in its catalog.
For multi-host production set `SUDARSHAN_OBJECT_STORE_MODE=s3`, provide
`SUDARSHAN_OBJECT_STORE_S3_BUCKET` (and optionally endpoint, region, and
prefix), install the boto3 extra used by the deployment, and configure
server-side encryption plus bucket versioning/backup. The adapter downloads
objects into a verified local cache before a renderer reads them.

Set `SUDARSHAN_OBSERVABILITY_EXPORT_URL` to a controlled collector endpoint to
receive the redacted event envelope. The local SQLite chain remains the audit
source; the Redis/HTTP projections are dashboard transport and should not be
treated as immutable audit storage.

OpenAI is the supported native model/media provider. DeepSeek Harness is the
session, MCP, and runtime boundary, not a second model provider. Leave
MONEYPRINTERTURBO_BASE_URL blank for native video generation.

## API surface

### Python application

| Method | Route | Purpose |
| --- | --- | --- |
| GET | /health | readiness and pipeline registry |
| GET | /pipelines | registered pipeline discovery |
| POST | /ingest | authenticated source upload |
| POST | /runs | queue a generation run; returns 202 |
| GET | /runs/{run_id} | safe status and result projection |
| GET | /runs/{run_id}/events | SSE progress stream |
| POST | /runs/{run_id}/resume | clarification or approval resume |
| POST | /runs/{run_id}/cancel | cooperative cancellation |

All mutating Python API requests require X-Operator-Id. See
backend-integration.md for request bodies, source ingestion, identity rules,
memory behavior, and application-boundary details.

### Node gateway

The browser-facing gateway exposes Google authentication, cases,
transformations, task polling, task resume/cancel, and SSE proxying below the
/api/v1 prefix. See gateway-integration.md for the complete route tables,
cookie rules, MongoDB requirements, idempotency behavior, and errors.

## Live smoke sequence

Run this only after configuring the external services intentionally:

1. GET /health on the Python API.
2. GET /readyz and /api/v1/health on the gateway.
3. Complete Google OAuth through /api/v1/auth/google.
4. Create a case through POST /api/v1/cases.
5. Upload a source through POST /ingest or the gateway upload route.
6. Create a transformation with an Idempotency-Key.
7. Poll the task or subscribe to its SSE events.
8. Resume only when the state is waiting_for_input or waiting_for_approval.
9. Verify the artifact reference and classification marking.
10. Confirm logout and refresh-token rotation.

## Testing

Python application and agentic system:

@@@powershell
.\.venv\Scripts\python.exe -m pytest -q
@@@

Node gateway:

@@@powershell
Push-Location backend-node
npm test
npm run check
Pop-Location
@@@

Landing and Harness frontend checks:

@@@powershell
node --check "landing page\landing page\public\login.js"
@@@

The repository tests are offline and deterministic. They mock provider and
memory calls and do not prove live MongoDB, Cognee, Google OAuth, OpenAI, or
external worker reachability.

## Troubleshooting

### MongoDB Atlas querySrv ECONNREFUSED

The gateway initialization resolves the MongoDB SRV record and creates
collections/indexes. Verify:

1. the current public IP is in Atlas Network Access;
2. the database user, password, cluster hostname, and database name are valid;
3. Windows DNS, VPN, and firewall permit SRV lookups;
4. special characters in the URI password are URL-encoded.

Use startup.ps1 -SkipNodeGateway only for Python pipeline development. That mode
does not provide gateway authentication, cases, quotas, or task records.

### Google OAuth returns 401 or refuses login

Confirm the exact GOOGLE_CALLBACK_URL is registered in Google Cloud Console,
the authorized origin matches FRONTEND_URL, the OAuth client is a Web
application, and the account has a verified email. Inspect the gateway log and
/api/v1/health. Never put OAuth secrets in the frontend.

### Infographic does not render

Run the pinned installation in pipelines/infographic/antv_renderer/ or rerun
startup.ps1. The Python pipeline validates syntax before the Node SSR bridge
receives it. The bridge has a 60-second cold-start budget by default because
the first Node SSR render can take more than 20 seconds on Windows. Override
it with `ANTV_RENDER_TIMEOUT_SECONDS` if the host is slower; a renderer timeout
is distinct from a quality-gate rejection.

The pipeline converts complex JSON-like model layouts to the built-in
`list-grid-simple` AntV template before rendering. This keeps the title, every
evidence ID, source reference, known limitation, and required caveat visible
when a model emits a layout that AntV cannot reliably parse. If a rejected
draft still contains valid syntax, the gateway can render it locally as a
clearly marked draft preview without another model/API call.

### Video is pending or uses title-card fallbacks

Native video requires OPENAI_API_KEY for images/TTS and local FFmpeg through
imageio-ffmpeg. MONEYPRINTERTURBO_BASE_URL selects the asynchronous
compatibility path. Provider pending means the worker is still running; it is
not a human approval state.

### Artifact preview says it is unavailable

Check the task status before testing the artifact URL. Artifacts are released
only after the pipeline's structured-output quality gate succeeds. A failed or
quality-rejected pipeline legitimately has no artifact to serve. In gateway
mode, use the authenticated task route and the parent gateway task ID:

```text
GET /api/v1/tasks/{task_id}/artifacts/{artifact_key}
```

For direct FastAPI development, use the orchestration run ID:

```text
GET /artifacts/{run_id}/{artifact_key}
```

If a video response reports success but the browser still shows nothing, hard
refresh the frontend and confirm that the result contains video artifact
metadata. The native video file is written below
`artifacts/videos/<child_run_id>/`.

### A pipeline fails but the draft is needed for diagnosis

Terminal failures for the executive-summary and infographic pipelines retain
the last structured draft, quality-review issues, attempt counters, token
budget, and gateway token usage. The frontend displays that failed draft in
its normal output tab together with the quality-gate notice; it does not treat
the draft as a released artifact. This makes a failed run inspectable without
silently bypassing the quality gate.

### History is empty after a browser refresh

Gateway task history is stored in MongoDB and loaded through `GET
/api/v1/tasks`. Confirm that the user is authenticated, MongoDB is connected,
and the browser is using the gateway rather than direct FastAPI fallback.
Direct FastAPI mode intentionally does not provide persistent user task
history.

## Deployment requirements

Production deployments should use HTTPS, secure cookies, strict CORS, an
approved SSO identity source, secret management, encrypted durable state,
observability, backups, and provider-specific cancellation/retry policies.
Configure the approved shared state and worker infrastructure for the target
deployment before exposing the system to operational users.
## Windows startup and shutdown

The canonical local bootstrap is `startup.ps1`. It loads the ignored `.env`,
starts the Python API, optional Node gateway, DeepSeek Harness, and the Vite
landing app, and records
the owned process IDs in `artifacts/.state/sudarshan-processes.json`.

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\startup.ps1
```

Useful recovery modes:

```powershell
# Restart only services previously recorded by this checkout.
pwsh -NoProfile -ExecutionPolicy Bypass -File .\startup.ps1 -ForceRestart

# Run the Python/API/frontend bootstrap without Mongo index initialization.
pwsh -NoProfile -ExecutionPolicy Bypass -File .\startup.ps1 -SkipDatabaseInit

# Stop services recorded by startup.ps1; harmless when they are already down.
pwsh -NoProfile -ExecutionPolicy Bypass -File .\stop-servers.ps1
```

`-SkipDatabaseInit` is for local debugging only; the Node gateway still needs a
reachable MongoDB when it is started. The optional DeepSeek Harness is not
installed or started unless `-EnableHarness` is supplied. If startup exits with
status 1, it now prints the failing service's stderr tail and the log folder;
check those logs before retrying. Do not use `stop-servers.ps1 -ByPort` unless
you have verified that the listeners belong to Sudarshan.
