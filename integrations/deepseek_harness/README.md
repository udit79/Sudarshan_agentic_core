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
- `get_sudarshan_status` returns frontend-safe progress events.

The server uses the configured SQLite LangGraph checkpointer, so these tools
share a durable run identity within the service process instead of creating a
new in-memory orchestrator for every call.

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

The MCP server is an application adapter, not a second orchestrator: it calls
the same application service as the JSONL runner. Do not place Cognee keys in
Harness workflow scripts or pass them into an E2B sandbox.
