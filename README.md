# Sudarshan Agentic Core — NTRO Intelligent Advisory Platform

The `memory` package is the Sudarshan-side memory unit. It accepts ingestion
`KnowledgeUnit` objects, applies User/Case/Task scope policy, and delegates
knowledge graph and semantic retrieval to Cognee. See
[`memory/README.md`](memory/README.md) for setup and usage.

## One-command setup

From PowerShell, run:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

This installs the locked Python dependencies and the pinned AntV infographic
renderer together. It requires `uv` and Node.js/npm. The setup script uses
`npm install --ignore-scripts`; runtime rendering is performed by the checked-in
AntV bridge under `pipelines/infographic/antv_renderer/`.

After setup, use the Python environment with `uv run ...`; no separate npm
installation command is needed.

## Native Media Pipelines

The in-repo presentation pipeline generates native PPTX files. The ingestion process now includes a native **PPT Master** implementation that extracts structural markdown and slide transitions natively. No external service is required.

Video generation defaults to a native **MoneyPrinterTurbo-inspired** architecture running in-process using `imageio-ffmpeg` and optional OpenAI TTS. Deployments that already operate the upstream MoneyPrinterTurbo worker can set `MONEYPRINTERTURBO_BASE_URL`; the same adapter then uses its asynchronous submit/status contract and preserves provider-pending state.

## Start testing

Copy `.env.example` to `.env` if needed, then add the Cognee Cloud values and
the CrewAI provider credentials. The example disables optional CrewAI telemetry
by default. Run the focused unit suite with:

```powershell
uv run pytest -q
```

The test configuration intentionally targets the Sudarshan-owned suites and
does not collect the vendored DeepSeek Harness test tree.

Generated advisory, LinkedIn image, and infographic files are written below
`artifacts/`, which is intentionally ignored by Git.

Internal backend/frontend integration details are in
[`docs/internal/pipeline-orchestration.md`](docs/internal/pipeline-orchestration.md).
The backend handoff and HTTP/MCP contract are in
[`docs/backend-integration.md`](docs/backend-integration.md).

## Running the API Server

The system includes a FastAPI server equipped with SSE streaming, NTRO security middleware, and tamper-evident audit logging. Production deployments must provide approved at-rest encryption for the SQLite state stores.

```powershell
uv run python -m api.server
```

The API will start at `http://localhost:8000`. It enforces `X-Operator-Id` headers on mutations and returns `X-Classification-Level` headers.

## DeepSeek Harness integration

The LangGraph orchestrator now provides the thin application boundary for
routing, lifecycle state, approval interrupts, and progress events. The
Harness should own session, tool, and runtime execution; CrewAI pipelines own
agent collaboration; and MemoryManager owns memory policy. Do not make each
pipeline depend directly on Harness internals.

For a local headless Harness bridge, send one JSON request to:

```powershell
'{"query":"Create an executive summary","user_id":"u-1","case_id":"c-1","task_id":"t-1"}' |
  .\.venv\Scripts\python.exe -m integrations.deepseek_harness.runner
```

In production, register the MCP overlay at
`integrations/deepseek_harness/sudarshan.cordis.yml` or expose the same
boundary through an authenticated backend service. MoneyPrinterTurbo is
called by `integrations/providers/moneyprinterturbo/client.py` from the
backend process; the Harness does not call it directly.

The MCP application boundary exposes four operations:

- `run_sudarshan`: start a routed operation with a stable `task_id`.
- `get_sudarshan_status`: poll frontend-safe stage and progress events.
- `resume_sudarshan`: continue a clarification, approval, or revision.
- `cancel_sudarshan`: request cooperative cancellation while preserving the
  task audit trail.

The application owns a durable LangGraph checkpoint store, so a resume or
status request does not create a second orchestration instance. Raw Cognee
context, provider credentials, and model reasoning are not serialized into
the Harness response.
