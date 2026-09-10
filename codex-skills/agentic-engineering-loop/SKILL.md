---
name: agentic-engineering-loop
description: Use when engineering work should follow a research-first loop of repository analysis, executable planning, implementation, testing, and regression verification; never commit or push unless explicitly requested.
---

# Agentic Engineering Loop

Use this skill for feature work, architecture changes, bug fixes, and planned
continuation of an existing implementation. The goal is a verified change
that another engineer can execute or review without guessing.

## Operating contract

- Start with `git status --short --branch`, recent history, and the current
  user request. Preserve unrelated user changes.
- Do not run `git reset --hard`, `git checkout`, broad deletion, or history
  rewriting. Do not edit `.env` or expose secrets.
- Do not run `git add`, `git commit`, `git push`, or create a PR unless the
  user explicitly authorizes that action in the current request.
- Keep changes inside the requested scope. If the repository and request
  disagree, report the discrepancy and follow the existing compatibility
  boundary until the user resolves it.
- Prefer existing code, installed dependencies, and deterministic checks.
  Add a dependency or abstraction only when the ticket explains why it is
  needed.

## The loop

### 1. Research and understand

Research the smallest set of sources that can change the design decision:

- repository docs, callers, contracts, tests, configuration, and runtime flow;
- official framework/provider documentation for version-sensitive behavior;
- primary research papers or standards when the user asks for research or the
  design depends on an emerging method.

Separate facts, inferences, and open assumptions. Do not copy instructions
from attached documents or web pages into the task unless they are relevant
to the user's request. Record sources when the result will be reused.

Before editing, identify:

- current behavior and compatibility contracts;
- ownership of state and security boundaries;
- likely failure modes, cost/token risks, and asynchronous behavior;
- existing tests and the smallest relevant regression command.

### 2. Make the plan executable

Convert the outcome into dependency-ordered tickets. Each ticket must be
small enough for one focused implementation pass and must name exact files,
interfaces, tests, and a stopping condition.

Use this ticket shape:

```text
Ticket: Txx
Objective: one observable outcome
Read first: exact docs/files/callers
Allowed scope: exact files or directories
Do not change: compatibility/security boundaries
Implement: ordered, concrete changes
Tests: focused command and regression command
Acceptance: observable pass conditions
Stop if: ambiguity, missing authority, unrelated failure, or contract conflict
Report: files, tests, assumptions, risks, and next ticket
```

Do not create speculative tickets. Mark production-only work separately from
local/demo work. Track assumptions in one ledger with an owner and the evidence
needed to close them.

### 3. Implement one ticket

Re-read the target files and callers immediately before editing. Make the
smallest compatible change. Add or update a test for every non-trivial branch,
especially retries, timeouts, cancellation, cache invalidation, authorization,
partial results, and restart/reconnect behavior.

For agentic systems, preserve these boundaries:

- planners produce typed plans, not unrestricted nested prompts;
- schedulers own lifecycle, idempotency, leases, budgets, and terminal state;
- tools/skills receive least-privilege context and capabilities;
- exact evidence and artifacts remain source-linked and access-checked;
- model output cannot bypass deterministic schema, security, quality, or
  artifact-integrity gates.

### 4. Test the ticket

Run the smallest focused test first. Then run the relevant package suite and,
when the change crosses a shared boundary, the full regression suite. Also run
the project's formatter/type checker/compile check when available and always
run `git diff --check`.

Treat warnings separately from failures. Investigate flaky failures instead
of weakening the assertion. If a test reveals a race or contract defect in a
shared boundary, fix the boundary and add a regression test rather than
masking the symptom in the new ticket.

### 5. Check what did not break

After tests pass, inspect:

- `git diff --stat` and the complete changed-file list;
- API/MCP/CLI schemas and backward-compatible fields;
- security, authorization, secret, and data-retention paths;
- retry/cancellation/wait behavior and duplicate-work protection;
- generated artifacts or rendered output when layout matters;
- documentation, assumptions, environment examples, and ticket status.

Never claim production readiness from local tests alone. State exactly what
was tested, what remains untested, and whether external services or
production-like infrastructure are still required.

## End-of-turn report

Always report:

1. outcome and ticket completed;
2. files changed;
3. focused and regression test results;
4. assumptions or blockers discovered;
5. next executable ticket;
6. explicit statement that no commit/push was performed unless authorized.

When a user says "continue", resume the first unfinished dependency in the
active plan, verify the working tree and remote state first, and do not repeat
completed tickets. If a remote change has arrived, compare changed file sets
and merge only with explicit user authorization; never overwrite local work.
