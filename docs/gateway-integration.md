# Node gateway integration contract

The Node/Express service in backend-node/ is the browser-facing gateway. It
owns authentication, user and case ownership, MongoDB task records, token and
request quotas, idempotency, request IDs, and safe forwarding to the Python
application.

The browser must call this gateway. It must not call Cognee, OpenAI, CrewAI,
MoneyPrinterTurbo, or Python pipeline modules directly.

## Service boundary

@@@text
Reference frontend
  -> Node/Express gateway
       authentication, cookies, cases, quotas, idempotency, task API
  -> Python FastAPI
       SudarshanApplication, LangGraph, memory, pipelines, artifacts
  -> Cognee and providers
       backend-only dependencies
@@@

The gateway does not implement a second pipeline router. It forwards a
validated transformation request to Python POST /runs and projects the safe
result back to the browser.

## Local configuration

Copy the root environment template and configure:

@@@dotenv
NODE_ENV=development
PORT=8080
MONGODB_URI=mongodb+srv://<user>:<password>@<cluster>.mongodb.net/sudarshan_gateway?retryWrites=true&w=majority
MONGODB_DB_NAME=sudarshan_gateway
PYTHON_API_BASE_URL=http://localhost:8000
PYTHON_API_TIMEOUT_MS=30000
FRONTEND_URL=http://localhost:3000
GOOGLE_CLIENT_ID=<web-client-id>
GOOGLE_CLIENT_SECRET=<web-client-secret>
GOOGLE_CALLBACK_URL=http://localhost:8080/api/v1/auth/google/callback
JWT_ACCESS_SECRET=<long-random-secret>
JWT_REFRESH_SECRET=<different-long-random-secret>
CORS_ORIGINS=http://localhost:3000,http://localhost:5173
COOKIE_SECURE=false
COOKIE_SAME_SITE=lax
TOKEN_LIMIT_PER_MINUTE=20000
TOKEN_LIMIT_PER_DAY=200000
REQUEST_LIMIT_PER_MINUTE=30
@@@

The callback URL must be registered exactly in Google Cloud Console. Use
HTTPS, secure cookies, and deployment-specific origins in production.

Start the gateway independently for debugging:

@@@powershell
Push-Location backend-node
npm start
Pop-Location
@@@

The normal local command remains startup.ps1 because it starts Python, Node,
and the static frontend together.

## Health and authentication routes

| Method | Route | Auth | Purpose |
| --- | --- | --- | --- |
| GET | /healthz | no | Node process liveness |
| GET | /readyz | no | MongoDB readiness |
| GET | /api/v1/health | no | MongoDB and Python health projection |
| GET | /api/v1/auth/google | no | start Google OAuth |
| GET | /api/v1/auth/google/callback | Google | finish login and issue cookies |
| POST | /api/v1/auth/refresh | refresh cookie | rotate access/refresh session |
| GET | /api/v1/auth/me | access cookie/token | current user |
| POST | /api/v1/auth/logout | access cookie/token | revoke session |

Tokens are delivered as HttpOnly cookies. Browser requests must use
credentials: include. Frontend code must not read or persist refresh tokens.

@@@javascript
window.location.assign(
  "http://localhost:8080/api/v1/auth/google"
);
@@@

## Case routes

| Method | Route | Auth | Purpose |
| --- | --- | --- | --- |
| POST | /api/v1/cases | required | create a user-owned case |
| GET | /api/v1/cases | required | list the current user's cases |

Every transformation verifies that the authenticated user owns the supplied
case. A user cannot use another user's case_id.

A case includes a classification level and distribution marking. These values
must remain visible in the UI and be carried into the Python request.

## Transformation route

The primary browser route is POST /api/v1/transform. It accepts authenticated
input data and selected output types, creates an idempotent gateway task, and
forwards the common request contract to Python.

A typical request contains:

@@@json
{
  "user_id": "operator-1",
  "case_id": "case-42",
  "task_id": "task-42",
  "input": {
    "query": "Create an executive summary of the case"
  },
  "output_types": ["executive_summary"],
  "classification_level": "RESTRICTED",
  "distribution": "Authorized NTRO personnel"
}
@@@

The gateway maps output_types to registered Python pipelines, preserves the
case/task identity, and never sends provider keys or raw memory from the
browser. Use Idempotency-Key for retry-safe task creation.

Transformation tasks support:

- asynchronous creation and task polling;
- optional wait=true long-poll delivery;
- selected multi-output pipelines;
- resume for clarification or approval;
- cooperative cancellation;
- SSE progress proxying;
- input/output token accounting.

## Task status and progress

| Method | Route | Purpose |
| --- | --- | --- |
| GET | /api/v1/tasks/{task_id} | task projection |
| GET | /api/v1/tasks/{task_id}?wait=true | bounded long-poll |
| GET | /api/v1/tasks/{task_id}/events | SSE progress proxy |
| POST | /api/v1/tasks/{task_id}/resume | clarification or approval |
| POST | /api/v1/tasks/{task_id}/cancel | cooperative cancellation |

Always preserve task_id and run_id after creation. If the browser loses a
response, poll the existing task before submitting a new request.

Terminal statuses are succeeded, partial, failed, and cancelled. pending means
an external provider is still working. waiting_for_input and
waiting_for_approval require a user action.

## Browser security rules

- Use the authenticated gateway identity; never trust a free-text operator ID.
- Send credentials: include on cookie-authenticated requests.
- Do not expose Google secrets, JWTs, MongoDB credentials, provider keys,
  Cognee context, raw prompts, or model reasoning.
- Use strict CORS origins; never use wildcard origins with credentials.
- Escape output and artifact metadata before rendering.
- Display classification and distribution with every artifact preview.
- Disable duplicate submit while a request is queued, but recover by task_id.
- Use HTTPS and secure cookies outside local development.
- Treat every artifact URI and model-produced string as untrusted display data.

## Error handling

| Status | Meaning | Browser action |
| --- | --- | --- |
| 401 | missing or expired identity | authenticate or refresh |
| 403 | identity/case ownership mismatch | stop and show authorization error |
| 404 | task or case not found | refresh state and verify identity |
| 409 | idempotency or state conflict | reuse the existing task state |
| 413 | source or request too large | ask for a smaller input |
| 422 | validation failure | show field-level error |
| 502 | Python/provider/memory failure | show retry/support state |
| 503 | MongoDB or Python service unavailable | show service-unavailable state |
| network timeout | delivery uncertain | poll the existing task before retry |

Never blindly retry a transformation after a network timeout. The gateway may
already have created the task. Poll using the stored task_id or Idempotency-Key.

## MongoDB Atlas startup requirement

startup.ps1 resolves the MongoDB SRV record and runs the gateway database
initializer. Before running it:

1. add the current public IP to Atlas Network Access;
2. create a database user with the required permissions;
3. URL-encode special characters in the URI password;
4. confirm DNS/VPN/firewall permits SRV lookup;
5. verify the cluster hostname is copied from Atlas.

If MongoDB is unavailable, use startup.ps1 -SkipNodeGateway only for Python
pipeline development. The gateway's authentication, cases, quotas, and task
records are not available in that mode.

## Verification

From the repository root:

@@@powershell
Push-Location backend-node
npm test
npm run check
Pop-Location
@@@

The gateway tests are deterministic and do not prove live Google OAuth or
MongoDB reachability. A deployment smoke test must call health, readiness,
Google login, case creation, transformation creation, task polling, and
logout with intentionally configured services.

