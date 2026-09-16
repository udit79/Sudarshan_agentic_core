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

## What graph exists, and who owns it

Sudarshan currently has three related but different graph-like structures:

| Structure | How it is made | What it means | Authority |
| --- | --- | --- | --- |
| Cognee knowledge graph/vector index | `MemoryManager.remember()` sends a document and metadata to `/api/v1/remember`; Cognee extracts semantic entities/relationships and builds its indexes | Semantic relationships found in remembered content | Cognee, eventually consistent |
| Sudarshan execution DAG | The orchestrator admits typed nodes and dependency edges into SQLite/Redis | Which pipeline/child runs, in what order, with what status and attempts | Sudarshan scheduler/DAG |
| Sudarshan memory policy/store | `MemoryManager` creates stable memory IDs, scope, type, lifecycle, confidence, expiry, and provenance records | Whether a memory is eligible, authorized, auditable, or bounded for recall | Sudarshan policy layer |

The Cognee graph shown in a graph-map UI is therefore not the Sudarshan DAG.
Cognee discovers semantic connections from content; Sudarshan explicitly
creates execution dependencies. A `MemoryType.RELATIONSHIP` value is a
Sudarshan classification, not a guarantee that a particular Cognee edge was
created. The current adapter does not maintain a separate custom entity-edge
database; it sends scoped documents and lets Cognee build its semantic graph.

## How policy changes what Cognee sees

Every write goes through `MemoryManager`, which:

1. assigns a stable ID from the unit, exact scope, and memory type;
2. attaches User/Case/Task scope, classification/provenance metadata,
   confidence, lifecycle, expiry, source reference, and a context URI;
3. sends the document only to the exact node set, such as
   `sudarshan:scope:case:<case-id>`;
4. keeps parent-scope inheritance for read time instead of tagging a child
   write into every parent node set.

For a task-scoped request, the recall boundary sends only system, current-user,
current-case, and current-task node sets. A user-only request does not read all
of that user's child cases. Returned items are checked again for explicit
scope conflicts, known local lifecycle state, and `ACTIVE` status before they
reach `ContextBuilder`.

Cognee still performs the semantic graph/vector work. `ContextBuilder` is the
Sudarshan control point after retrieval: it ranks results, removes duplicates,
selects L0/L1/L2 context, detects instruction-like source content, preserves
provenance, and enforces the token/character budget. Agents receive a bounded
`ContextPack` or memory tool result, never a Cognee client or unrestricted
graph.

## Important difference from viewing Cognee directly

The application policy is enforced at the Sudarshan boundary, not by changing
Cognee's internal graph algorithm. A direct Cognee graph-map query may show
semantic nodes that the application would not return for a particular user,
case, task, lifecycle, or classification. `retract()` also hides a memory from
Sudarshan recall while retaining its local audit record; physical backend
deletion requires explicit, supported `purge_backend=True` and is not the
default. Therefore the raw Cognee map is an operator/development view, not a
safe user-facing case view.

Ingestion and unreviewed output are additionally prevented from becoming
durable `FACT` memory by Sudarshan's write policy. They may be stored as
bounded `SUMMARY`, `EVENT`, or pending-review records, but that distinction is
metadata enforced by Sudarshan and should be respected when interpreting a
Cognee graph node.

## Where User, Case, and Task live

These are application identities, not separate Cognee databases:

| Identity | Meaning | Code boundary | Memory effect |
| --- | --- | --- | --- |
| `user_id` | Authenticated operator/owner | API `X-Operator-Id`, `AdvisoryRequest`, `AccessContext` | Owns user-scoped preferences and may access its authorized cases |
| `case_id` | Durable investigation/workspace boundary | request validation, case-scoped evidence/artifacts, `AccessContext` | Separates one case from another for memory and artifacts |
| `task_id` | One user-visible transformation/audit request | request contract, audit log, run context | Holds task events and task-specific working memory |
| `run_id` | One execution of a task | scheduler/checkpointer/DAG | Correlates execution, attempts, events, artifacts, and telemetry; it is not a memory scope |

The hierarchy is enforced by `AccessContext`: a case requires a user, and a
task requires a case. A task-scoped write is tagged only with
`sudarshan:scope:task:<task-id>`; a case-scoped write is tagged only with
`sudarshan:scope:case:<case-id>`. On recall, Sudarshan explicitly supplies the
system, current-user, current-case, and current-task node sets to Cognee. This
gives parent-scope inheritance at read time without making a user write into
every child case or task.

The same scope tuple is carried into evidence retrieval, artifact authorization,
ingestion cache fingerprints, audit records, ContextPack scope, and A2A
handoffs. The gateway/operator identity is authoritative; client-supplied
scope values are validated against it. This is logical tenant isolation and
must still be backed by approved identity, storage, encryption, and network
controls in production.

## What we adopted from OpenViking and agentmemory

The references influenced contracts and policy, not runtime ownership:

| Reference idea | Sudarshan implementation |
| --- | --- |
| OpenViking L0/L1/L2 progressive context | `ContextBuilder.STAGE_CONTEXT_LEVELS`, `context_layers`, bounded `ContextPack`, and `sudarshan://context/.../L0|L1|L2` references |
| OpenViking retrieval lineage/trajectory | `retrieval_trace_id`, `ContextBuildTrace`, safe memory lifecycle events, and the run trajectory projection |
| OpenViking recall → execute → feedback → consolidate | bounded recall before execution, task/event writes during execution, and explicit post-run lesson/memory projection; automatic experience extraction is not imported |
| agentmemory stable identity/deduplication | stable memory IDs, request/evidence fingerprints, local idempotent memory store, and duplicate removal in `ContextBuilder` |
| agentmemory lifecycle/forgetting | `ACTIVE`, `PENDING_REVIEW`, `SUPERSEDED`, `RETRACTED`, `EXPIRED`, `retract()`, `forget()`, and append-only safe lifecycle history |
| agentmemory lessons/profiles | explicit `remember_lesson()` and `remember_profile()` APIs with user scope |
| agentmemory operator visibility | safe counts, provenance, lifecycle IDs, and trajectory/observability events without raw prompts or credentials |

We deliberately did not import OpenViking as a second memory store, its
AGPL-licensed filesystem/runtime, or agentmemory's 54-tool coding-agent
surface. Cognee remains the semantic backend; the evidence index remains the
exact-source boundary; and Sudarshan remains the policy and orchestration
authority.
