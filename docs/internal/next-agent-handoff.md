# Next-agent handoff

This document is a compact continuation brief for work on Sudarshan Agentic
Core. It is intentionally specific to this repository and its NTRO-oriented
application; it is not a general agent framework specification.

## Product boundary

- `MemoryManager` owns User, Case, and Task memory policy and is the only
  application boundary for Cognee.
- Ingestion owns extraction and creates `KnowledgeUnit` objects. It stores
  them through `MemoryManager.remember()` before generation.
- LangGraph owns request understanding, routing, lifecycle, fan-out/fan-in,
  cancellation, and frontend-safe progress events.
- CrewAI owns multi-agent collaboration inside each concrete generation flow.
- DeepSeek Harness owns the interactive session, tool/runtime execution,
  optional sandbox, and application handoff. It must not become a second
  memory owner.
- The frontend owns preview, user editing, upload, and rendering of progress.

## Implemented Python state

The current implementation lives in `pipelines/` and includes:

- Two-stage memory recall: bounded User/Case recall before request
  understanding, followed by User/Case/Task recall after routing.
- `AdvisoryRequest` with required identity, `requested_pipelines`, and
  revision linkage (`operation`, `parent_run_id`, `parent_artifact_id`,
  `revision_instruction`, `revision_scope`).
- Deterministic request understanding and prompt planning with bounded memory
  context. Explicit plugin pipeline names are accepted without changing the
  router.
- Parallel fan-out in `PipelineOrchestrator`: each child receives an isolated
  task/run identity, shared bounded context, a pipeline-specific prompt plan,
  and independent response/progress metadata.
- Parent results expose `response` for backward compatibility and
  `responses: dict[pipeline, PipelineResponse]` for batch runs. Parent status
  is `succeeded`, `partial`, `failed`, `pending`, or `cancelled`.
- Revisions create a new task/artifact version and do not mutate or re-run
  sibling artifacts. A revision should normally contain exactly one selected
  pipeline.
- Cooperative cancellation with frontend progress and Task-memory audit.
  Provider calls already in progress cannot be force-stopped by LangGraph.
- `PipelineAdapter` is the stable plugin contract. `PipelineRegistry` gives
  explicit registration, and `load_pipeline_plugins()` loads approved Python
  entry points from the `sudarshan.pipelines` group.
- `orchestration_result_to_dict()` serializes the parent plus every child for
  an HTTP response.

## Important current limitation

The default Python registry contains the pipelines implemented in this repo.
PPT/video or any partner-owned pipeline must be registered by the backend; the
central router does not invent an implementation. A new plugin can be selected
explicitly with `requested_pipelines=("plugin_name",)` or
`metadata={"pipelines": ["plugin_name"]}`. Automatic natural-language aliases
for third-party names are not yet discovered from plugin metadata.

## Recommended Harness integration

Expose one Harness-facing application tool or SDK method such as:

```text
run_sudarshan(request) -> orchestration_result_to_dict(result)
```

The Harness adapter should:

1. validate authenticated user/case identity;
2. create `task_id` and `run_id`;
3. submit the common `AdvisoryRequest` contract;
4. stream `ProgressEvent` values to the frontend;
5. return `responses` and artifact references;
6. map cancel/resume commands to the orchestrator;
7. never expose raw Cognee context, model reasoning, credentials, or direct
   Cognee tools to the model.

Do not move routing into a Harness workflow script. The Python LangGraph
orchestrator remains the source of truth for memory scopes, revisions,
parallel child identity, and artifact isolation. A Harness workflow may be a
thin runtime wrapper or may call the application tool once; it should not
duplicate those policies.

## Harness capabilities relevant to this project

The vendored `deepseek-harness/` source currently documents:

- Cordis composition: model, tools, sessions, storage, workflow, sandbox,
  UI, and other capabilities are replaceable plugins.
- `dsh-workflow`: JavaScript workflow scripts with `agent()`, `parallel()`,
  `pipeline()`, `phase()`, and `log()`.
- E2B provider family: one shared ephemeral remote Linux sandbox for files,
  shell commands, and terminals. It is opt-in and is not the whole Harness
  runtime; session state and LLM calls remain in the host process.
- Local sandbox providers: platform confinement with fail-closed behavior,
  but Windows enforcement is documented as partial.
- Append-only session events, tool execution seams, cancellation, subagents,
  and SDK/headless entry points.

Use these capabilities for session/tool/runtime concerns. Keep Cognee and the
application pipeline contract in Python.

## Build and sandbox notes

Harness itself is TypeScript/Node and can be built from its directory:

```powershell
cd deepseek-harness
pnpm install
pnpm run build
pnpm dsh web
```

The E2B family can run build/test/render commands inside an isolated remote
Linux environment after source and dependencies are supplied. It is useful
for untrusted or disposable compilation/rendering, but it is ephemeral and
adds network latency. Do not implicitly pass `OPENAI_API_KEY`, Cognee keys,
or host environment variables into that sandbox. API calls requiring secrets
should remain behind a backend service boundary.

The current Sudarshan setup command remains the supported local setup path:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
uv run pytest -q
```

## Verification already completed

The Sudarshan suite passed with 46 tests. Coverage includes component,
pipeline, and system-level tests, including parallel child isolation and
selected-artifact revision routing. `git diff --check` passes; line-ending
warnings are normal for this Windows checkout.

## Next recommended work

1. Add the backend HTTP/SDK adapter around `PipelineOrchestrator`; it is not
   present in this repository yet.
2. Register the partner's concrete pipelines through `PipelineRegistry` and
   add their output schemas/artifact references.
3. Add per-plugin alias metadata if natural-language routing should discover
   third-party names automatically.
4. Replace the in-process thread fan-out with durable worker jobs for
   production multi-instance execution; retain the same parent/child result
   contract.
5. Add batch approval/resume semantics if multiple human-approval pipelines
   will be allowed in one parent run. Current automatic fan-out is intended
   for pipelines that can complete without a shared approval gate.
6. Add integration tests against real configured services only after keys and
   deployment endpoints are intentionally supplied. Never commit keys.

