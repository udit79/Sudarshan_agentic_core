# Internal tools, prompts, and Cognee map audit

**Reviewed:** 2026-09-16  
**Scope:** Sudarshan runtime, DeepSeek Harness MCP boundary, pipeline prompts,
memory boundary, and the requested Cognee graph visualization.  
**Purpose:** source-backed audit and implementation plan. This document does
not change runtime behavior by itself.

## Executive result

The Cognee map can be brought into Sudarshan as a bounded, authenticated graph
projection. It should be an observability and memory-navigation surface, not a
replacement for the durable run DAG, scheduler, trajectory, or
`MemoryManager` policy boundary.

The repository already has the correct foundation:

- `MemoryManager` owns scope, lifecycle, provenance, recall limits, and access
  checks.
- `CogneeHttpAdapter` is the only module that knows Cognee REST payloads.
- `sudarshan_memory` is the configured shared dataset, with User/Case/Task
  NodeSets rather than one dataset per task.
- run progress and child execution already have safe projections that can be
  extended with graph references.

The missing piece is a server-side graph reader and projection. The screenshot
is a Cognee UI visualization, not a data contract that the frontend should call
directly.

## How to bring the Cognee map into Sudarshan

### Phase 1: add a read-only adapter capability

Add a `visualize_graph(...)` operation to `memory/cognee_adapter.py` and its
`MemoryBackend` protocol. Keep the Cognee URL, API key, tenant ID, dataset
resolution, and version-specific path inside this adapter. The current adapter
only implements `remember` and `recall`.

Use a bounded query or seed-node request by default:

- `dataset_name`: the configured `sudarshan_memory` dataset;
- `query` or selected `seed_node_ids`, never an unbounded full graph;
- neighborhood depth normally 1 or 2;
- a small UI limit, such as 250 nodes;
- an explicit timeout and no automatic “full graph” fallback.

Cognee deployments expose version-dependent URL prefixes. The adapter should
use the configured deployment contract and capability-check the endpoint rather
than hardcoding a browser URL. Current official Cognee material documents the
JSON visualization endpoint and bounded parameters such as `max_nodes`, query,
seed nodes, and neighborhood depth:
<https://github.com/topoteretes/cognee/blob/main/cognee/api/v1/users/routers/get_visualize_router.py>.

### Phase 2: project the graph through Sudarshan policy

Add an application-bound route such as `GET /memory/graph` and a corresponding
safe MCP read tool only if the Harness actually needs it. The route should
require `AccessContext` and filter the Cognee response again using the local
memory store and lifecycle state. Cognee’s dataset authorization is not a
substitute for Sudarshan’s User/Case/Task and classification rules.

Return a small DTO, not raw Cognee records:

```text
GraphProjection
  nodes: node_id, redacted label, kind, coarse scope, confidence, status
  edges: source, target, relationship, provenance/evidence reference
  sources: source_id, source_type, authorized display label
  query/focus: bounded request and selected seeds
  truncated: boolean and counts
  generated_at / dataset_revision
```

Do not return raw memory text, prompts, hidden reasoning, provider credentials,
unredacted source content, or direct Cognee URLs to the browser. Preserve
`memory_id`, `source_id`, `run_id`, and `event_seq` only as authorized opaque
references.

### Phase 3: make the screenshot concepts useful in the product

The screenshot’s useful concepts can map to Sudarshan as follows:

| Cognee view | Sudarshan projection |
| --- | --- |
| Sources | authorized evidence/source summaries |
| Business / Players / Connections / Records | node-type filters, not new memory stores |
| Operators | system-owned operator/entity nodes with redacted labels |
| Search / ask | bounded graph focus plus normal scoped recall |
| Live | event-driven refresh from a run/trajectory stream |
| force graph | client visualization of the safe DTO |

Trajectory can add a second overlay: `run_id`, `node_id`, `child_id`,
`attempt_id`, `memory_id`, `artifact_id`, and event sequence. That gives users
both memory topology and execution history. It does not remove the need for the
durable DAG; trajectory is a projection and playback surface, while the DAG is
the scheduling and recovery authority.

### Phase 4: index the repository when Cognee is available

The Cognee codebase skill requires a reachable Cognee server for repository
indexing. The local doctor check on this review found no configured server or
API key, and the indexing helper could not start under the locked-down Windows
environment. Therefore this review did not pretend to have a Cognee code graph;
it used the repository source and tests directly.

When the service is intentionally configured, index this repository into one
narrow dataset and query structural questions with code search. Do not commit
the generated `.enola/` directory. Verify every graph answer against the
source files before treating it as truth. Cognee’s NodeSets are suitable for
scoped retrieval and graph grouping:
<https://docs.cognee.ai/core-concepts/further-concepts/node-sets>.

## Internal MCP tool audit

Reviewed `integrations/deepseek_harness/mcp_server.py`, the application
boundary, manifests, and component tests. The complete server surface contains
22 tools; the `artifact` profile exposes 11.

### What is already good

- All tools use the `sudarshan_*` namespace.
- The MCP server delegates through one application boundary instead of owning a
  second scheduler or direct provider integration.
- The artifact profile removes evidence, memory-maintenance, and operational
  schemas from the normal Harness path.
- Memory credentials, Cognee clients, filesystem paths, and provider keys are
  not exposed as model tools.
- Status, artifact, event, quality, usage, and child-result projections are
  designed to avoid raw prompts and model reasoning.
- Input schemas are covered by `tests/component/test_application_boundary.py`.
- Durable child handoff already has `ChildTaskSpec`, `SkillResult`, budgets,
  capabilities, trust tiers, and typed outcomes.

### Findings, ranked

#### High: the normal profile exposes two ways to start the same work

`run_sudarshan` and `start_sudarshan_run` overlap. One is described as running
an operation and the other as starting an asynchronous operation, but both can
lead to the same application lifecycle. A model can call the wrong one after a
timeout and create duplicate work.

Recommended correction:

1. Make `start_sudarshan_run` the canonical model-facing admission tool.
2. Return a stable admission/idempotency result and require `wait_sudarshan`
   or status polling.
3. Keep `run_sudarshan` only as a compatibility/API operation or hide it from
   the default artifact profile after an agent-selection evaluation.
4. Document that the same request fingerprint must reconcile to the existing
   run, while a retry attempt gets a new `attempt_id`.

#### High: child execution tools expose orchestration internals

`invoke_sudarshan_skill` accepts `parent_run_id` and `parent_node_id` from the
model. Those are lineage fields and should normally be server-derived from an
authorized parent handle. The tool is useful to the orchestrator but is not a
good general-purpose user tool.

Recommended correction: keep local child invocation behind typed child plans;
expose only a capability-based specialist request to a model. Make parent
lineage opaque and server-resolved. Keep `start_sudarshan_skill` for explicit
durable specialist jobs if needed.

#### High: memory write is too broad for a general model surface

`remember_sudarshan_context(user_id, case_id, context)` has no task, source,
memory type, confidence, expiration, classification, provenance, or explicit
consent fields. It can create unbounded case memory and bypass the richer
`MemoryManager.remember` contract.

Recommended correction: keep this internal or replace it with a bounded,
typed case-memory operation that accepts evidence references, confidence,
lifecycle, expiry, and a server-authenticated access context. Recall should
return a bounded typed `ContextPack` with provenance and truncation metadata,
not an arbitrary string.

#### Medium: no explicit output contracts or MCP annotations

The decorators define input schemas, but `mcp_server.py` does not declare
explicit per-tool output models or read-only/destructive/idempotent annotations.
The backend returns a mixture of dictionaries, lists, and strings. This makes
client validation, tool selection, and safe retry policy weaker than the
Pydantic contracts inside Sudarshan.

Recommended correction: add response models for admission, status, wait,
artifact, skill discovery, evidence, memory, and errors. Add annotations or an
equivalent capability table for read-only, mutating, approval-required, and
idempotent operations. Test output validation and annotations, not only input
names.

#### Medium: descriptions do not expose important limits and recovery rules

Descriptions are clear at a high level but several omit the information a
model needs to act safely: wait cursor semantics, timeout bounds, approval
authority, cleanup preview versus apply, evidence `top_k` limits, and which
operations are asynchronous.

Recommended correction: make descriptions short but operationally explicit.
For example, say that `wait_sudarshan` is bounded, returns only events after a
cursor, and does not start work; say that `cleanup_sudarshan_lifecycle` is an
operator-only mutation and `dry_run=true` is the safe preview.

#### Medium: four evidence search tools have a shared-shape opportunity

Text, visual, table, and video evidence tools are useful capabilities, but they
repeat the same identity, scope, classification, and ranking concerns. Their
Python signatures do not communicate all bounds to the model, even where the
application clamps values.

Recommended correction: use one typed evidence request with a constrained
`modality` enum if an evaluation shows that consolidation improves selection;
otherwise retain separate names but share a schema and explicit `top_k` /
pagination / time-range limits. Do not consolidate merely to reduce line count.

#### Medium: cleanup and operational tools need a stricter profile

Health, usage, pipeline listing, memory maintenance, and lifecycle cleanup are
operator/developer capabilities. `cleanup_sudarshan_lifecycle` has a mutating
path even though it defaults to dry-run. Keep these out of the artifact agent
profile and require authenticated operator context for apply mode.

#### Low: profile selection is hard-coded by role name

The current allow-list is understandable at 22 tools. As the surface grows,
replace a single full/artifact distinction with capability-based profiles such
as `artifact_author`, `reviewer`, `operator`, and `developer`. Add progressive
discovery only when tool count or schema size makes the current profile
measurably expensive; do not add a registry layer early.

## Prompt and pipeline audit

Reviewed the common prompt policy, request understanding/prompt planning,
memory tools, and task prompts for advisory, executive summary, infographic,
LinkedIn, and PPT.

### What is already good

- `NTRO_AGENT_GUARDRAILS` centralizes the important policy boundary.
- Request understanding, prompt planning, pipeline execution, review, and
  quality are distinct phases.
- Pipeline outputs are typed with Pydantic contracts.
- Memory is scoped and provenance-aware through `MemoryManager`.
- Quality stages and repair paths exist instead of returning every first draft.
- Prompts prohibit invented facts, hidden reasoning, credentials, and external
  side effects.

### Findings, ranked

#### High: hard artifact constraints still depend too much on prompts

Page count, custom colors, layers, diagram return, and similar requirements
cannot be guaranteed by text instructions. The PPT and infographic prompts
describe constraints, but the authoritative enforcement must happen in schema,
normalization, renderer, and post-render validation.

The required flow is:

```text
request constraint
  -> typed plan/IR
  -> deterministic renderer
  -> post-render validator
  -> repair or blocked delivery
```

For PPT, make page budget, stable `slide_id`, theme/style tokens, layer
metadata, and untouched-slide hashes part of the contract. For infographic and
AntV, validate node/edge return, palette tokens, layer structure, and renderer
success before marking the artifact complete. A model critic can explain an
issue; it must not be the only release authority.

#### Medium: task prompts duplicate generic guardrails

The five task modules repeat facts/provenance/no-invention/internal-workflow
rules that already exist in `pipelines/common/prompt_policy.py`. Duplication
increases token cost and allows wording to drift.

Recommended correction: keep common policy in one versioned builder and pass a
small task-specific policy block. Preserve domain-specific instructions in the
task module; remove repeated generic prose after prompt regression tests exist.

#### Medium: injected memory and plans are not consistently delimited

`PromptCrafterAgent` labels memory with `<sudarshan_memory_context>`, but many
CrewAI task strings interpolate `query`, `memory_context`, or `prompt_plan`
directly. Treat all user-derived and retrieved material as data, not
instructions, with common delimiters such as `<user_request>`,
`<permitted_memory>`, and `<validated_prompt_plan>`.

#### Medium: prompts encourage redundant recall

Tasks repeatedly tell agents to call `recall_sudarshan_memory` even when the
orchestrator has already produced bounded `memory_context`. This can create
extra latency, token usage, and inconsistent context.

Recommended correction: use injected context by default; permit one bounded
recall only to close a named evidence gap. Record that recall in telemetry.

#### Medium: context and retry feedback need receipts

The prompt plan allows up to 50,000 characters of memory and 60,000 characters
of prompt text. The memory tool has a smaller token budget, but the plan does
not expose a universal truncation receipt, prompt version/hash, or bounded
retry-feedback contract.

Recommended correction: persist `prompt_version`, `prompt_hash`, context-pack
ID, truncation flag, and quality issue IDs in the run/usage receipt. Bound
quality feedback and retry it by issue ID rather than replaying an entire
rejected draft.

#### Low: request-understanding is currently deterministic and memory-blind

`RequestUnderstandingAgent` is a deterministic parser and explicitly discards
the supplied memory context. That is acceptable as a policy boundary. If it is
merged into DeepSeek, preserve it as a typed, persisted phase with validated
output, not as free-form model text. Routing and authorization must still be
server-owned.

## Relationship to timeout and duplicate-run problems

The tool and prompt findings explain why a timeout can look like repeated
execution, but they are not themselves the complete fix. Admission needs:

- request fingerprint over normalized user request, case, operation,
  revision scope, and requested pipelines;
- idempotency key supplied or derived at the boundary;
- one durable run record per logical request;
- separate `attempt_id` for each worker execution;
- lease ownership and heartbeat;
- reconciliation when a worker or Harness call times out;
- late-result protection so an old attempt cannot overwrite a newer terminal
  result;
- event fields that expose run, node, attempt, cache, retry, and fallback state.

The model should receive a stable run handle and resume/wait instructions, not
be asked to infer whether a timeout means “start again.”

## Evaluation plan before changing the surface

Add focused evaluations rather than relying only on unit tests:

1. **Tool selection:** create, revise one slide, resume approval, search text,
   inspect artifact, and cancel. Verify canonical tool choice and no duplicate
   starts.
2. **Timeout/retry:** delay the worker, repeat the same admission request,
   deliver a late result, and verify one logical run with multiple attempts.
3. **Prompt injection:** put instruction-like text in user requests, memory,
   and evidence. Verify it remains data and cannot change tool authority.
4. **Artifact constraints:** ask for exactly two slides, custom colors/layers,
   a returned diagram, and a one-slide revision. Verify deterministic validators,
   unchanged-slide hashes, and blocked delivery on failure.
5. **Parallel visibility:** run independent child lanes and verify each lane’s
   status, attempt, quality, usage, artifact, and dependency state are visible.
6. **Memory scope:** query User, Case, and Task records from different access
   contexts and verify unauthorized graph nodes and evidence are removed.

Existing tests cover many contracts and input schemas, but they do not yet
measure real model tool selection, output-schema adherence, or prompt-token
drift. Do not remove tools or merge prompts until these evaluations have a
baseline.

## Source map

- MCP server: `integrations/deepseek_harness/mcp_server.py`
- Harness boundary: `integrations/deepseek_harness/application.py`
- Cognee adapter: `memory/cognee_adapter.py`
- Memory policy: `memory/memory_manager.py`, `memory/scope_policy.py`,
  `memory/context_builder.py`
- Prompt policy: `pipelines/common/prompt_policy.py`
- Request understanding: `pipelines/orchestrator/understanding.py`
- Typed handoff/runtime: `pipelines/orchestrator/contracts.py`,
  `pipelines/orchestrator/skill_runtime.py`,
  `pipelines/orchestrator/cross_skill.py`
- Task prompts: `pipelines/*/tasks.py`
- Existing boundary tests: `tests/component/test_application_boundary.py`,
  `tests/component/test_harness_profile.py`,
  `tests/component/test_harness_benchmark.py`

## External Cognee references

- [Knowledge graph / Mindmap UI](https://docs.cognee.ai/cognee-cloud/ui/knowledge-graph)
- [Search and recall](https://docs.cognee.ai/cognee-cloud/functionality/search-and-recall)
- [NodeSets](https://docs.cognee.ai/core-concepts/further-concepts/node-sets)
- [Visualization router and JSON contract](https://github.com/topoteretes/cognee/blob/main/cognee/api/v1/users/routers/get_visualize_router.py)
