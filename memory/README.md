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
        -> bounded ContextBuilder
        -> MemoryInjector
```

Use one dataset for the application and logical node sets for isolation:
`system`, the current user, current case, and current task. Each write is
tagged only with its exact scope; a recall request sends the current scope plus
its ancestors. This preserves inheritance without making a user-level query
retrieve all child cases and tasks. A recall request only sends
the current context's node sets to Cognee; results with explicit conflicting
scope metadata are also rejected defensively.

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

`COGNEE_API_KEY` and `COGNEE_TENANT_ID` are read from the environment. For
Cognee Cloud, both are required: the adapter sends them as `X-Api-Key` and
`X-Tenant-Id`. Put them in a local `.env` after copying `.env.example`; this
package intentionally does not print secrets.
