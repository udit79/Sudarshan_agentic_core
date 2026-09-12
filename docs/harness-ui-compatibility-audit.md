# Harness UI compatibility audit

Date: 2026-09-12  
Scope: the native DeepSeek Harness web profile with
`integrations/deepseek_harness/sudarshan.cordis.yml` applied, including the
Sudarshan operations plugin and the inherited Harness web controls.

The audit compares each visible control with the Sudarshan application
contracts in `integrations/deepseek_harness/mcp_server.py`, `api/server.py`,
`integrations/deepseek_harness/application.py`, and
`deepseek-harness/packages/experimental/client-ui-sudarshan-operations`.

## Compatibility matrix

| Surface/control | Current result | Evidence and decision |
| --- | --- | --- |
| Session sidebar, chat composer, new session, session navigation | Compatible as Harness shell | The shell can host the governed Sudarshan MCP agent. Session history is not case-memory history and must remain labelled as such. |
| Clarification/user-question UI | Compatible | The Sudarshan profile intentionally keeps clarification support; answers must resume the durable run through the backend. |
| Sudarshan operations header action | Compatible | Opens the session-scoped details panel and does not create a second session store. |
| Monitor/evidence/artifact/ingestion tabs and Refresh | Compatible | Read-only safe projections; evidence contains references and metadata rather than raw source or memory. |
| Artifact Preview and Open/download | Compatible when manifest routes are present | Uses stable preview/download URIs and disables the action when the projection has no route. Deployment still must provide authenticated same-origin access. |
| Artifact Review / Approve / Reject | UI exists, action not compatible in the live bridge | The bridge posts `/runs/{run_id}/resume` but does not send the required `X-Operator-Id`; the API middleware returns 401 for state-changing requests. |
| Ingestion Retry failed stage | Not compatible | `OperationsBridge` declares `retryIngestion`, but the live bridge never implements it and the API has no retry endpoint. The button is permanently disabled. |
| Ingestion Cancel | Not compatible | The API has `/ingestions/{ingestion_id}/cancel`, but the projection has no `ingestion_id` and the live bridge never implements `cancelIngestion`. |
| Generic attachment button/drop zone | Not compatible with Sudarshan ingestion | Harness attachments are not translated into Sudarshan's authenticated multipart `/ingest` contract, classification, case, task, and idempotency fields. |
| Workspace/browser/directory picker | Not compatible for production artifact work | These controls expose Harness workspace/filesystem semantics, while the governed profile prohibits filesystem capability and Sudarshan owns source/object storage. The browse picker is only a preview/development compatibility aid. |
| Generic model selector and model settings | Not compatible | Harness model selection changes the Harness provider seat; it does not change Sudarshan's backend provider/model routing, budgets, or receipts. The settings surface can also suggest unsupported browser-managed credentials. |
| Generic permission presets | Not compatible | Harness permission presets describe generic shell/filesystem/web capabilities that the Sudarshan artifact profile does not expose. They must not imply authority over Sudarshan policy. |
| Generic approval panel | Not compatible as the artifact approval surface | Harness tool approval is not the same as Sudarshan artifact/run approval. Sudarshan approval is a typed resume decision with actor, case, task, and audit data. |
| Generic trajectory/tool inspector | Not proven safe | It is not backed by the safe Sudarshan projection contract and may render MCP arguments/results. It needs an allow-listed redacted view or must be hidden. |
| Generic deliverables row | Not compatible until adapted | Harness produced-file rows are not bound to Sudarshan artifact manifests, classification, quality, renderer, and authenticated stable routes. |
| Schedule, jobs, goals, plans, workflows, subagents, command palette, skill/reference menus | Correctly disabled for this profile | The overlay disables these generic controls because their authority and lifecycle are not Sudarshan's. Scheduling remains a backend backlog item. |
| Agent preset and plugin inventory/settings | Correctly disabled | The profile pins one system-owned Sudarshan Artifact Agent and excludes shipped/user-authored presets and generic plugin mutation. |

## Tickets generated

The audit-derived tickets are added to the remaining-work plan as T84–T90.
They are intentionally open; the audit did not claim that a control is fixed
merely because it is hidden or disabled.

## Verification performed

- Inspected the native profile overlay and web bundle rows.
- Inspected every control exposed by the Sudarshan operations plugin.
- Matched bridge methods to FastAPI routes and middleware requirements.
- Ran the existing Harness profile/component checks and frontend plugin tests
  where the local dependency environment permitted them.

The final acceptance gate for T90 is a browser run with the actual overlay,
authenticated identity, and a test backend; static source inspection is not a
substitute for that staging check.
