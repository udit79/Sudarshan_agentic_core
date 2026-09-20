# Code Review, Optimisation & Jev Judge Plan

## Confirmed Design Decisions

| # | Decision |
|---|---|
| 1 | **Keep Jev** (`typesafe/jev-1.13` via OpenRouter) for both routing and judging |
| 2 | **Jev judge blocks on schema/quality failures** (never hallucinates so it can gate); on pass it auto-forwards and always logs the scores |
| 3 | **Fix the full scheduler thread-safety issue** (set `cancel_event` before timeout, add `Idempotency-Key` to `createRun`) |
| 4 | **All sub-tasks, in order**: Sub-Task 1 → 2 → 3 → 4 → 5 → 6 |

---

## Already Confirmed Done — Do Not Re-Implement

| Item | Evidence |
|---|---|
| Jev routing on by default | `understanding.py:161` — `SUDARSHAN_JEV_ROUTING_ENABLED=true` |
| Jev judge on by default | `graph.py:1452` — `SUDARSHAN_JEV_JUDGE_ENABLED=true` |
| `OPENROUTER_API_KEY` in `.env.example` | `.env.example:17-28` |
| Stage caps named in `constants.py` | `constants.py:19,24,28,41` |
| `advisory/crew.py:274` rationale comment present | "A memory outage must not hide the original pipeline failure." |
| `observability.py:566` intentional fire-and-forget | `failed_exports += 1` — telemetry export |
| `cache.py:325`, `audit_logger.py:106` re-raise after rollback | Correct SQLite context-manager pattern |
| `linkedin/voice_profile.py:43` returns None intentionally | Validation guard |
| `skill_runtime.py:256`, `dag.py:459,882` — `# noqa: BLE001` | Already documented |

---

## Sub-Task 1 — Fix Two Silent Exception Swallowers in `graph.py`

### Intent
Two bare `except Exception` clauses in [`pipelines/orchestrator/graph.py`](pipelines/orchestrator/graph.py)
swallow errors with no log output, making failures in LangGraph state reads and audit
writes completely invisible at runtime.

### Expected Outcomes
- [`graph.py:505`](pipelines/orchestrator/graph.py:505): LangGraph state-read failures log at WARNING with `exc_info=True` before falling back to `{}`
- [`graph.py:567`](pipelines/orchestrator/graph.py:567): Audit write failures log at WARNING with `exc_info=True` before returning

### Todo List
- [ ] At `graph.py:505`: change `except Exception:` → `except Exception: _log.warning("LangGraph state read failed for run %s; treating as not found", run_id, exc_info=True)`
- [ ] At `graph.py:567`: change `except Exception: return` → `except Exception: _log.warning("Orchestrator task audit write failed at step %r", step, exc_info=True); return`

### Relevant Context
- [`pipelines/orchestrator/graph.py:500-570`](pipelines/orchestrator/graph.py:500) — both clauses are in `cancel_run()` and `_write_orchestrator_task_memory()`
- `_log` is already defined at the top of `graph.py`

### Status
[ ] pending

---

## Sub-Task 2 — Centralise Context Truncation (Token Budget Bypass Fix)

### Intent
Three places bypass the `STAGE_RECALL_GROUNDING_TOKENS=2600` cap by slicing context
with raw character counts. A prompt receiving 12,500 tokens of context when the ledger
budgets 2,600 wastes LLM spend and can cause silent quality regressions.

**Verified violations:**

| File | Slice | Approx tokens (4 chars/token) | Cap |
|---|---|---|---|
| [`video/pipeline.py:67`](pipelines/video/pipeline.py:67) | `[:30000]` | ~7,500 | **2.9× over** |
| [`video/pipeline.py:98`](pipelines/video/pipeline.py:98) | `[:20000]` | ~5,000 | **1.9× over** |
| [`understanding.py:59`](pipelines/orchestrator/understanding.py:59) | `max_length=50000` | ~12,500 | **4.8× over** |

Also: [`graph.py:99`](pipelines/orchestrator/graph.py:99) hard-codes `6000` inline
instead of importing `RUN_DEFAULT_TOKEN_BUDGET` (already imported at line 41).

### Expected Outcomes
- A single `truncate_to_token_budget(text, budget)` utility exists and is used everywhere
- All three char-slice bypass points replaced with that utility
- `PromptPlan.memory_context` max capped at `STAGE_RECALL_GROUNDING_TOKENS * 4`
- Inline `6000` replaced with `RUN_DEFAULT_TOKEN_BUDGET`

### Todo List
- [ ] Add to [`pipelines/orchestrator/constants.py`](pipelines/orchestrator/constants.py):
  ```python
  def truncate_to_token_budget(text: str, budget: int) -> str:
      """Cap text to approximately `budget` tokens using a 4-chars-per-token estimate."""
      return text[: budget * 4]
  ```
  Add it to `__all__`.
- [ ] In [`video/pipeline.py:67`](pipelines/video/pipeline.py:67): import and replace `[:30000]` with `truncate_to_token_budget(…, STAGE_RECALL_GROUNDING_TOKENS)`
- [ ] In [`video/pipeline.py:98`](pipelines/video/pipeline.py:98): replace `[:20000]` with `truncate_to_token_budget(…, STAGE_RECALL_GROUNDING_TOKENS)`
- [ ] In [`understanding.py:59`](pipelines/orchestrator/understanding.py:59): change `max_length=50000` → `max_length=STAGE_RECALL_GROUNDING_TOKENS * 4`
- [ ] In [`graph.py:99`](pipelines/orchestrator/graph.py:99): replace `6000` with `RUN_DEFAULT_TOKEN_BUDGET`

### Relevant Context
- [`pipelines/orchestrator/constants.py`](pipelines/orchestrator/constants.py) — add utility here; all stage caps already live here
- [`pipelines/orchestrator/understanding.py:55-63`](pipelines/orchestrator/understanding.py:55) — `PromptPlan` field definitions
- `STAGE_RECALL_GROUNDING_TOKENS` and `RUN_DEFAULT_TOKEN_BUDGET` are already exported from `constants.py`

### Status
[ ] pending

---

## Sub-Task 3 — PPT Page Budget Enforcement ("2 pages" → 12 slides fix)

### Intent
A user request for "2 pages" produces a 12-slide deck because
[`renderer.py:161-218`](pipelines/ppt/renderer.py:161) unconditionally adds title +
agenda + conclusion + closing on top of however many content slides the model
generated. No typed `total_page_budget` field exists to constrain this.

### Expected Outcomes
- A `total_page_budget: int | None` field exists on the PPT plan/schema
- The renderer respects it: fixed sections count toward the budget, not beyond it
- The quality inspector flags a `page_budget_exceeded` issue when rendered count exceeds budget

### Todo List
- [ ] In [`pipelines/ppt/schemas.py`](pipelines/ppt/schemas.py): add `total_page_budget: int | None = Field(default=None, ge=1, le=50)` to the appropriate plan schema (the one passed to the renderer)
- [ ] In the PPT task prompt builder ([`pipelines/ppt/tasks.py:20-55`](pipelines/ppt/tasks.py:20)): parse `"(\d+)\s*(page|slide)"` from `request.query` and set `total_page_budget` before the crew runs
- [ ] In [`pipelines/ppt/renderer.py:161-218`](pipelines/ppt/renderer.py:161): when `total_page_budget` is set, compute `max_content_slides = max(1, total_page_budget - 4)` and truncate `output.slides` to that count before rendering
- [ ] In [`pipelines/ppt/presentation_quality.py:86-118`](pipelines/ppt/presentation_quality.py:86): add check — if `total_page_budget` is set and `rendered_count > total_page_budget`, emit a `page_budget_exceeded` issue

### Relevant Context
- [`pipelines/ppt/schemas.py`](pipelines/ppt/schemas.py) — schema definitions; `SlideSpec`, `SlideDeck` are the primary types
- [`pipelines/ppt/renderer.py:161-218`](pipelines/ppt/renderer.py:161) — slide assembly; the 4 fixed slides are added here
- [`pipelines/ppt/tasks.py:20-55`](pipelines/ppt/tasks.py:20) — legacy prompt builder
- [`pipelines/ppt/presentation_quality.py:86-118`](pipelines/ppt/presentation_quality.py:86) — quality inspector

### Status
[ ] pending

---

## Sub-Task 4 — Wire Jev Judge to Block on Failures, Auto-Forward on Pass

### Intent
Currently the Jev judge at [`graph.py:1531-1538`](pipelines/orchestrator/graph.py:1531)
emits a `partial` progress event when `needs_retry >= threshold` but does **not** block
or retry — the flagged output still reaches the user.

**Confirmed design (from user decision #2)**:
- If Jev flags a schema/quality issue (`needs_retry >= threshold`) → **block delivery**, trigger one quality-critic recheck via the existing retry path
- If Jev passes → **auto-forward** (do not wait for further human input)
- **Always log** the three Jev scores (`relevance`, `is_complete`, `needs_retry`) at INFO level regardless of outcome

Since Jev never hallucinates, a `needs_retry` score >= threshold is a reliable signal.

### Expected Outcomes
- When `needs_retry >= retry_threshold`: `payload["metadata"]["jev_needs_retry"] = True` is set, and the orchestrator's pipeline dispatch loop triggers one quality-critic recheck before marking final status
- When `needs_retry < retry_threshold`: output is auto-forwarded with no extra gate
- All three scores always appear in structured log output at INFO level: `"Jev judge [pipeline]: relevance=X is_complete=Y needs_retry=Z forwarded=True/False"`

### Todo List
- [ ] In `_jev_judge` ([`graph.py:1521-1529`](pipelines/orchestrator/graph.py:1521)): always log scores at INFO (already done at line 1516-1518); additionally set `payload["metadata"]["jev_needs_retry"] = True` when flagged
- [ ] In the pipeline dispatch loop in `_run_pipeline` (find by searching `graph.py` for where `_jev_judge` is called at line 1209): after `_jev_judge` returns, check `payload.get("metadata", {}).get("jev_needs_retry")` — if True and `attempt < max_attempts`, re-enter the quality-critic path instead of returning
- [ ] Add one test in the existing Jev/orchestrator test file: mock `_jev_judge` to set `jev_needs_retry=True`, assert the quality-critic path runs once more before the final response

### Relevant Context
- [`pipelines/orchestrator/graph.py:1209`](pipelines/orchestrator/graph.py:1209) — call site of `_jev_judge`
- [`pipelines/orchestrator/graph.py:1434-1545`](pipelines/orchestrator/graph.py:1434) — full `_jev_judge` implementation
- The quality-critic retry path is the same one triggered by in-pipeline crew failures — reuse it, do not duplicate

### Status
[ ] pending

---

## Sub-Task 5 — Fix Unsafe Scheduler Retry + Idempotency Key

### Intent
[`api/scheduler.py:755-789`](api/scheduler.py:755) (`_execute_with_timeout`) calls
`child_executor.shutdown(wait=False)` on timeout — Python cannot stop a running thread.
If the still-running thread and a new retry attempt both proceed, two provider calls
overlap for the same logical run.

[`backend-node/src/python-client.js:44-48`](backend-node/src/python-client.js:44)
(`createRun`) does not pass an `Idempotency-Key` header, so a gateway timeout + client
retry creates a second run instead of reusing the first.

### Expected Outcomes
- On timeout: `cancel_event` is set **before** the `SchedulerExecutionTimeout` is raised, giving the in-flight orchestrator/provider a cooperative stop signal
- `_execute_with_timeout` waits up to a short grace period for the thread to exit before returning control (so `_schedule_retry` does not requeue while the thread is still alive)
- `createRun` passes `"Idempotency-Key": taskId` so the Python scheduler deduplicates repeated gateway calls

### Todo List
- [ ] In [`api/scheduler.py:776-780`](api/scheduler.py:776): before `raise SchedulerExecutionTimeout(...)`, call `cancel_event.set()` so the in-flight work gets a cooperative stop signal
- [ ] After `future.cancel()` at line 777: replace `child_executor.shutdown(wait=False, cancel_futures=True)` with a short grace-period wait — attempt `future.result(timeout=cancel_grace_period_s)` (default 2s) in the `finally` block, catching `FutureTimeoutError` silently; then `child_executor.shutdown(wait=False)`
- [ ] Add `SUDARSHAN_CANCEL_GRACE_PERIOD_MS` to [`.env.example`](.env.example) with default `2000`
- [ ] In [`backend-node/src/python-client.js:44-48`](backend-node/src/python-client.js:44): add `"Idempotency-Key": taskId` to the headers object in `createRun`

### Relevant Context
- [`api/scheduler.py:755-845`](api/scheduler.py:755) — full `_execute_with_timeout` and `_worker` implementations
- [`backend-node/src/python-client.js:26-50`](backend-node/src/python-client.js:26) — `createRun`; the ingestion path already passes `Idempotency-Key` as a pattern to follow
- [`.env.example:68-71`](.env.example:68) — scheduler env vars; add new one alongside `SUDARSHAN_MAX_ATTEMPTS`

### Status
[ ] pending

---

## Sub-Task 6 — Expose DAG Graph in Public API

### Intent
The DAG engine is fully durable ([`api/dag_scheduler.py:44-81`](api/dag_scheduler.py:44))
but its node/edge graph is never returned through `api/server.py` or
`SudarshanApplication.status()`. The PPT vertical slice keeps part of its run context
in an in-memory dict that is lost on process restart.

### Expected Outcomes
- `GET /runs/{run_id}/graph` returns canonical DAG nodes, edges, node status, output refs, and repair attempts
- `SudarshanApplication.status()` includes a `"dag"` key when the run used a DAG pipeline
- The in-memory `_runs` dict in [`pipelines/ppt/vertical.py:51`](pipelines/ppt/vertical.py:51) is replaced with durable reads from the DAG store on each `status()` call

### Todo List
- [ ] Add `GET /runs/{run_id}/graph` route to [`api/server.py`](api/server.py); delegate to `SudarshanApplication.dag_graph(run_id)`
- [ ] Implement `SudarshanApplication.dag_graph(run_id)` in [`integrations/deepseek_harness/application.py`](integrations/deepseek_harness/application.py) — delegate to `DAGSchedulerBridge.status()` (already returns the full graph at `api/dag_scheduler.py:44-81`)
- [ ] In [`pipelines/ppt/vertical.py`](pipelines/ppt/vertical.py): remove the `_runs` in-memory dict at line 51; replace each `_runs[run_id] = …` write with a DAG store write; replace each `_runs.get(run_id)` read with a DAG store read

### Relevant Context
- [`api/dag_scheduler.py:44-81`](api/dag_scheduler.py:44) — `DAGSchedulerBridge.status()` already returns the full graph
- [`integrations/deepseek_harness/application.py:976-1063`](integrations/deepseek_harness/application.py:976) — `status()` implementation to extend
- [`pipelines/ppt/vertical.py:51,102-113`](pipelines/ppt/vertical.py:51) — in-memory state to replace

### Status
[ ] pending

---

## Implementation Order

| Step | Sub-Task | Risk | Size |
|---|---|---|---|
| 1 | Sub-Task 1 — Silent exception logging | LOW | 2 lines |
| 2 | Sub-Task 2 — Token budget centralisation | LOW | ~15 lines across 4 files |
| 3 | Sub-Task 3 — PPT page budget | MEDIUM | ~30 lines across 4 files |
| 4 | Sub-Task 4 — Jev judge blocks on failure | MEDIUM | ~20 lines + 1 test |
| 5 | Sub-Task 5 — Scheduler cancel + idempotency | MEDIUM | ~15 lines across 2 files |
| 6 | Sub-Task 6 — DAG API | MEDIUM | ~40 lines across 3 files |
