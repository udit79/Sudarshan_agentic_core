# Harness–Sudarshan artifact flow

The Harness is the conversation and wake-up layer. Sudarshan owns admission,
file extraction, evidence scope, pipeline execution, validation, artifact
storage, and quality gates.

```mermaid
sequenceDiagram
    participant U as User
    participant H as Harness agent
    participant M as Sudarshan MCP
    participant Q as Durable scheduler
    participant P as Pipeline + validators
    participant A as Artifact store

    U->>H: Request artifact + attach documents
    H->>M: start_sudarshan_run(metadata: attachment refs)
    M->>Q: Validate, deduplicate, enqueue run
    Q-->>M: accepted + run_id (immediate)
    M-->>H: 200-style accepted response
    H-->>U: Accepted; processing in background
    Q->>P: Extract, ground, generate, validate
    P->>A: Write verified artifact + manifest
    Q->>M: Persist terminal status + wake event
    M-->>H: completion_callback_url event
    H->>M: get_sudarshan_status(run_id)
    H->>M: get_sudarshan_artifact(artifact_id)
    M-->>H: Safe manifest + download/preview URI
    H-->>U: Show verified artifact

    U->>H: Change slide 4
    H->>M: revise_sudarshan_slide(parent_artifact_id, slide_id, instruction)
    M->>Q: Enqueue revision with idempotency key
    Q->>P: Apply scoped revision
    P->>A: Incremental render of slide 4 + dependents
    A-->>H: New artifact version via terminal wake event
    H-->>U: Show revised artifact
```

## Agent rules

- Use `start_sudarshan_run` for new asynchronous artifacts.
- Pass attachment references in scoped metadata; do not expose provider
  credentials or raw memory to the Harness.
- Treat the returned `run_id` as an acceptance receipt, not completion.
- On wake, fetch status and the verified artifact manifest before presenting it.
- Use `revise_sudarshan_slide` for a slide-local PPT change.
- Use `resume_sudarshan` for clarification or approval states.
- Do not expose private reasoning or claim success from an unverified tool call.

## Wake contract

If `completion_callback_url` is supplied and matches
`SUDARSHAN_HARNESS_CALLBACK_BASE_URL`, Sudarshan posts a terminal event:

```json
{
  "event_id": "run.completed:run-123:succeeded",
  "event_type": "run.completed",
  "run_id": "run-123",
  "status": "succeeded",
  "artifact_ids": ["artifact-456"],
  "safe_summary": "succeeded"
}
```

The Harness must deduplicate by `event_id`, then call the read-only status and
artifact MCP tools. If the Harness is offline, it should resume from the
durable `run_id` using `wait_sudarshan` or `get_sudarshan_status`.
