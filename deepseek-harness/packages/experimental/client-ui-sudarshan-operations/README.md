# Sudarshan operations projections

This browser-only plugin adds the operator surface for Sudarshan without replacing the Harness shell, session sidebar, or tool inspector.

It contributes:

- a session-header `Sudarshan ops` action;
- an additive details-panel surface for execution lanes, normalized wait/cancel
  states, safe telemetry, fallback notices, evidence references, artifact
  quality metadata, and ingestion stages;
- a session-scoped selected-tab preference in `sessionStorage`.

The plugin installs a live typed bridge when loaded. It reads the backend
`RunStatusProjection`, hydrates terminal artifact manifests through the stable
artifact routes, and listens to the backend run-events stream. It also watches
native Harness `tool/call`/`tool/result` events, so the `run_id` returned by
`start_sudarshan_run` is automatically bound to the active Harness session.
When the API is unavailable, the panel falls back to the explicitly labelled
`previewProjection()` fixture. It never renders raw extracted source text,
prompts, memory payloads, provider payloads, credentials, or hidden reasoning.
The live bridge stores the greatest received event sequence per session and
reopens the SSE stream with `after_sequence`, so reconnects do not replay the
stream from zero. Backend statuses such as approval, provider-pending,
retrying, capacity wait, partial, failed, and cancelled remain distinct in the
operator projection.

Artifact buttons stay disabled when a preview is unavailable. The backend adapter should provide authenticated preview/download routes, renderer/version metadata, quality reports, evidence IDs, classification markings, and typed status projections. SSE/polling reconnect should update the projection by stable `run_id`, `task_id`, and cursor; it should not create a second chat/session store. Approval inboxes and release/operations gates are intentionally deferred until their backend contracts are connected.
