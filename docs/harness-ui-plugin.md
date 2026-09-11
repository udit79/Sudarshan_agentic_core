# Harness UI composition

Sudarshan's visual changes are loaded as replaceable Harness plugins when that
profile is enabled. The Sudarshan core does not require the DeepSeek Harness
checkout to execute runs, render artifacts, or serve the native dashboard.

## Product plugins

| Package | Owns | Does not own |
| --- | --- | --- |
| `@deepseek-ai/dsh-experimental-client-ui-sudarshan` | Sidebar mark, wordmark, and empty-session hero mark | Sessions, model calls, MCP, artifacts, or routing |
| `@deepseek-ai/dsh-experimental-client-ui-sudarshan-theme` | Product stylesheet and lifecycle-owned `<style>` tag | Generic Harness theme services and settings |
| `@deepseek-ai/dsh-experimental-client-ui-sudarshan-operations` | Session-scoped safe run/evidence/artifact/ingestion projections | Backend execution, session history, raw source/prompt/memory/provider payloads |

The web bundle registers both packages in
`deepseek-harness/packages/bundle/web-app/cordis.patch.yml`. To create a
white-label build, replace those two package rows with another brand/theme
pair; the core Harness packages and the Sudarshan backend remain unchanged.

The safe execution monitor, evidence drawer, artifact workspace, and ingestion
stages now live in the additive
`@deepseek-ai/dsh-experimental-client-ui-sudarshan-operations` Harness plugin.
It installs a typed live bridge when the native plugin loads. The bridge reads
the backend's safe run projection, refreshes it from the run-events SSE stream,
and opens only stable artifact preview/download routes. A host can bind a
Harness session to a backend run with `bindRun(sessionId, runId)`; until then,
the session ID is used as the run ID. If the API is unavailable, the panel
falls back to its explicitly labelled preview projection. Disabled actions are
explicit capability states, not fake buttons.
The plugin does not copy the standalone dashboard or create a second chat
store: Harness owns the maintained side chat/session list, while this panel is
keyed by the active session ID and persists only its selected tab locally.
The bridge reads `SUDARSHAN_API_ORIGIN` or defaults to `http://localhost:8000`.
For a gateway deployment, set this to the authenticated backend origin exposed
to the Harness browser; do not put Cognee credentials in the browser or
configure the bridge to call Cognee directly.
The API CORS example includes the native Harness origins on port 3080.
Approval inboxes and release/operations gates remain planned follow-up surfaces
until their backend decision and release contracts are connected.

## Harness independence

The reusable skill catalog lives in `skills/catalog.py`, and pipeline
execution uses the core `PipelineAdapter`/`PipelineRegistry` contract. DeepSeek
Harness is one optional session/MCP adapter. Other harnesses or skill hosts can
use the same application boundary through MCP, A2A, JSONL, HTTP, or Python
entry points without importing DeepSeek code. Reference repositories informed
the design of skills, renderers, and memory, but are not runtime dependencies.

Backend integration must keep the safe boundary from `docs/frontend-integration.md`:
source references and evidence IDs are allowed, but raw extracted text,
prompts, memory payloads, provider payloads, credentials, and hidden reasoning
are not rendered. Artifact previews/downloads must use authenticated routes and
carry classification, renderer/version, and quality metadata.

## Local build

From `deepseek-harness/`:

```powershell
node node_modules/typescript/bin/tsc -b packages/experimental/client-ui-sudarshan/tsconfig.json
node node_modules/typescript/bin/tsc -b packages/experimental/client-ui-sudarshan-theme/tsconfig.json
node node_modules/typescript/bin/tsc -b packages/experimental/client-ui-sudarshan-operations/tsconfig.json
node node_modules/tsdown/dist/run.mjs --config packages/experimental/client-ui-sudarshan/tsdown.config.ts
node node_modules/tsdown/dist/run.mjs --config packages/experimental/client-ui-sudarshan-theme/tsdown.config.ts
node node_modules/tsdown/dist/run.mjs --config packages/experimental/client-ui-sudarshan-operations/tsdown.config.ts
```

The normal repository build should be preferred once the workspace package
manager has linked the new packages. The package lock contains workspace links
for both additions.

## Preview-state security

`.dsh-preview/` is local Harness state and is ignored. It must never be copied
into a commit because it can contain credentials, session transcripts, caches,
and machine-specific absolute paths. A credential that was present in an
earlier commit must be revoked/rotated even after the file is removed locally;
removing a working-tree file does not erase Git history.
