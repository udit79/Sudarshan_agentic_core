# Sudarshan operations projections

This browser-only plugin adds the operator surface for Sudarshan without replacing the Harness shell, session sidebar, or tool inspector.

It contributes:

- a session-header `Sudarshan ops` action;
- an additive details-panel surface for execution lanes, wait reasons, safe evidence references, artifact quality metadata, and ingestion stages;
- a session-scoped selected-tab preference in `sessionStorage`.

The current `previewProjection()` adapter is deliberately fixture-backed. It is not a claim that a run succeeded and it never renders raw extracted source text, prompts, memory payloads, provider payloads, credentials, or hidden reasoning. Backend integration should replace that adapter with the typed `RunStatusProjection`/artifact manifest projection described in `docs/frontend-integration.md` and preserve the same safe field boundary.

Artifact buttons stay disabled when a preview is unavailable. The backend adapter should provide authenticated preview/download routes, renderer/version metadata, quality reports, evidence IDs, classification markings, and typed status projections. SSE/polling reconnect should update the projection by stable `run_id`, `task_id`, and cursor; it should not create a second chat/session store. Approval inboxes and release/operations gates are intentionally deferred until their backend contracts are connected.
