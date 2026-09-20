# DeepSeek Harness boundary

The vendored Harness remains the session/runtime layer. Sudarshan remains the
application layer: LangGraph routes, `MemoryManager` owns Cognee, and each
pipeline owns its CrewAI or provider adapter.

For a local headless smoke run, send one real request to the Python boundary:

```powershell
'{"query":"Create an executive summary","user_id":"u-1","case_id":"c-1","task_id":"t-1"}' |
  .\.venv\Scripts\python.exe -m integrations.deepseek_harness.runner
```

This requires configured Cognee credentials and returns the normal
`orchestration_result_to_dict()` envelope. It does not create fake artifacts.

## MCP stdio integration

The repository exposes the real application boundary as MCP tools through
`integrations/deepseek_harness/mcp_server.py`. The Harness invokes backend-owned
tools while Cognee, OpenAI, and provider credentials remain in the Python
process:

- `run_sudarshan` starts a create/revise operation;
- `resume_sudarshan` continues clarification or approval;
- `cancel_sudarshan` requests cooperative cancellation;
- `get_sudarshan_status` returns frontend-safe progress events;
- `get_sudarshan_artifact` returns an integrity-verified manifest and stable
  download URI without exposing filesystem paths or raw bytes.
- `list_sudarshan_skills` and `get_sudarshan_skill` expose the versioned,
  canonical skill catalog and output contracts;
- `invoke_sudarshan_skill` runs an available specialist through the typed local
  `SkillRuntime`; `start_sudarshan_skill` submits the same skill contract to
  the durable background scheduler.

The built-in `visual.flowchart` child is executable and can be requested by
the presentation, LinkedIn, infographic, and video parent skills. Discovery
still reports availability per deployment: an optional package may be listed
without an adapter, and the application rejects unavailable execution instead
of silently routing it to an unrelated pipeline.

Parent outputs carry a typed `child_plan`. Sudarshan validates dependencies,
runs independent children under the parent concurrency/budget policy, and
returns child artifact IDs, quality-report IDs, and typed fallback/blocking
states in the same parent artifact projection.

The server uses the configured SQLite LangGraph checkpointer, so these tools
share a durable run identity within the service process instead of creating a
new in-memory orchestrator for every call.

## Portable pipeline agents

Harness is one optional client of the Sudarshan orchestrator. The scalable
agent boundary is not the Harness plugin: each governed pipeline can expose a
portable A2A agent card while retaining the same local adapter. The
orchestrator can mediate a typed handoff such as Presentation → Infographic or
Presentation → Diagram, then pass the returned artifact and quality receipt
back to the parent.

The portable handoff uses the existing `SkillManifest`, `ChildTaskSpec`, and
`SkillResult` contracts. A remote child must preserve parent/child IDs, case
scope, idempotency, deadline, cancellation, budget, dependencies, artifact
references, and quality/usage receipts. The current `a2a.py` exposes the
global Sudarshan run/status/cancel boundary; per-pipeline cards and remote
child dispatch remain staged work.

Local and A2A children should emit the same lifecycle events. Harness
trajectory is one projection of those events and can show the parent run with
parallel child lanes; it is not the scheduler or source of truth.

Use the checked-in overlay at
`integrations/deepseek_harness/sudarshan.cordis.yml` with the Harness MCP
client. On Linux, use `.venv/bin/python` for `command` instead of the Windows
`.venv/Scripts/python.exe` value in the overlay.

From the vendored Harness checkout, launch the web profile with the overlay:

```powershell
dsh web --patch (Resolve-Path ..\integrations\deepseek_harness\sudarshan.cordis.yml)
```

The Python environment and the Harness process must be able to resolve this
repository as their current working directory. For a packaged deployment,
replace the relative Python command in the overlay with the absolute service
entry point.

### Production agent profile

The overlay mounts one checked-in `Sudarshan Artifact Agent` preset from
`agent-presets/sudarshan-artifact-agent`. It deliberately excludes Harness's
shipped coding presets and the user preset directory, so users cannot switch
the production session into a shell/filesystem/web/coding composition. The
profile keeps Harness compaction and clarification support, while all planning,
skill selection, execution, evidence, artifact, and quality decisions remain
owned by the Sudarshan MCP application.

The overlay hides generic preset, plugin, plan, goal, subagent, workflow, and
command-palette controls. The Sudarshan operations drawer and clarification
support remain available. The inherited attachment, workspace, generic
approval, trajectory, model/provider, and permission controls are not yet
Sudarshan-compatible; the control-by-control findings and follow-up tickets
are recorded in `docs/archive/harness-ui-compatibility-audit-2026-09-12.md` and T84-T90. This is
a composition-level restriction in the replaceable Cordis profile; the
vendored Harness core is not modified.

The native MCP child process receives `SUDARSHAN_MCP_TOOL_PROFILE=artifact`.
That profile exposes only lifecycle, skill discovery/dispatch, and verified
artifact tools to the native agent, reducing tool-schema tokens. External MCP
clients retain the default `full` profile for compatibility, or can select a
named profile explicitly.

The MCP server is an application adapter, not a second orchestrator: it calls
the same application service as the JSONL runner. Do not place Cognee keys in
Harness workflow scripts or pass them into an E2B sandbox.

See [`docs/sudarshan-harness-artifact-flow.md`](../../docs/sudarshan-harness-artifact-flow.md)
for the full asynchronous artifact flow, wake contract, and slide-scoped PPT
revision behavior. The production system prompt is wired in both
`sudarshan.cordis.yml` and the `Sudarshan Artifact Agent` preset.

### Native operations bridge and sandbox boundary

The operations plugin installs a typed HTTP/SSE bridge at runtime. It maps the
safe `GET /runs/{run_id}` projection to the native operations drawer, listens
to `/runs/{run_id}/events`, and opens only the authenticated preview/download
routes returned by the artifact projection. A host that starts a run should
call `bindRun(sessionId, runId)` so a Harness session follows the durable
Sudarshan run; without a binding, the bridge uses the session ID as the run ID.
Set `SUDARSHAN_API_ORIGIN` when the API is not on `http://localhost:8000`.

Renderers and provider execution use the `pipelines.common.sandbox` protocol.
The checked-in local adapter enforces an executable allowlist, timeouts,
cooperative cancellation, output limits, workspace containment, and secret
redaction. It is a policy boundary for development and tests, not a claim of
OS-level isolation. Production selects the container adapter with:

```dotenv
SUDARSHAN_SANDBOX_MODE=container
SUDARSHAN_SANDBOX_RUNTIME=docker
SUDARSHAN_SANDBOX_CONTAINER_IMAGE=python:3.12-slim
```

The container command is shell-free, network-disabled, read-only at the
container root, capability-dropped, resource-limited, and mounts only a
temporary `/workspace`. `SUDARSHAN_SANDBOX_MODE=local` is rejected unless
`SUDARSHAN_ALLOW_LOCAL_SANDBOX=true` is also set. This prevents a deployment
from silently falling back to a host subprocess when the container runtime is
missing. A trusted/rootless runtime and approved image registry remain
deployment responsibilities.

## Harness web UI composition

The web profile loads Sudarshan branding and presentation through the
replaceable packages under
`deepseek-harness/packages/experimental/client-ui-sudarshan*`. The overlay
does not modify the official Harness brand package. See
[`docs/harness-ui-plugin.md`](../../docs/harness-ui-plugin.md) for the package
contract and white-label replacement path.

Never commit `.dsh-preview/`; it is local preview state and may contain
credentials, transcripts, caches, and machine-specific paths. If a credential
was ever committed, rotate it even after the local file is deleted.
