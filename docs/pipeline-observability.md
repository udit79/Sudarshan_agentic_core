# Pipeline observability

Sudarshan has three complementary views of one run. They are intentionally
separate: the progress stream explains what the user can see, the DAG explains
parallel dependencies, and the operator trace explains safe runtime details.

## What to monitor

1. Start one run and keep the returned `run_id`.
2. Poll `get_sudarshan_status(run_id)` or subscribe to
   `GET /runs/{run_id}/events?after_sequence=N`. This is the ordered,
   frontend-safe lifecycle: request preparation, bounded recall, prompt
   planning, pipeline execution, quality, repair, and artifact publication.
3. Poll `get_sudarshan_dag(run_id)` or `GET /runs/{run_id}/dag` to see child
   nodes, dependencies, lanes, and which parallel branch is waiting or failed.
4. Use `get_sudarshan_usage(run_id)` or `GET /runs/{run_id}/telemetry` for
   token, cost, cache, latency, and duplicate-safe usage totals.
5. Operators can use `get_sudarshan_observability(run_id, operator_id)` or
   `GET /runs/{run_id}/observability` with the `x-operator-id` header for the
   sanitized trace of provider and memory operations.
6. Harness clients can use `get_sudarshan_trajectory(run_id, operator_id)` or
   `GET /runs/{run_id}/trajectory` for those safe events plus grouped parallel
   lane summaries. This is a display projection; the durable DAG remains the
   authority for dependencies and completion.

## Cognee visibility

MemoryManager emits these operator events through the existing observability
store:

- `memory.recall.started`
- `memory.recall.completed`
- `memory.recall.failed`
- `memory.remember.started`
- `memory.remember.completed`
- `memory.remember.failed`

Completed recall events include the backend name, stage, query hash, requested
`top_k` and token budget, backend result count, accepted result count, bounded
retrieval trace ID, and duration. Remember events include the memory ID/type,
scope, backend response keys, and duration. Failure events include only the
exception class as `error_code`.

Returned Cognee text, prompts, model reasoning, credentials, and provider
payloads are never placed in progress or operator telemetry. To inspect the
actual bounded context, use the authorized artifact/evidence boundary or the
local memory backend under controlled development access; do not add raw memory
to the Harness event stream.

## Parallel work

The event stream is a time-ordered projection and may interleave child events.
Use `node_id`, `parent_node_id`, `child_id`, `lane_id`, and `attempt_id` to
group them. The DAG is the authoritative dependency view; the trace is the
authoritative diagnostic view. A child finishing before another child does not
mean the parent is complete until the DAG dependency condition is satisfied.

The trajectory does not invent steps from model narration. It only projects
events recorded by Sudarshan, including `memory.*`, `skill.*`, cache, quality,
fallback, and provider-receipt fields when those producers emit them.

## Minimal operator loop

```text
start_sudarshan_run -> run_id
        |
        +--> get_sudarshan_status(after_sequence)   # live lifecycle
        +--> get_sudarshan_dag(after_revision)       # parallel branches
        +--> get_sudarshan_observability             # Cognee/provider details
        +--> get_sudarshan_trajectory                # Harness timeline + lanes
        +--> get_sudarshan_usage                     # reconciled budget totals
```

The observability endpoint is for operators and diagnostics, not for the model
to receive raw context. Keep it disabled from artifact/specialist MCP profiles
unless a deployment explicitly needs operator diagnostics.
