# Frontend Handoff: Sudarshan Node Gateway

This guide describes how a frontend integrates with the production-facing
Node/Express gateway in `backend-node/`.

The gateway is the browser-facing service. It owns Google OAuth2, user and
case ownership, MongoDB Atlas task records, token accounting, rate limiting,
idempotency, and safe delivery of transformed outputs. It forwards generation
requests to the existing Python FastAPI service, which remains the source of
truth for memory policy, routing, pipeline execution, approval, cancellation,
and artifact generation.

```text
Frontend
  -> Node/Express gateway : authentication, ownership, quotas, task API
  -> Python FastAPI       : SudarshanApplication / LangGraph / pipelines
  -> Cognee and providers : backend-only services
```

The frontend must never call Cognee, CrewAI, OpenAI, MoneyPrinterTurbo, or the
Python pipeline modules directly.

The repository includes a working dependency-free reference frontend in
`frontend/`. Serve it over HTTP with `python -m http.server 3000 --directory
frontend` and open `http://localhost:3000/login.html`. It uses `api.js` for
cookie-authenticated gateway requests, `login.js` for Google OAuth, and
`script.js` for cases, multi-output submission, task polling, cancellation,
and safe output rendering. Do not open the HTML files with `file://`, because
browser cookies and CORS require an HTTP origin.

## 1. Services and local startup

The canonical local command installs dependencies, initializes the MongoDB
Atlas schema/indexes, warms the orchestrator and pipeline registry, and starts
all three local services:

```powershell
Copy-Item .env.example .env # only needed once; fill the required values
pwsh -NoProfile -ExecutionPolicy Bypass -File .\startup.ps1
```

Use `-NoStart` when only dependency installation and database initialization are
needed. Manual service commands remain useful for debugging individual logs.

The default URLs are:

```text
Node gateway: http://localhost:8080
Python API:   http://localhost:8000
```

The repository-wide dependency command installs the Python environment, the
AntV renderer, the DeepSeek Harness, and the Node gateway dependencies:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\startup.ps1
```

Configure every local service from the unified root `.env` file. Copy
`.env.example` to `.env` and provide the same variables through the deployment
environment in production.

Required local gateway configuration:

```dotenv
NODE_ENV=development
MONGODB_URI=mongodb+srv://<user>:<password>@<cluster>.mongodb.net/sudarshan_gateway?retryWrites=true&w=majority
MONGODB_DB_NAME=sudarshan_gateway
FRONTEND_URL=http://localhost:3000
GOOGLE_CLIENT_ID=<client-id>
GOOGLE_CLIENT_SECRET=<client-secret>
GOOGLE_CALLBACK_URL=http://localhost:8080/api/v1/auth/google/callback
JWT_ACCESS_SECRET=<long-random-secret>
JWT_REFRESH_SECRET=<different-long-random-secret>
PYTHON_API_BASE_URL=http://localhost:8000
CORS_ORIGINS=http://localhost:3000,http://localhost:5173
```

In Google Cloud Console, create a Web application OAuth client and add the
exact `GOOGLE_CALLBACK_URL` to the authorized redirect URIs. The callback URL
must be HTTPS in production.

## 2. Browser authentication

The gateway uses Google OpenID Connect through Google OAuth2. On a successful
callback it upserts the user in MongoDB Atlas using Google's stable `sub`
claim, issues a short-lived access token and a rotating refresh token, and
stores the refresh-token hash in MongoDB.

Tokens are delivered as `HttpOnly` cookies. The browser should use
`credentials: "include"` on gateway requests. Frontend JavaScript should not
read or persist the refresh token.

### Start login

Navigate the browser to:

```text
GET http://localhost:8080/api/v1/auth/google
```

Example frontend function:

```ts
export function signInWithGoogle(apiOrigin: string) {
  window.location.assign(`${apiOrigin}/api/v1/auth/google`);
}
```

Google redirects to `GOOGLE_CALLBACK_URL`. The gateway sets the auth cookies
and redirects to `FRONTEND_URL`.

### Get the current user

```ts
export async function getCurrentUser(apiOrigin: string) {
  const response = await fetch(`${apiOrigin}/api/v1/auth/me`, {
    credentials: "include",
  });
  if (response.status === 401) return null;
  if (!response.ok) throw await readApiError(response);
  return response.json();
}
```

Response:

```json
{
  "user": {
    "id": "66...",
    "email": "operator@example.com",
    "email_verified": true,
    "name": "Operator Name",
    "picture": "https://...",
    "roles": ["user"]
  }
}
```

### Refresh an expired access token

```ts
export async function refreshSession(apiOrigin: string) {
  const response = await fetch(`${apiOrigin}/api/v1/auth/refresh`, {
    method: "POST",
    credentials: "include",
  });
  if (!response.ok) throw await readApiError(response);
  return response.json();
}
```

The gateway rotates the refresh token. A reused refresh token is rejected, so
the frontend should not retry refresh requests concurrently.

### Log out

```ts
export async function logout(apiOrigin: string) {
  const response = await fetch(`${apiOrigin}/api/v1/auth/logout`, {
    method: "POST",
    credentials: "include",
  });
  if (!response.ok && response.status !== 401) throw await readApiError(response);
}
```

## 3. Gateway API conventions

All application routes below are prefixed with `/api/v1`.

Send cookies on every request:

```ts
const requestOptions = { credentials: "include" as const };
```

For bearer-token clients, the short-lived access token returned by refresh may
also be sent as:

```text
Authorization: Bearer <access-token>
```

Every response includes `X-Request-Id`. Include it in support logs. Do not send
provider credentials, model keys, arbitrary operator identities, or raw memory
context from the browser.

## 4. Endpoint reference

### Public health endpoints

| Method | Endpoint | Auth | Purpose |
| --- | --- | --- | --- |
| `GET` | `/healthz` | No | Node process liveness |
| `GET` | `/readyz` | No | MongoDB readiness |
| `GET` | `/api/v1/health` | No | MongoDB plus Python API health |

`/readyz` returns `503` until MongoDB Atlas is connected. The gateway health
endpoint returns `503` if the Python service is unavailable.

### Authentication endpoints

| Method | Endpoint | Auth | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/v1/auth/google` | No | Begin Google OAuth2 |
| `GET` | `/api/v1/auth/google/callback` | No | Complete OAuth2 and create/update user |
| `POST` | `/api/v1/auth/refresh` | Refresh cookie | Rotate tokens |
| `GET` | `/api/v1/auth/me` | Access token/cookie | Return current user |
| `POST` | `/api/v1/auth/logout` | Access token/cookie | Revoke refresh token and clear cookies |

### User case endpoints

| Method | Endpoint | Auth | Purpose |
| --- | --- | --- | --- |
| `POST` | `/api/v1/cases` | Required | Create a user-owned case |
| `GET` | `/api/v1/cases` | Required | List the current user's cases |

Create a case:

```ts
await fetch(`${apiOrigin}/api/v1/cases`, {
  method: "POST",
  credentials: "include",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    case_id: "case-42",
    name: "Maritime Activity Assessment",
    classification_level: "RESTRICTED",
    distribution: "Authorized NTRO personnel",
  }),
});
```

Response: `201 Created`.

```json
{
  "case_id": "case-42",
  "name": "Maritime Activity Assessment",
  "classification_level": "RESTRICTED",
  "distribution": "Authorized NTRO personnel"
}
```

The gateway verifies that every transformation task belongs to the
authenticated user's case. A user cannot use another user's `case_id`.

### Transformation endpoint

| Method | Endpoint | Auth | Purpose |
| --- | --- | --- | --- |
| `POST` | `/api/v1/transform` | Required | Queue selected transformations and calculate input tokens |

Request body:

```json
{
  "user_id": "optional-and-must-match-authenticated-user",
  "case_id": "case-42",
  "task_id": "task-summary-42",
  "input": "Create an executive summary focused on maritime activity.",
  "output_types": ["executive_summary"],
  "classification_level": "RESTRICTED",
  "distribution": "Authorized NTRO personnel"
}
```

`input` can be a string, JSON object, or JSON array. The gateway serializes it
to the Python request query. `output_types` accepts one to eight registered
types:

```text
advisory
linkedin_post
executive_summary
infographic
presentation
ppt
video
```

The body `user_id` is optional and never establishes identity. If provided, it
must equal the authenticated user ID. The server creates `task_id` when it is
omitted.

The request is accepted asynchronously by default:

```json
{
  "task_id": "task-summary-42",
  "run_id": "run-...",
  "case_id": "case-42",
  "output_types": ["executive_summary"],
  "status": "queued",
  "result": null,
  "error": null,
  "usage": {
    "input_tokens": 18,
    "output_tokens": 0,
    "total_tokens": 0
  }
}
```

The default HTTP status is `202 Accepted`. Use the returned `task_id` for all
later calls.

To wait for completion in the same HTTP request, add `?wait=true`:

```ts
const response = await fetch(`${apiOrigin}/api/v1/transform?wait=true`, {
  method: "POST",
  credentials: "include",
  headers: {
    "Content-Type": "application/json",
    "Idempotency-Key": "case-42-summary-v1",
  },
  body: JSON.stringify({
    case_id: "case-42",
    input: "Create an executive summary focused on maritime activity.",
    output_types: ["executive_summary"],
  }),
});
```

If all selected pipelines finish before the configured wait timeout, the
response is `200` and contains transformed output in `result`. Otherwise it
returns `202` and the frontend should poll the task endpoint.

### Task status and transformed output

| Method | Endpoint | Auth | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/v1/tasks/{task_id}` | Required | Read task status, output, and token usage |
| `GET` | `/api/v1/tasks/{task_id}/events` | Required | Stream Python progress events through the gateway |
| `POST` | `/api/v1/tasks/{task_id}/resume` | Required | Answer clarification/approval input |
| `POST` | `/api/v1/tasks/{task_id}/cancel` | Required | Request cooperative cancellation |

Completed task response:

```json
{
  "task_id": "task-summary-42",
  "run_id": "run-...",
  "case_id": "case-42",
  "output_types": ["executive_summary"],
  "status": "succeeded",
  "result": {
    "executive_summary": {
      "status": "succeeded",
      "pipeline": "executive_summary",
      "task_id": "task-summary-42-executive_summary",
      "run_id": "run-...",
      "output": {},
      "artifact": null,
      "failure": null,
      "attempts": 1,
      "metadata": {}
    }
  },
  "error": null,
  "usage": {
    "input_tokens": 18,
    "output_tokens": 412,
    "total_tokens": 430
  }
}
```

For multiple output types, `result` contains one key per pipeline. Do not use
only the first output; partial successes are preserved.

Polling helper:

```ts
export async function getTask(apiOrigin: string, taskId: string) {
  const response = await fetch(
    `${apiOrigin}/api/v1/tasks/${encodeURIComponent(taskId)}`,
    { credentials: "include" },
  );
  if (!response.ok) throw await readApiError(response);
  return response.json();
}
```

### Progress events

The task events endpoint proxies the Python SSE stream:

```ts
export function subscribeToTask(
  apiOrigin: string,
  taskId: string,
  onProgress: (event: unknown) => void,
) {
  const source = new EventSource(
    `${apiOrigin}/api/v1/tasks/${encodeURIComponent(taskId)}/events`,
    { withCredentials: true },
  );
  source.addEventListener("progress", (message) => {
    onProgress(JSON.parse((message as MessageEvent).data));
  });
  source.addEventListener("error", () => source.close());
  return () => source.close();
}
```

Progress events contain safe fields such as `run_id`, `task_id`, `pipeline`,
`stage`, `status`, `progress`, `message`, `requires_action`, `artifact_id`,
`error_code`, and `timestamp`. They do not contain raw memory, prompts,
credentials, or model reasoning.

Terminal states are `succeeded`, `partial`, `failed`, and `cancelled`.
`pending` means an external provider job may still be running. `waiting_for_input`
and `waiting_for_approval` require a resume action.

### Resume clarification or approval

Clarification:

```ts
await fetch(`${apiOrigin}/api/v1/tasks/${taskId}/resume`, {
  method: "POST",
  credentials: "include",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    answer: "Create an advisory focused on the case decision.",
  }),
});
```

Approval:

```json
{
  "decision": "approved",
  "reviewer_id": "<authenticated-user-id>",
  "comment": "Approved for authorized release"
}
```

The gateway supplies the task ID and authenticated user identity when it calls
the Python service. The Python boundary verifies that `reviewer_id`, when
provided, matches the authenticated operator identity.

### Cancel a task

```ts
await fetch(`${apiOrigin}/api/v1/tasks/${taskId}/cancel`, {
  method: "POST",
  credentials: "include",
});
```

Cancellation is cooperative. A provider call already in progress may finish
before the Python orchestrator observes cancellation.

### Usage endpoint

```text
GET /api/v1/usage
```

Returns aggregate persisted usage for the authenticated user:

```json
{
  "input_tokens": 1200,
  "output_tokens": 3400,
  "total_tokens": 4600,
  "requests": 12
}
```

## 5. Token accounting and rate limiting

The gateway counts tokens before forwarding a request and after the Python
service returns transformed output. It uses the `js-tiktoken` encoder with a
`gpt-4o-mini` encoding and falls back to `cl100k_base` if required.

- Input tokens are counted from the serialized `input` value.
- Output tokens are counted from the safe transformed `result` envelope.
- `total_tokens = input_tokens + output_tokens`.
- Usage is stored on the MongoDB task document.
- Responses include `X-Input-Tokens`, `X-Output-Tokens`, and
  `X-Total-Tokens` headers.

Before forwarding, the gateway reserves the configured maximum output budget
so concurrent requests cannot all bypass quota while their outputs are still
unknown. Default limits are configured in the root `.env.example`:

```dotenv
TOKEN_LIMIT_PER_MINUTE=20000
TOKEN_LIMIT_PER_DAY=200000
REQUEST_LIMIT_PER_MINUTE=30
MAX_RESERVED_OUTPUT_TOKENS=12000
```

The counters are MongoDB-backed fixed-window buckets, so multiple Node gateway
instances share quota state. A rejected request returns `429` and a
`Retry-After` header. The frontend should display a rate-limit message and
wait; it should not blindly retry a transformation with a new task ID.

## 6. Idempotency and retries

Send an `Idempotency-Key` for user actions that must not create duplicate
tasks, for example:

```text
Idempotency-Key: case-42-summary-v1
```

The key is scoped to the authenticated user and stored in MongoDB. Repeating
the same request returns the existing task instead of submitting another
Python run. Preserve the returned task/run identity across browser refreshes
and network timeouts.

Recommended frontend behavior:

1. Generate one idempotency key when the user presses Generate.
2. Disable duplicate submission while the request is in flight.
3. If the response is lost, repeat the same request with the same key.
4. Poll the returned task before deciding whether another request is needed.

## 7. Error handling

The gateway returns JSON errors with `error` and `request_id` fields.

| Status | Meaning | Frontend action |
| --- | --- | --- |
| `400` | Invalid OAuth callback or request | Show validation/authentication error |
| `401` | Missing/expired authentication | Refresh once, then send user to Google login |
| `403` | User/case/reviewer mismatch | Stop and show authorization error |
| `404` | Case or task is not owned by user | Do not reveal another user's data |
| `409` | Duplicate case/task or task not yet proxied | Refresh current resource |
| `422` | Invalid body or unsupported output type | Show field-level validation |
| `429` | Token/request quota exceeded | Respect `Retry-After` |
| `500` | Gateway internal failure | Show request ID and support state |
| `502`/`503` | Python, MongoDB, or provider dependency unavailable | Show retry/support state |

Example error reader:

```ts
export async function readApiError(response: Response) {
  let payload: { error?: string; request_id?: string } = {};
  try { payload = await response.json(); } catch { /* keep fallback */ }
  return new Error(
    `${payload.error ?? `Request failed (${response.status})`} [${payload.request_id ?? "no-request-id"}]`,
  );
}
```

## 8. Security requirements for production

- Use HTTPS for the frontend, Node gateway, Google callback, and Python
  service-to-service connection.
- Set `NODE_ENV=production`, strong independent JWT secrets, and
  `COOKIE_SECURE=true`.
- Set `COOKIE_SAME_SITE=none` only when the frontend and gateway are on
  different sites and HTTPS is enabled.
- Restrict `CORS_ORIGINS` to exact trusted frontend origins.
- Keep MongoDB Atlas network access restricted to the gateway deployment and
  use a least-privilege database user.
- Store secrets in the deployment secret manager, not `.env` committed to Git.
- Terminate TLS and apply WAF/API gateway policy at the approved edge.
- Keep Python API access private to the gateway/network boundary.
- Do not trust `user_id` from the request body; the Google-authenticated token
  is authoritative.
- Escape returned transformed output and artifact metadata in the frontend.

The Node service is designed to scale horizontally: access tokens are
stateless, refresh-token state/tasks/cases/rate-limit buckets are in MongoDB,
and each task is associated with a durable Python run ID. For high-volume
deployments, place a durable queue/worker layer between `/transform` and the
Python service while preserving the same task and output contracts.

## 9. Backend verification

From the repository root:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\startup.ps1
Set-Location .\backend-node
npm run check
```

From the Python service:

```powershell
Set-Location ..
$env:UV_CACHE_DIR = Join-Path (Get-Location) ".uv-cache"
uv lock --check
uv run pytest -q --basetemp .pytest-tmp-run -p no:cacheprovider
```
