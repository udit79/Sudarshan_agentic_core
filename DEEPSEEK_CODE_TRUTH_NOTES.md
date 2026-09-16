# Code-truth notes: Sudarshan + DeepSeek Harness

These notes are based on source code, package manifests, executable configuration, and tests in this checkout. README files, website documentation, agent notes, and other documentation files were intentionally not used as evidence. Generated bundles, dependency trees, caches, and binary artifacts were also not treated as source truth.

Repository state observed: branch `Sudarshan2.2`, clean working tree at inspection time.

## 1. The actual repository shape

The checkout is a combined Python/Node product:

- Python Sudarshan service: `api/`, `pipelines/`, `memory/`, `ingestion_pipelines/`, `skills/`, `integrations/`.
- Node gateway: `backend-node/`.
- DeepSeek Harness monorepo: `deepseek-harness/`.
- Product web/branding assets: `chakra-app/` and `landing page/`.
- Runtime launcher: `startup.ps1`.

`deepseek-harness/package.json` defines a private pnpm workspace using Node `^22.19.0 || >=24.0.0`, pnpm `11.7.0`, and six workspace families: `vendor/*`, `packages/*/*`, native landlock packages, `apps/*`, and `website`. The workspace version currently visible in the root and CLI packages is `0.1.2-rc.1`.

The Harness is not a small adapter. It contains package families for agents, sessions, LLMs, storage, tools, sandboxing, scheduling, subagents, web UI, API gateways/controllers, SDK/ACP transports, experimental features, and test support. The workspace contains 278 package manifests; the focused runtime families are especially large in `client`, `experimental`, `api`, `core`, `session`, and `llm`.

## 2. Active product data flow

```text
startup.ps1
  -> Node gateway + Python API + dsh web process
  -> dsh --patch integrations/deepseek_harness/sudarshan.cordis.yml
  -> dsh web profile / Cordis Loader tree
  -> native dsh MCP client
  -> Python: integrations.deepseek_harness.mcp_server
  -> SudarshanHarnessAdapter (allow-listed operations)
  -> one lazy SudarshanApplication per Python process
  -> LangGraph-backed PipelineOrchestrator + memory + ingestion + artifacts
```

`startup.ps1:635-679` requires `JWT_ACCESS_SECRET` when Harness is enabled, passes the same value to the Harness as `SUDARSHAN_GATEWAY_ACCESS_SECRET`, sets `SUDARSHAN_REPO_ROOT` and `SUDARSHAN_PYTHON_EXECUTABLE`, then starts `apps/cli/src/bin.ts web` with the Sudarshan overlay.

The Harness-facing Python process is started as `python -m integrations.deepseek_harness.mcp_server` by `integrations/deepseek_harness/sudarshan.cordis.yml:56-66`. Its working directory is the repository root, and its native tool profile is `artifact`.

## 3. The key product truth: native DeepSeek is disabled in Sudarshan

`integrations/deepseek_harness/sudarshan.cordis.yml:26-43` does all of the following:

- supplies `OPENAI_API_KEY` to the `llm-pi-ai` provider configuration;
- sets the default agent model to provider `openai`, model `gpt-5.4`;
- disables the `llm-deepseek` plugin row.

Therefore the deployed Sudarshan Artifact Agent does not use the native `deepseek-official` provider route by default. The DeepSeek adapter is still present in the shared `dsh-base` composition and is independently usable/tested, but the Sudarshan product overlay intentionally removes it as an active fallback.

The same overlay installs `@deepseek-ai/dsh-mcp-client` pointing at the Python MCP server, uses only the artifact MCP profile, disables generic coding/UI controls, and mounts the repository-owned `sudarshan-artifact-agent` preset. The preset uses Harness only as a session/runtime shell; Sudarshan owns routing, skills, pipelines, artifacts, evidence, approvals, budgets, and auditability (`integrations/deepseek_harness/sudarshan.cordis.yml:1-119`, `integrations/deepseek_harness/agent-presets/sudarshan-artifact-agent/agent.cordis.yml:7-50`).

## 4. DeepSeek native LLM implementation

Primary package: `deepseek-harness/packages/llm/llm-deepseek/` (`@deepseek-ai/dsh-llm-deepseek`). The package owns these source modules:

- `src/index.ts`: Cordis plugin/configuration/registration.
- `src/adapter.ts`: provider adapter, HTTP request, streaming, cancellation, timeouts, and error mapping.
- `src/serialize.ts`: Harness message -> DeepSeek chat-completions wire format.
- `src/sse.ts`: SSE framing and `[DONE]` enforcement.
- `src/translate.ts`: DeepSeek chunks -> Harness stream chunks.
- `src/files-api.ts`: `/files` API client.
- `src/file-store.ts`: upload reuse, single-flight, quota cleanup, stale-ID invalidation.
- `src/upload-index.ts`: durable local attachment-version -> provider-file mapping.
- `src/request-pricing.ts`: image request size/token pricing and offload policy.
- `src/image-tokens.ts`: image token projection.
- `src/file-id.ts` and `src/types.ts`: branded IDs and wire types.
- `src/request-pricing.ts` and `src/image-tokens.ts`: image capability/cost calculations.

### Provider registration and configuration

`src/index.ts:84-90,405-498` registers exactly one route: `deepseek-official`, displayed as `DeepSeek`, under settings namespace `llm-deepseek`. It resolves settings and credentials per request, while an in-flight stream holds one immutable connection snapshot. The retry policy is the one captured fact that requires in-place route replacement when changed.

Defaults and hard constraints in `src/index.ts` and `src/adapter.ts`:

- public base URL: `https://api.deepseek.com`;
- API key reference: `DEEPSEEK_API_KEY` unless configured otherwise;
- default context window: 1,000,000;
- default output cap: 256,000 tokens;
- default stream idle timeout: 300,000 ms;
- default file lifetime: 7 days;
- file refresh margin: 1 hour;
- max stored-file cleanup batch: 100;
- max accumulated file-referenced image bytes per request: 128 MiB;
- max inline base64 image payload: 20 MiB;
- max represented images per request: 600;
- default model catalog: `deepseek-v4-flash`, `deepseek-v4-pro`, and `deepseek-v4-flash-vision-exp`;
- only catalog entries declaring `image` are treated as image-capable; unknown model IDs are conservatively text-only.

Configuration validation rejects duplicate/empty model IDs, invalid context/output caps, invalid image bounds, invalid expiry windows, non-off reasoning while thinking is disabled, and the removed `imageDetail` field. A bad live settings snapshot keeps the last good complete connection snapshot, preventing a new endpoint from being paired with an old/new mismatched credential.

Credentials are resolved through the optional credentials service; without that seam, the trusted launch environment is used. A missing key fails at request time with `MISSING_CREDENTIAL`, while model discovery can remain available.

### Request and response behavior

`src/adapter.ts:444-705` implements one request lifecycle:

1. Validate image capability before credential resolution.
2. Resolve the API key once and create one combined caller/consumer abort signal.
3. Apply per-request image offloading policy.
4. Serialize to `POST {baseURL}/chat/completions` with `stream: true` and `stream_options.include_usage: true`.
5. Prepare registered DeepSeek request-extension fields before HTTP dispatch.
6. Reject extension field collisions with base request fields.
7. Accept extension side effects only after HTTP 2xx.
8. Require a response body, parse SSE, and translate the stream.
9. Abort/close the underlying stream when the consumer stops.

Headers include the bearer token, SSE/content-type headers, attribution headers, a stable anonymous Harness user ID, optional Harness session ID, and a compaction marker for compaction calls.

HTTP mapping in `src/adapter.ts:332-344` is explicit: 401/403 -> `AUTH`, 413 -> `INVALID_REQUEST`, recognized quota -> `QUOTA_EXCEEDED`, 429 -> `RATE_LIMIT`, recognized context overflow on 400 -> `CONTEXT_WINDOW_EXCEEDED`, other 400 -> `INVALID_REQUEST`, 5xx -> `SERVER`, otherwise `HTTP_<status>`. Retry-After and provider request IDs are preserved when valid.

The adapter retries one stale-file-ID chat failure after invalidating only the mappings identified by the provider. It does not convert generic chat failures into base64 fallback. Files API resolution failures can switch the whole request to one all-base64 retry; caller cancellation does not trigger that fallback.

### Wire serialization

`src/serialize.ts:82-404` translates Harness messages as follows:

- system messages become `role: system`;
- assistant text/reasoning/tool calls become one assistant message;
- reasoning is passed back through `reasoning_content`;
- tool results become separate `role: tool` messages;
- empty tool output becomes `(no output)`;
- optional tools become OpenAI-style function tools;
- text-only user content stays a compact string;
- images are rejected on unsupported roles rather than silently flattened away;
- image-capable user content carries a stable textual handle plus either `file_id` or inline `image_url` parts;
- consecutive tool-result images are emitted after textual tool messages in a following user message;
- `session-title` forces thinking off;
- effort `off` becomes `thinking: {type: disabled}` and no wire reasoning effort;
- supported wire efforts are `low`, `high`, and `max`;
- optional fields are omitted rather than sent as null.

Assistant messages deliberately use `content: ""` rather than null for content-less/tool-only/reasoning-only turns, preserving replayability and avoiding provider rejection.

### SSE and stream translation

`src/sse.ts` requires a complete SSE stream terminated by `[DONE]`; it tolerates arbitrary byte/UTF-8 chunk boundaries and reports comments as activity without emitting them as model content. Missing `[DONE]`, empty streams, and truncated events map to `STREAM_CLOSED`.

`src/translate.ts` maintains separate text, reasoning, and per-tool-call blocks. It ignores empty initial reasoning deltas, preserves streamed tool-call identity across continuation fragments, defers finish emission until `[DONE]`, and keeps the latest usage object if usage arrives both on the finish chunk and in a trailing usage-only chunk. `stop`, `tool_calls`, and `length` map to Harness stop/tool-calls/max-tokens; unknown finish reasons become structured errors. Cache-hit prompt tokens are subtracted so Harness input/output counts remain disjoint.

### Images and Files API

`src/files-api.ts:127-257` is a direct OpenAI-compatible client for `/files`:

- upload uses multipart `purpose=user_data` and explicit `expires_after`;
- upload limit is 128 MiB;
- accepted expiry is 3,600 through 2,592,000 seconds;
- list is paginated and scoped to `purpose=user_data`;
- retrieve/delete responses are schema-validated;
- provider quota/storage errors retain detail for one cleanup-and-retry path.

`src/file-store.ts:110-320` derives deterministic owned filenames with `dsh-` prefix, keys the local index by endpoint + API-key scope + request variant, shares concurrent uploads, aborts a shared transport when no waiter remains, reuses mappings above the refresh margin, deletes duplicate uploads after a cross-process winner, and reclaims only Harness-owned remote files on quota recovery.

`src/upload-index.ts` persists records under `DSH_HOME/llm-deepseek/files-v3.json` by default. Records are scoped by normalized base URL and API key, expire safely, reject duplicate/corrupt mappings, and use atomic writes. The session log does not carry raw image bytes; it carries content-addressed attachment references.

## 5. DeepSeek request-extension architecture

`packages/llm/deepseek-llm-api-extensions/src/index.ts` defines a Cordis service with one provider per top-level JSON field. Providers prepare against an immutable serialized base body, receive session/purpose/cancellation context, and return detached frozen JSON plus an optional acceptance callback. All preparation runs abortably; all acceptance callbacks settle before failures are reported; acceptance is idempotently shared.

`packages/llm/plugin-package-inventory-deepseek/src/index.ts` contributes `dsh_plugin_packages` to official DeepSeek requests. It walks active Loader entries and, when available, the requesting agent's standing preset tree, resolves owning package manifests, deduplicates exact name/version pairs, and sorts them deterministically. Disabled/group/inactive entries and loose modules without package identity are excluded.

The base bundle mounts both the extension registry and the package-inventory plugin. The session-log extension is optional and controlled by composition; the package inventory is on by default in the tested real Loader composition.

## 6. Harness runtime lifecycle

`apps/cli/src/bin.ts:24-50` parses one of three effective modes: profile boot, plugin management, or config dump. Profile boot calls `runProfile` with layered launch environment, selected profile, patches, and inner app arguments.

`apps/cli/src/profile-boot.ts:136-320` composes patch layers in this order:

1. bundle layers from `dsh.profile.bundles`;
2. profile patch;
3. `$DSH_HOME/cordis.patch.yml`;
4. explicit `--patch` overlays;
5. telemetry-disable patch if requested.

It rewrites an empty profile root config, boots the Cordis Loader tree, provides an immutable launch-environment snapshot and command-line snapshot to plugins, installs fail-loud shutdown handling, optionally watches user patch layers for live reload, and commits readiness only after the tree remains active.

`packages/bundle/base/cordis.patch.yml` is the shared runtime layer. It mounts the LLM seam, DeepSeek adapter, pi-ai twin, sessions and persistence, credentials/settings, attachment-local storage, sandbox and permissions, tools, compaction, subagents, workflows, web tools, token meter, and agent loop. The base default agent selection is `deepseek-official/deepseek-v4-flash`; Sudarshan overrides this later.

The web bundle adds the web server, frontend static fallback, browser roster, controllers, workspace/session UI, and trust/runtime URL handling. `apps/web/src/main.ts` is only the Vite browser entry; the actual app shell is served by `dsh web` after `window.__DSH_BOOT__` is injected by the Harness runtime.

SDK and ACP are separate profile bundles. `packages/sdk/client/src/launch.ts` enforces same-version SDK/CLI manifests, prefers a built `dsh` executable, and falls back to the source CLI plus `tsx` and a compatibility patch. `packages/sdk/client/src/api.ts` manages a JSON-RPC subprocess, initialize handshake, stable session IDs, event validation, prompt submission, idle completion, and cleanup/retry on failed startup.

## 7. Python application boundary

`integrations/deepseek_harness/adapter.py` is intentionally small. It exposes a fixed `HarnessOperation` literal allow-list and delegates only to the process-scoped application. Unsupported operation names raise `ValueError`; it does not contain routing, memory, or provider logic.

`integrations/deepseek_harness/mcp_server.py` exposes the public MCP facade. Full mode includes lifecycle, memory, pipeline, skill, and evidence operations. Artifact mode keeps only run/resume/cancel/status/artifact, async submit/wait, and skill discovery/invocation/submission. All MCP calls go through the adapter; raw memory-provider credentials and raw model reasoning are not exposed.

`integrations/deepseek_harness/application.py` constructs one `SudarshanApplication` lazily (`:1640-1652`). On construction it creates:

- optional Redis control plane, otherwise SQLite/local state;
- object store and artifact lifecycle cleaner;
- composite observability and progress sinks;
- LangGraph `PipelineOrchestrator` with SQLite checkpointing;
- skill manifests/runtime, budget controller, and cache;
- evidence index and ingestion stage cache/usage/budget controllers;
- separate durable local schedulers for runs and ingestion.

Run submission validates `AdvisoryRequest`, reserves/propagates `run_id`, enforces operator/user identity, validates explicit pipeline names, and durably enqueues via `LocalRunScheduler`. Synchronous `run` executes the orchestrator and logs start/complete audit events. `resume` verifies task identity and reviewer identity before checkpoint resume. `cancel` supports queued cancellation and cooperative orchestrator cancellation. Status/events/wait project safe progress events; telemetry is aggregate-only.

Skills are canonicalized against manifests. Local child skills run through `SkillRuntime`, not recursive Run API calls. Typed child plans are validated and executed under parent capabilities/tools/trust tiers; child failures can change the parent status to failed/partial. Evidence search is scoped by user/case/task/classification, and ingestion hashes/indexes evidence before memory projection.

`api/server.py` is a FastAPI transport over this same application. It exposes health, A2A tasks, pipeline discovery, artifacts, ingestion, run creation/status/wait/events/resume/cancel. HTTP identity headers are checked against payload user/case/task fields before delegating.

## 8. What tests establish

The native DeepSeek package has extensive tests for mocked HTTP/SSE behavior, dynamic settings/credentials, request serialization, image policy/pricing, file upload/index lifecycle, stale-ID recovery, quota cleanup, proxy egress, Loader composition, and optional real-API E2E behavior. The real API suite is skipped unless `DEEPSEEK_API_KEY` is present (`packages/llm/llm-deepseek/tests/adapter.e2e.ts:142`).

The most important tested invariants are:

- credentials and base URL can change for the next request without restart;
- invalid settings preserve the last complete good snapshot;
- route replacement for retry-policy changes has no empty registry window;
- extension preparation occurs before fetch and acceptance only after 2xx;
- file resolution fallback is all-inline and bounded;
- stale-file retry is limited and does not loop indefinitely;
- provider errors preserve status, retry delay, request ID, and raw cause where available;
- stream idle watchdog aborts the body, while SSE comments keep the read alive;
- the Python MCP facade and replaceable adapter preserve operation parity;
- the artifact MCP profile is smaller than the full external profile;
- Harness correlation IDs are projected without arbitrary metadata exposure.

## 9. Operational truths and likely pitfalls

- Looking only at `deepseek-harness` defaults gives the wrong product-provider answer: the active Sudarshan overlay disables native DeepSeek and selects OpenAI `gpt-5.4`.
- Looking only at the Python MCP server gives the wrong runtime answer: the Python side owns the real work, but the Harness still owns session/UI/MCP transport and invokes it over stdio.
- Looking only at the API server gives the wrong durability answer: queued runs, checkpoints, progress, observability, artifacts, and ingestion state are owned by `SudarshanApplication` and its local/Redis-backed stores.
- A DeepSeek model can be catalogued without a key, but a request cannot run without a usable key.
- Model IDs not in the catalog are allowed through the adapter but are treated as text-only for capability safety.
- Image bytes are deliberately kept outside the append-only session log; attachment references and the provider upload index are separate durability layers.
- The native adapter does not use a generic SDK client; it uses direct `fetch`, multipart `FormData` for files, and `eventsource-parser` for SSE.
- The Harness base has many coding/subagent/web controls, but the Sudarshan profile disables the corresponding product UI and routes agent authority through the allow-listed MCP boundary.

## 10. Evidence index for future work

Start with these files when changing behavior:

- Native provider: `deepseek-harness/packages/llm/llm-deepseek/src/index.ts`, `adapter.ts`, `serialize.ts`, `translate.ts`, `file-store.ts`.
- Provider extension seam: `deepseek-harness/packages/llm/deepseek-llm-api-extensions/src/index.ts`.
- Request package provenance: `deepseek-harness/packages/llm/plugin-package-inventory-deepseek/src/index.ts`.
- Runtime composition: `deepseek-harness/packages/bundle/base/cordis.patch.yml`, `deepseek-harness/apps/cli/src/bin.ts`, `deepseek-harness/apps/cli/src/profile-boot.ts`.
- Active Sudarshan composition: `integrations/deepseek_harness/sudarshan.cordis.yml`, `integrations/deepseek_harness/agent-presets/sudarshan-artifact-agent/agent.cordis.yml`.
- Python boundary: `integrations/deepseek_harness/adapter.py`, `mcp_server.py`, `application.py`.
- HTTP boundary: `api/server.py`, `api/sse.py`, `backend-node/src/python-client.js`, `backend-node/src/routes.js`.
- Behavioral tests: `deepseek-harness/packages/llm/llm-deepseek/tests/`, `tests/component/test_application_boundary.py`, `tests/component/test_harness_profile.py`, `tests/component/test_harness_parity.py`, `tests/system/test_harness_e2e.py`.

## 11. Code-first overengineering and fallback audit

This is an audit of source, executable configuration, package manifests, and tests only. Project Markdown/docs were not used as evidence. The repository-wide inventory covered 4,754 non-document source/config/test files after excluding dependency trees, build output, caches, snapshots, lockfiles, maps, and binaries. The DeepSeek Harness source was checked for duplicate generated artifacts, fallback branches, compatibility shims, factories, wrapper layers, environment-resolution duplication, and optional package wiring.

### Ranked simplification candidates

- `fixed:` Unify video model resolution: `OpenAIVideoPlanner` now uses the
  provider router for `video_script` and no longer falls back to unrelated
  `CREWAI_MODEL`. [`pipelines/video/planner.py`; `integrations/providers/router.py`]
- `shrink:` Stop reconstructing provider identity from raw environment variables in `NativeVideoGenerator.scene_fingerprint`; the fingerprint currently uses raw TTS/image env defaults even when injected adapters or a router selected different models/voice, so configuration resolution is duplicated and cache identity can diverge from the actual request. Use the selected adapter/router configuration. [`pipelines/video/native_generator.py:604-631`]
- `shrink:` Resolve the object store once in `SudarshanApplication`; `build_object_store_from_env()` returns `None` for local mode and the application immediately creates another `LocalObjectStore`, then the mode is read again for artifacts and ingestion. Pass one resolved store/config through the application boundary. [`api/storage.py:442-459`; `integrations/deepseek_harness/application.py:84-149`]
- `shrink:` Replace the application’s 52 direct `os.getenv()` reads and duplicated run/ingestion scheduler defaults with one validated settings object; this removes configuration sprawl and makes the active deployment contract inspectable in one place. [`integrations/deepseek_harness/application.py:84-217,898-1551`]
- `fixed:` Centralize the five identical text-model fallbacks through
  `ProviderRouter.configured_model`; the legacy `CREWAI_MODEL` alias remains
  available but is resolved in one place. [`pipelines/*/agents.py`; `integrations/providers/router.py`]
- `fixed:` Simplify `ProviderRouter.select_model()` to return its current
  single provider directly; the dead conditional branch is gone.
  [`integrations/providers/router.py`]
- `delete:` Do not keep 46 tracked compiled `.js`/`.d.ts` files beside matching TypeScript under `deepseek-harness/**/src`; the root launch/tests use `.ts`, while package `main`/`types` point to `lib`. Generate derived output into `lib` only, or document a concrete source-runtime requirement before retaining these duplicates. The matched artifacts account for about 5,265 generated lines. [`deepseek-harness/packages/client/ui-conversation/src`; `deepseek-harness/packages/llm/llm-retry/src`; `deepseek-harness/packages/llm/token-meter/src`; `deepseek-harness/packages/plan/plan-mode/src`]
- `delete:` If the legacy external video worker is no longer a supported contract, remove the explicit `moneyprinterturbo|legacy` branch and the parallel compatibility renderer; the current default is native and the legacy route duplicates provider selection, pipeline branching, and renderer metadata. Keep this as conditional until the deployment contract drops that environment mode. [`pipelines/orchestrator/graph.py:187-199`; `pipelines/video/pipeline.py:76-128`; `pipelines/video/renderers.py:28-58`; `pipelines/video/contracts.py:158-205`]

### Fallbacks that are deliberate and should not be deleted as “stupid”

- DeepSeek Files API failure to bounded all-inline base64 is a tested request-preservation path; it is size-capped and does not trigger on caller cancellation.
- A stale DeepSeek file ID gets one bounded retry, not an unbounded retry loop.
- Invalid provider settings retain the last complete good snapshot; this protects a running process from a bad live settings write.
- The Python MCP adapter is an allow-listed security boundary, not a needless wrapper around `SudarshanApplication`.
- Local sandbox execution requires explicit opt-in; missing container runtime fails instead of silently executing on the host.
- Native video audio/image degradation to silent audio/title card is recorded in scene metadata and covered by tests, so it is an intentional partial-result contract.
- Renderer fallback resolution marks the result as degraded and detects cycles; it is not silently presenting a different renderer as equivalent.
- Local SQLite plus optional Redis observability and the local/built `dsh` launch choices are deployment seams with active tests, not proven deletion targets.

The broad `except Exception` scan also found catches at provider, plugin, persistence, codec, and adapter boundaries. Those should be reviewed for error classification separately; the presence of a broad catch alone is not proof of overengineering or a safe deletion.

`net: -5,300 lines, -0 deps possible.`

The three `fixed` items above are the code cleanup completed in the current
working tree. The remaining candidates are deliberately not claimed as fixed:
provider identity in video fingerprints, application-wide settings
consolidation, the object-store seam, generated Harness source artifacts, and
the legacy video worker require separate compatibility decisions and
regression coverage.

## 12. Timeout duplication, case memory, PPT constraints, and missing DAG responses

This section is based on source and tests, not on project Markdown. It separates confirmed behavior from recommendations.

### Timeout and repeated same-run execution

The repeated DeepSeek/provider request is an execution-cancellation bug, not primarily an admission-deduplication bug.

- The Node gateway aborts its HTTP wait after `PYTHON_API_TIMEOUT_MS` (default 30 seconds) in `backend-node/src/python-client.js:3-23` and `backend-node/src/config.js:51`. Aborting that fetch does not cancel the already-submitted Python worker.
- The Python `POST /runs` endpoint submits work to the application scheduler and returns 202; the HTTP disconnect is not connected to the run cancellation event (`api/server.py:464-523`). The run can therefore continue after the gateway/client has timed out.
- Python scheduler admission uses `run_id` as a primary key and rejects the same run ID with a different request hash; the same request is replayed idempotently (`api/scheduler.py:132-203`). That part is correct.
- The scheduler execution timeout is unsafe when enabled: `_execute_with_timeout` runs the attempt in a child `ThreadPoolExecutor`; on deadline it calls `future.cancel()` and shuts down without waiting (`api/scheduler.py:715-747`). Python cannot forcibly stop a thread that is already running. The timeout path also does not set the attempt's `cancel_event`.
- The worker treats `SchedulerExecutionTimeout` as retryable and `_schedule_retry` requeues the same logical `run_id` (`api/scheduler.py:662-690, 758-790`). The still-running timed-out child can overlap the next attempt. This produces two provider/DeepSeek calls with one logical run ID and can duplicate side effects.
- The current application default is `SUDARSHAN_MAX_ATTEMPTS=1` and execution timeout disabled unless configured (`integrations/deepseek_harness/application.py:175-199`), which reduces but does not eliminate duplicates caused by gateway/client retries, lease recovery, or manually reused identifiers.
- The Node transformation task lookup is idempotent only when the request includes a Mongo `idempotencyKey` (`backend-node/src/tasks.js:224-246`). `createRun()` does not pass an `Idempotency-Key` header to Python (`backend-node/src/python-client.js:27-50`), so a request without the gateway key can create another task/run on retry. The ingestion helper does pass the header, which is a separate path.

Safe fix order:

1. Propagate one cancellation signal from HTTP/task cancellation through the scheduler, orchestrator, Harness, and provider adapter. On scheduler deadline, set `cancel_event` before recording timeout.
2. Do not retry an attempt that timed out inside a non-killable thread. Either wait until cooperative cancellation proves the worker exited, or run each attempt in a killable subprocess/process and terminate the process before retrying.
3. Keep the lease longer than the maximum provider/graph deadline and do not reclaim an expired lease while the original attempt may still be alive.
4. Pass the client/gateway idempotency key through `createRun`; retain stable logical `run_id`, but record a separate attempt ID/provider request ID for every provider call.
5. Until cancellation/termination semantics are fixed, keep retry-on-timeout disabled for side-effecting runs. A timeout should be represented as `uncertain` when the provider may have accepted the request; blind retry is unsafe.

The regression test that is missing is: block the first execution past its deadline, make it observable if it continues, then assert that no second provider call starts until the first attempt has exited or been forcibly terminated. Existing scheduler coverage proves timeout status handling but not duplicate side-effect prevention.

### Case memory and request understanding

The current architecture already recalls bounded, scoped case context in Python, but it does not expose raw memory to the Harness model:

- `pipelines/orchestrator/graph.py:259-339` recalls user/case request context before deterministic understanding; `:426-504` recalls broader scoped memory after pipeline selection.
- `pipelines/orchestrator/understanding.py:161-253` is deterministic and explicitly discards `memory_context` (`del memory_context` around `:183-185`). It resolves pipeline/clarification and protects routing policy without an LLM call.
- `PromptCrafterAgent` receives bounded memory and embeds it into the generated prompt (`pipelines/orchestrator/understanding.py:254-358`). Generic text-generation pipelines reuse `resolved_memory_context` instead of recalling again (`pipelines/common/text_generation.py:192-230`).
- The Harness artifact profile intentionally exposes run/status/artifact/skill tools but no memory tool (`integrations/deepseek_harness/mcp_server.py:39-60`). Full MCP mode has `remember_sudarshan_context` and `recall_sudarshan_context` (`:379-397`), but those should not be treated as unrestricted model memory.

It is possible and useful to give DeepSeek bounded case context, but the safe design is hybrid:

- Let DeepSeek act as the conversational front door that interprets the user's words and proposes structured intent, requested pipeline, page budget, style, revision scope, and explicit constraints.
- Keep Python as the authority that authenticates user/case scope, recalls/redacts memory, validates the structured proposal, resolves the allowed pipeline, enforces classification/distribution, and executes the run.
- Add a bounded `prepare/understand_sudarshan_request` operation or a carefully scoped recall tool. It should accept authenticated user/case/task scope, enforce record/token limits, return provenance, redact sensitive content, and never expose Cognee credentials or a raw memory client.
- Reuse the prepared context/understanding in `run_sudarshan` through an opaque, signed or server-held preparation ID bound to user, case, task, and run. Do not send the same memory back through a second recall path.
- Do not delete request understanding entirely. Replace `RequestUnderstandingAgent` with a deterministic validator/normalizer if DeepSeek becomes the proposer. The backend must still reject model-selected unauthorized pipelines, changed case scope, invalid classification, and impossible output constraints.

Therefore, “remove request-understanding agent and make DeepSeek the request-understanding agent” is possible only as a responsibility move, not as removal of the validation boundary. Removing the deterministic backend guard would make routing and policy dependent on an untrusted model response.

### PPT page guardrails, custom colors, and layers

The reported “2 pages becomes 12” behavior is explained by several concrete gaps:

- `PresentationOutput` has only a generic `slides` list with a maximum of 15; it has no requested/maximum total page count, page budget, theme, color, or layer contract (`pipelines/ppt/schemas.py:245+`).
- The legacy PPT prompt asks for a complete deck but does not convert “2 pages” into a typed budget (`pipelines/ppt/tasks.py:20-55`). A user constraint remaining as prose cannot be enforced by a Pydantic maximum.
- `render_presentation()` always adds title, agenda, conclusion, and closing around content slides and reports `len(output.slides) + 4` (`pipelines/ppt/renderer.py:161-218`). Two requested total pages can therefore exceed the request before model over-generation is considered.
- `inspect_presentation()` only flags more than 15 content slides and bullet-density/empty-slide issues; it does not compare the rendered total against a user request (`pipelines/ppt/presentation_quality.py:86-118`). The generic quality gate has no PPT-specific page-budget issue (`pipelines/common/text_generation.py:171-230`).
- `PresentationStyleProfile` has hard-coded default colors/fonts and is not populated from user constraints (`pipelines/ppt/presentation_quality.py:14-23`). The renderer uses standard `python-pptx` layouts and hard-coded sizes/colors (`pipelines/ppt/renderer.py:32-187`).
- The flowchart renderer has `style_tokens` in its IR input but ignores them for rendering; SVG and PPTX colors are fixed (`pipelines/ppt/flowchart.py:75-82, 158-190, 194-253`). Its “layers” are deterministic DAG ranks from `layout_flowchart`, not a general editable z-order/layer model (`:111-155`).

The minimum correct PPT contract is:

1. Parse page requests into typed `total_page_budget` plus explicit optional fixed sections. Treat “2 pages” as total pages unless the user explicitly says “2 content slides”.
2. Normalize/truncate/regenerate before rendering, then assert the rendered slide count after rendering. Fixed title/agenda/conclusion/closing must be optional or included in the budget calculation.
3. Carry a validated theme/style token object through plan, renderer, and quality inspection. Apply allowed background/foreground/accent/font tokens deterministically and validate them after rendering.
4. Define what “layers” means: z-order for shapes, graph rank for DAGs, or semantic visual layers. Do not use one word for three different contracts.

AntV is a reasonable choice for infographic/diagram child visuals, not a fix for the page-budget bug. The existing AntV code renders declarative infographic output; the main editable PPT deck still uses `python-pptx`. A good architecture is to use AntV for a visual child artifact, then place its SVG/PNG (or a controlled editable conversion) into the budgeted PPT slide. Keep deck budgeting and style validation in the PPT pipeline.

### Why the DAG graph is not returned

The DAG engine itself persists and returns node state:

- `api/dag_scheduler.py:44-81` returns `run_id`, status counts, full nodes, dependencies, failure fields, output refs, and scheduler metrics.
- `pipelines/orchestrator/dag.py:329-364` reads durable SQLite node/run state, and `:370-390` stores the run and node graph.
- `pipelines/ppt/vertical.py:33-133` wraps this bridge and exposes `start_flowchart()`/`status()`.

But that path is disconnected from the public main-run response:

- `api/server.py:464-620` exposes `/runs`, `/runs/{run_id}`, wait, events, resume, and cancel; there is no DAG status/graph route.
- `SudarshanApplication.status()` projects LangGraph/application values and completed `response`/`responses`, but no `dag` or node-edge graph (`integrations/deepseek_harness/application.py:976-1063`).
- `PresentationVerticalSlice` keeps part of its run context in an in-memory `_runs` dictionary (`pipelines/ppt/vertical.py:51,102-113`), while the actual DAG is durable. After a process restart the graph may exist but the vertical quality/artifact projection can be missing.
- The main orchestrator returns pipeline responses; it does not automatically return the separate `DAGSchedulerBridge` graph. This is a response-contract/wiring omission, not evidence that the DAG admission engine failed.

Recommended contract: return a canonical `dag` object with `dag_run_id`, nodes, dependencies/edges, node status, output refs, repair attempts, and failure details. Expose it either inside `/runs/{run_id}` and MCP status or through `GET /runs/{run_id}/graph` plus a `get_sudarshan_graph` MCP tool. Wire the intended production PPT path to the same durable bridge, and add tests proving graph visibility in queued, running, completed, failed, and post-restart states.

### Required regression coverage before changing architecture

- Scheduler: timed-out provider attempt cannot overlap a retry; gateway timeout followed by client retry with the same key creates one task/run.
- Memory: context is scoped to authenticated user/case/task, bounded, redacted, provenance-carrying, and reused once between preparation and execution.
- Request understanding: model proposal is schema-validated; backend still owns pipeline allow-list, classification, distribution, and case scope.
- PPT: “2 total pages” renders exactly two; “2 content slides” has an explicit separate behavior; fixed sections are budgeted; custom tokens survive into SVG/PPTX; z-order/layer assertions are testable.
- DAG: public status returns nodes and edges for the actual run, not only the internal vertical slice, and remains readable after restart.

## 13. Pipeline audit completion matrix (2026-09-16)

This matrix records the staged source audit. “Current” describes observed code
paths; “improved” is the target contract, not a claim that the target has been
implemented. Reference repositories were used as design evidence only; they
were not changed or imported as runtime dependencies.

| Area | Current behavior and failure mode | Improved contract |
| --- | --- | --- |
| Advisory | Evidence and quality are partly model-gated; artifact paths are run-based; automatic case-memory writes can happen before human release. | Deterministic evidence/linkage/quality validation, immutable attempt-scoped artifacts, and approved-only durable case memory. |
| Executive summary | Basic non-empty schema checks; no complete evidence-ID coverage or request-constraint validator. Shared text flow overwrites pipeline options. | One persisted typed request spec, evidence coverage checks, preserved pipeline options, and blocked delivery on failed deterministic checks. |
| Presentation/PPT | Renderer adds fixed slides, so a requested two-page deck can become twelve; style tokens and layers are not reliably applied; the legacy path rebuilds the deck. | Explicit total-page versus content-page budget, stable `slide_id`, validated theme/layer tokens, per-slide artifacts, dependency invalidation, and PPT Master round-trip preservation. |
| Infographic/diagram | AntV style/theme data is not consistently forwarded; native failure can become a fallback SVG; the diagram package is not a top-level registry pipeline; diagram export families converge on flowchart behavior. | Canonical visual IR, explicit renderer mode, fail-closed native promotion, palette/layer/accessibility checks, and separately registered diagram capabilities. |
| AntV runtime | Full suite currently exposes a deadline collision: Python outer timeout and Node SSR timeout can both be 30 seconds. Fallback can use `foreignObject`, which later export safety rejects. | Nested deadlines with shutdown headroom; native/fallback status is explicit; fallback is preview-only unless its output passes the same safe-export contract. |
| Video | Scene manifests and bounded parallelism exist, but provider submission lacks complete idempotency/reconciliation. Missing media can become title cards, silent audio, or partial output that still succeeds. | Provider submit/status/reconcile/cancel contract, attempt-scoped scene identities, explicit `partial`/`provider_pending`, and release only after media-quality validation. |
| LinkedIn | Draft-only and approval boundaries exist, but claim bindings do not require valid evidence references; timeout can be mapped to draft-only even when publication may have occurred. | Evidence-complete claims, deterministic humanizer/quality checks, `provider_pending` reconciliation, and approved-memory/publication receipts. |
| Ingestion/evidence | Governed HTTP ingestion is bounded and idempotent, but direct `ingest_file()` bypasses source safety and partial extraction can still project durable facts. | One governed admission path, partial evidence status, no durable FACT projection without quality/provenance approval, and typed persisted manifests. |
| Orchestrator/A2A | Local child execution is typed and parallel, but child timeouts use non-killable threads, child IDs are regenerated per invocation, and only a global A2A card exists. | Stable logical child IDs, separate attempt IDs, fenced/reconciled local and remote execution, per-pipeline cards only for independently deployable agents, and one authoritative orchestrator. |
| Harness/MCP | The artifact profile reduces the surface, but `run_sudarshan` and `start_sudarshan_run` overlap; lineage fields and broad dictionaries are model-facing; native trajectory controls are disabled in the overlay. | One canonical admission tool, typed response contracts, server-owned lineage, role-scoped profiles, and a host-side trajectory projection over the same backend event stream. |
| Trajectory/usage | Progress and observability are durable and cursor-based, but events lack attempt/lane/provider identity. Runtime and progress events can carry the same usage receipt and be summed twice. | Redacted event bridge with `(run_id, source_sequence)` deduplication, parent/node/child/attempt/lane fields, and usage aggregation by unique `usage_id`. |

### Verified test evidence

- Focused Harness/scheduler/application/observability tests: **40 passed**.
- Full repository suite: **367 passed, 8 skipped, 1 failed**.
- The failing test is `tests/pipeline/test_json_renderer_contracts.py` and
  fails because `AntVInfographicRenderer(..., timeout_seconds=30)` reaches its
  outer deadline while the nested AntV SSR deadline is also 30 seconds.
- Re-running that test with `ANTV_SSR_TIMEOUT_MS=1000` passes by taking the
  deterministic fallback path; this does **not** prove native AntV success and
  is itself evidence that renderer mode must be asserted by the test.

### Completion boundary

The audit is complete; implementation is not. The highest-risk work remains
execution cancellation/reconciliation, deterministic artifact guardrails, the
public DAG projection, and the Harness trajectory adapter. No reference
repository was modified and no runtime code was changed during this audit.
