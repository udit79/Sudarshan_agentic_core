# Running benchmarks

Follow [Get started with the Python SDK](docs/user/guide/python-sdk.md) to
install the SDK and run the `jsonrpc-agent` minimal variant. Use separate
workspaces and session IDs for independent benchmark tasks.

## Sudarshan ticket acceptance benchmark

This is the tester-facing matrix for the Sudarshan agentic workflow. A ticket
is not complete because a unit test passes: record the focused test result,
the sanitized run/event/artifact evidence, and the environment used.

### Run the deterministic regression set

From the Sudarshan repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest --basetemp=.pytest-tmp -q `
  tests/component/test_scheduler.py `
  tests/component/test_scheduler_fencing.py `
  tests/component/test_shared_scheduler.py `
  tests/component/test_np11_mcp_a2a.py `
  tests/component/test_a2a.py `
  tests/component/test_dag_scheduler.py `
  tests/component/test_np06_incremental.py `
  tests/component/test_presentation_quality.py `
  tests/component/test_np10_ingestion.py
```

If the full suite is run, install the test dependencies first. A missing
optional chart dependency such as `matplotlib` is an environment failure, not
a passing benchmark result.

### Jev test modes

Jev is a hosted OpenRouter API; it is not downloaded locally. Use two explicit
modes:

```powershell
# Offline deterministic mode: no network calls
$env:SUDARSHAN_JEV_ROUTING_ENABLED="false"
$env:SUDARSHAN_JEV_JUDGE_ENABLED="false"

# Live Jev mode: requires outbound HTTPS and OPENROUTER_API_KEY
$env:SUDARSHAN_JEV_ROUTING_ENABLED="true"
$env:SUDARSHAN_JEV_JUDGE_ENABLED="true"
```

Never print `OPENROUTER_API_KEY` or include it in benchmark output. Live tests
must record the model version, latency, decision outcome, and fallback count,
but not the authorization header or raw provider payload.

### Ticket cases

| Ticket | Test case | Pass evidence |
|---|---|---|
| NP-01 | Submit the same idempotency key twice; force a timeout and release a late first attempt | One logical run, unique attempts, no overlapping side effect, stale attempt cannot finish the run |
| NP-02 | Replay trajectory/events from sequence 0 and reconnect after terminal completion | Stable event IDs, no duplicates, terminal event closes active view, safe fields only |
| NP-03 | Run with retry and cache hit; compare usage and trajectory totals | One usage receipt per provider request, retries/cache separated, totals do not double-count |
| NP-04 | Prepare a request with scoped User/Case/Task evidence and an ambiguous request | Opaque preparation ID, bounded context, correct scope, clarification instead of guessed routing |
| NP-05 | Request exactly two PPT pages/slides and invalid color/layout constraints | Exact count, typed rejection or repair, no invalid artifact reaches the renderer |
| NP-06 | Generate a PPT, then request “change slide 4” | New artifact version, targeted slide/dependent rerender only, unchanged slide hashes preserved |
| NP-07 | Render dense/off-canvas/low-contrast content | Deterministic quality failure, report and preview available, degraded output not silently promoted |
| NP-08 | Restart the worker/API after a DAG run is queued and after a node completes | DAG and node state recover, dependencies remain correct, no duplicate child execution |
| NP-09/10 | Ingest a valid document, duplicate it, partially fail extraction, then resume | Idempotent source identity, safe partial state, bounded evidence, resumable processing |
| NP-11 | Run create/status/wait/cancel/resume/artifact through MCP and A2A | Same run identity and policy across transports; no raw memory, credentials, or hidden reasoning |
| NP-12 | Execute this matrix plus the full suite | All hard gates pass; failures are classified and archived; no hidden fallback success |
| NP-13/14/16 | Cross-user/case artifact and memory access; expire or supersede a source | Unauthorized reads fail, stale data is excluded, deletion/supersession is auditable |
| NP-15/17/18/19 | Preference opt-in, large input, provider failure, and consented learning cases | Bounded resources, explicit recovery, no implicit preference learning, reversible decisions |

### Required artifact for every case

Store a sanitized record containing:

```json
{
  "ticket": "NP-06",
  "case": "ppt_single_slide_revision",
  "run_id": "run-...",
  "status": "succeeded",
  "attempts": 1,
  "event_ids": ["evt-..."],
  "artifact_ids": ["artifact-..."],
  "quality_status": "passed",
  "fallback_used": false,
  "issues": []
}
```

Do not store prompts, raw attachments, raw memory, API keys, provider payloads,
or chain-of-thought. A ticket remains open when the code path exists but its
required acceptance evidence is missing.
