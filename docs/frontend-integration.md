# Frontend integration guide

This guide is the frontend-facing contract for Sudarshan Agentic Core. The
frontend is a transport and presentation client: it uploads sources, starts
runs, displays safe progress, renders returned artifacts, and submits user
decisions. It does not call Cognee, CrewAI, OpenAI, provider workers, or the
DeepSeek Harness directly.

The backend contract is defined in
[`docs/backend-integration.md`](backend-integration.md). The internal execution
diagrams are in
[`docs/internal/pipeline-orchestration.md`](internal/pipeline-orchestration.md).

## Frontend responsibility boundary

```mermaid
flowchart LR
    UI[Frontend UI]
    API[FastAPI backend]
    APP[SudarshanApplication]
    ROUTER[LangGraph router]
    PIPE[Pipeline adapters]
    MEM[(Scoped Cognee memory)]

    UI -->|HTTP JSON / multipart| API
    API --> APP --> ROUTER --> PIPE
    APP --> MEM
    PIPE --> MEM
    API -->|safe JSON + SSE| UI
```

The frontend may own layout, filtering of already-safe fields, artifact
preview, approval dialogs, and publishing workflows. The backend owns identity
validation, classification, memory scope, routing, pipeline execution, audit,
provider credentials, and release policy.

## Start the frontend against a local backend

From the repository root:

```powershell
Copy-Item .env.example .env
pwsh -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
uv run python -m api.server
```

The default API origin is `http://localhost:8000`. Set the backend
`SUDARSHAN_CORS_ORIGINS` to the exact frontend origin, for example:

```dotenv
SUDARSHAN_CORS_ORIGINS=http://localhost:3000,http://localhost:5173
```

Do not use wildcard CORS with credentials in a deployed NTRO environment.

## Shared TypeScript types

Keep these types in the frontend API client. They mirror the public response
projection; they intentionally exclude raw prompts, Cognee documents, model
reasoning, and credentials.

```ts
export type RunStatus =
  | "queued" | "running" | "waiting_for_approval"
  | "waiting_for_input" | "pending" | "succeeded"
  | "partial" | "failed" | "cancelled";

export type ProgressEvent = {
  event_id: string;
  run_id: string;
  task_id: string;
  pipeline: string | null;
  stage: string;
  status: RunStatus | "completed";
  progress: number;
  message: string;
  requires_action: boolean;
  artifact_id: string | null;
  error_code: string | null;
  timestamp: string;
};

export type RunReceipt = {
  status: "queued";
  run_id: string;
  task_id: string;
  pipeline: string | null;
  pipelines: string[];
};

export type PipelineResponse = {
  status: "succeeded" | "failed" | "pending";
  pipeline: string;
  task_id: string;
  run_id: string;
  output: unknown;
  artifact: unknown;
  failure: string | null;
  attempts: number;
  metadata: Record<string, unknown>;
};

export type RunStatusProjection = {
  run_id: string;
  task_id: string | null;
  status: RunStatus | "not_found";
  stage?: string;
  pipeline?: string | null;
  pipelines: string[];
  clarification_required: boolean;
  clarification_questions: string[];
  error?: string | null;
  events: ProgressEvent[];
};

export type IngestionReceipt = {
  status: "succeeded";
  document_id: string;
  source_reference: string;
  doc_type: string;
  user_id: string;
  case_id: string;
  task_id: string;
  classification_level: string;
  content_characters: number;
  memory_persisted: true;
  ingested_at: string;
};
```

## Required request identity

Every mutating request must include `X-Operator-Id`. The frontend should send
the verified operator identity supplied by the authenticated application
session. `X-Case-Id` may be used as a default case header, but the JSON/form
`case_id` is clearer when the UI is switching cases.

Always send the classification selected by the case policy. If omitted, the
backend defaults to `RESTRICTED`; invalid values are normalized to
`RESTRICTED`. The backend returns `X-Classification-Level` on responses.

```ts
const identityHeaders = (operatorId: string, caseId: string) => ({
  "X-Operator-Id": operatorId,
  "X-Case-Id": caseId,
  "X-Classification-Level": "RESTRICTED",
});
```

Do not put Cognee keys, model keys, provider URLs, or Harness credentials in
frontend configuration or browser requests.

## Real source ingestion

Use `FormData`; do not base64-encode large files and do not upload them to
Cognee directly.

```ts
export async function ingestSource(
  apiOrigin: string,
  file: File,
  operatorId: string,
  caseId: string,
): Promise<IngestionReceipt> {
  const form = new FormData();
  form.append("file", file, file.name);
  form.append("case_id", caseId);
  form.append("task_id", `ingest-${crypto.randomUUID()}`);

  const response = await fetch(`${apiOrigin}/ingest`, {
    method: "POST",
    headers: identityHeaders(operatorId, caseId),
    body: form,
  });
  if (!response.ok) throw await readApiError(response);
  return response.json() as Promise<IngestionReceipt>;
}
```

The backend streams the upload to a bounded temporary file, extracts the real
source, synchronously persists the resulting `KnowledgeUnit` through scoped
memory, writes the audit event, and removes the temporary file. Display the
receipt and refresh the case memory/run view; do not display raw extracted
content from this response because it is intentionally not returned.

## Starting a run

```ts
export async function createRun(
  apiOrigin: string,
  input: {
    query: string;
    operatorId: string;
    caseId: string;
    taskId?: string;
    requestedPipelines?: string[];
    classificationLevel?: string;
    distribution?: string;
  },
): Promise<RunReceipt> {
  const body = {
    query: input.query,
    user_id: input.operatorId,
    case_id: input.caseId,
    task_id: input.taskId ?? `task-${crypto.randomUUID()}`,
    requested_pipelines: input.requestedPipelines ?? [],
    classification_level: input.classificationLevel ?? "RESTRICTED",
    distribution: input.distribution ?? "Authorized NTRO personnel",
    metadata: {},
  };
  const response = await fetch(`${apiOrigin}/runs`, {
    method: "POST",
    headers: {
      ...identityHeaders(input.operatorId, input.caseId),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (response.status !== 202) throw await readApiError(response);
  return response.json() as Promise<RunReceipt>;
}
```

An empty `requested_pipelines` lets the router select. Explicit names must be
registered in `GET /pipelines`. Multiple names run as isolated child tasks and
return through one parent run.

## Progress: polling or SSE

After `POST /runs`, use the returned `run_id` immediately. The reliable
fallback is polling:

```ts
export async function getRunStatus(apiOrigin: string, runId: string) {
  const response = await fetch(`${apiOrigin}/runs/${encodeURIComponent(runId)}`);
  if (!response.ok) throw await readApiError(response);
  return response.json() as Promise<RunStatusProjection>;
}
```

For live progress, subscribe to `GET /runs/{run_id}/events`. Events are named
`progress`, contain JSON `ProgressEvent` data, and may include `heartbeat` or
`error` events. If browser authentication requires custom headers, use a
`fetch` streaming client or an authenticated same-origin cookie; native
`EventSource` cannot attach arbitrary authorization headers.

```ts
export function subscribeToRun(
  apiOrigin: string,
  runId: string,
  onProgress: (event: ProgressEvent) => void,
  onError: (error: unknown) => void,
) {
  const source = new EventSource(
    `${apiOrigin}/runs/${encodeURIComponent(runId)}/events`,
    { withCredentials: true },
  );
  source.addEventListener("progress", (message) => {
    onProgress(JSON.parse((message as MessageEvent).data) as ProgressEvent);
  });
  source.addEventListener("error", onError);
  return () => source.close();
}
```

Terminal statuses are `succeeded`, `partial`, `failed`, or `cancelled`.
`pending` means an external provider is still working; it is not automatically
an approval request. `waiting_for_input` and `waiting_for_approval` require a
user action.

## Resume and cancel

Use `requires_action`, `clarification_required`, or the status event to show an
action dialog. Send only the user’s decision, not prompts or internal state:

```ts
export async function resumeRun(
  apiOrigin: string,
  runId: string,
  taskId: string,
  decision: Record<string, unknown>,
) {
  const response = await fetch(`${apiOrigin}/runs/${encodeURIComponent(runId)}/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task_id: taskId, ...decision }),
  });
  if (!response.ok) throw await readApiError(response);
  return response.json();
}

export async function cancelRun(apiOrigin: string, runId: string, taskId: string) {
  const response = await fetch(`${apiOrigin}/runs/${encodeURIComponent(runId)}/cancel`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task_id: taskId }),
  });
  if (!response.ok) throw await readApiError(response);
  return response.json();
}
```

In production, the gateway must apply the same authenticated operator/case
identity to resume and cancel requests. The current development middleware
requires `X-Operator-Id` on all POST requests.

## Error handling and UI behavior

| Status | Meaning | Frontend action |
| --- | --- | --- |
| `401` | missing operator identity | refresh/authenticate the session |
| `403` | operator/user mismatch | stop and show an authorization error |
| `413` | upload exceeds configured limit | ask for a smaller source |
| `415` | unsupported source extension | show supported upload types |
| `422` | invalid request or extraction input | show field/source validation |
| `502` | extraction or memory/provider failure | show retry/support state; do not fabricate success |
| network/timeout | transport failure | retain `run_id` and poll status before retrying |

Never retry `POST /ingest` blindly after a network timeout: the server may have
persisted the source. First check the case/task audit state or use the returned
task identity. For `/runs`, preserve the returned `run_id`; status polling is
idempotent even when the original response is lost.

## Frontend security checklist

- Use the authenticated gateway identity for `X-Operator-Id`; never trust a
  free-text operator field from a form.
- Keep case selection and classification visible in the UI before submission.
- Treat all output and artifact metadata as untrusted display data; escape it
  according to the rendering context.
- Do not expose raw prompts, recalled memory, provider responses, or credentials.
- Show classification and distribution markings with every artifact preview.
- Disable duplicate submit while a run is queued, but recover by `run_id` after
  a browser refresh.
- Use HTTPS, same-origin cookies or approved bearer tokens, and a strict CORS
  allow-list in deployment.

## Backend/frontend verification

The backend tests for this contract are in
`api/tests/test_api_server.py` and `tests/component/test_application_boundary.py`.
From the repository root:

```powershell
uv run pytest -q
```

For the full backend/Harness integration contract, also follow
[`docs/backend-integration.md`](backend-integration.md).
