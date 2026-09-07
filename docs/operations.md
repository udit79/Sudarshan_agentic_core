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

## Local setup

@@@powershell
Copy-Item .env.example .env
# Fill .env before starting; never commit it.
pwsh -NoProfile -ExecutionPolicy Bypass -File .\startup.ps1
@@@

The bootstrap installs the locked Python environment, AntV renderer, vendored
DeepSeek Harness workspace, and Node gateway dependencies. It then initializes
MongoDB collections/indexes and starts:

| Service | Default URL | Responsibility |
| --- | --- | --- |
| FastAPI | http://127.0.0.1:8000 | Python application and orchestrator |
| Node gateway | http://127.0.0.1:8080 | OAuth, cases, quotas, browser API |
| Static frontend | http://127.0.0.1:3000 | Login and output UI |

Useful switches:

@@@powershell
.\startup.ps1 -NoStart
.\startup.ps1 -SkipHarness
.\startup.ps1 -SkipNodeGateway
.\startup.ps1 -SkipAntV
.\startup.ps1 -SkipInstall
.\startup.ps1 -OpenBrowser
@@@

For frontend-only work:

@@@powershell
python -m http.server 3000 --directory frontend
Start-Process http://localhost:3000/login.html
@@@

Do not open the frontend with file://; cookies and CORS require an HTTP
origin.

For manual service debugging:

@@@powershell
uv run python -m api.server
Push-Location backend-node; npm start; Pop-Location
python -m http.server 3000 --directory frontend
@@@

## Configuration

.env.example is the authoritative configuration template.

| Group | Variables | Purpose |
| --- | --- | --- |
| Cognee | COGNEE_BASE_URL, COGNEE_API_KEY, COGNEE_TENANT_ID, COGNEE_DATASET_NAME | memory backend |
| Models | CREWAI_MODEL, CREWAI_FAST_MODEL, role-specific model variables | strong/fast CrewAI routing |
| OpenAI media | OPENAI_API_KEY, OPENAI_IMAGE_MODEL, OPENAI_TTS_MODEL, OPENAI_TTS_VOICE | image, speech, video assets |
| Python API | SUDARSHAN_API_HOST, SUDARSHAN_API_PORT, SUDARSHAN_CORS_ORIGINS | orchestrator service |
| State and audit | LANGGRAPH_CHECKPOINT_DB_PATH, CREWAI_FLOW_DB_PATH, SUDARSHAN_AUDIT_DB_PATH | local durable state |
| Gateway | MONGODB_URI, MONGODB_DB_NAME, PYTHON_API_BASE_URL | browser-facing backend |
| Google OAuth | GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_CALLBACK_URL | sign-in |
| Browser security | JWT_ACCESS_SECRET, JWT_REFRESH_SECRET, COOKIE_SECURE, CORS_ORIGINS | sessions and origin policy |
| Optional worker | MONEYPRINTERTURBO_BASE_URL and related variables | legacy asynchronous video mode |

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

Reference frontend:

@@@powershell
node --check frontend\script.js
node --check frontend\api.js
node --check frontend\login.js
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
receives it.

### Video is pending or uses title-card fallbacks

Native video requires OPENAI_API_KEY for images/TTS and local FFmpeg through
imageio-ffmpeg. MONEYPRINTERTURBO_BASE_URL selects the asynchronous
compatibility path. Provider pending means the worker is still running; it is
not a human approval state.

## Deployment requirements

Production deployments should use HTTPS, secure cookies, strict CORS, an
approved SSO identity source, secret management, encrypted durable state,
observability, backups, and provider-specific cancellation/retry policies.
Configure the approved shared state and worker infrastructure for the target
deployment before exposing the system to operational users.
