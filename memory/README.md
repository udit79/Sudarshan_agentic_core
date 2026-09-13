# Sudarshan memory unit

The memory unit owns Sudarshan semantics and delegates knowledge processing to
Cognee. The ingestion boundary is `KnowledgeUnit`; an ingestion pipeline can
pass that dataclass or any object/mapping with `unit_id`/`id`, `content`/`text`,
`source`, `metadata`, and `provenance` fields.

## Runtime flow

```text
KnowledgeUnit + AccessContext
        -> MemoryManager.remember()
        -> Cognee /api/v1/remember
        -> Cognee graph + vector indexes

query + AccessContext
        -> scope policy and node sets
        -> Cognee /api/v1/recall (context only)
        -> ranked, stage-bounded ContextBuilder
        -> typed ContextPack + retrieval trace
        -> MemoryInjector
```

Use one dataset for the application and logical node sets for isolation:
`system`, the current user, current case, and current task. Each write is
tagged only with its exact scope; a recall request sends the current scope plus
its ancestors. This preserves inheritance without making a user-level query
retrieve all child cases and tasks. A recall request only sends
the current context's node sets to Cognee; results with explicit conflicting
scope metadata are also rejected defensively.

`ContextBuilder` is the Sudarshan policy layer after Cognee retrieval. It ranks
backend results with query-term overlap, removes exact duplicates, preserves
source/provenance metadata, and applies a hard character/token budget. Stage
profiles provide progressive loading: request understanding receives a small
pack, grounding can receive more detail, and visual/quality stages receive
only the evidence they need. The builder emits a stable retrieval trace and
`MemoryManager.recall_context_pack()` returns the canonical orchestrator
`ContextPack`; Cognee remains responsible for graph/vector retrieval, not run
state or prompt policy.

This follows the useful ideas from Cognee, OpenViking, and agentmemory without
coupling Sudarshan to their storage formats: graph-plus-vector recall, explicit
memory/resource/skill separation, progressive context depth, hybrid ranking,
bounded injection, and inspectable retrieval traces. Task events remain
auditable writes through `MemoryManager`, and unreviewed output is not promoted
to case memory automatically.

Memory also has an explicit lifecycle: `active`, `pending_review`,
`superseded`, `retracted`, or `expired`. Only active records are eligible for
recall. A replacement can explicitly supersede an older record, while
`retract()` hides a record without destroying its audit entry. `forget()` is
scope-checked and retracts by default; irreversible backend purge is opt-in and
requires an adapter that explicitly supports it.

Case history is created as safe lifecycle events whenever `MemoryManager`
creates, supersedes, retracts, forgets, or expires a record. The event contains
the memory ID, scope, actor, case/task IDs, lifecycle, and timestamps—not the
memory content. `MemoryManager.from_env()` persists this append-only history to
`artifacts/.state/memory_events.jsonl` by default; set
`SUDARSHAN_MEMORY_EVENT_LOG` to choose another path or leave it empty to keep
the event projection in memory. Searchable case content and provenance remain
in Cognee, while `manager.case_history(AccessContext(...))` returns the
authenticated case's safe audit history.

## Example

```python
from memory import AccessContext, KnowledgeUnit, MemoryManager, Source, SourceType

manager = MemoryManager.from_env()
context = AccessContext(user_id="u-123", case_id="case-456", task_id="task-789")
unit = KnowledgeUnit(
    unit_id="pdf-42-page-3",
    content="The proposal identifies latency as the primary delivery risk.",
    source=Source("pdf-42", SourceType.PDF, "s3://bucket/proposal.pdf#page=3"),
    provenance={"pipeline": "pdf-extractor", "page": 3},
)

manager.remember(unit, context)
answer_context = manager.recall("What risks were identified?", context, token_budget=1200)
prompt = answer_context.context.text  # pass through MemoryInjector for an agent prompt
```

Cognee Cloud is the product default. Configure `COGNEE_BACKEND=cloud`, the
tenant service URL in `COGNEE_BASE_URL`, `COGNEE_API_KEY`, and
`COGNEE_TENANT_ID`. The adapter sends the key and tenant as `X-Api-Key` and
`X-Tenant-Id`, and rejects local/HTTP endpoints in cloud mode. Put them in a
local `.env` after copying `.env.example`; this package intentionally does not
print secrets. `COGNEE_BACKEND=local` remains an explicit development-only
compatibility mode.
