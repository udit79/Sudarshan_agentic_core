# Sudarshan 2.0: Full Agentic Evolution and Execution Plan

Status: proposed implementation baseline

This document defines the target architecture, research-backed design decisions, and staged execution plan for evolving Sudarshan into a durable, agentic artifact-production platform built on the native DeepSeek Harness and exposed through MCP.

The attached OpenAI-style diagram is treated as a design reference, not as an instruction. Its useful principle is the transformation of scattered context into a reusable workflow, a first draft, and a review/improvement loop. Sudarshan should implement that principle with typed intermediate representations, evidence provenance, deterministic renderers, validators, durable execution, and governed memory.

## Executive decision

The direction is good for scale, but the architecture should be strengthened in four ways:

1. PPT generation must use a typed presentation intermediate representation (IR), including a first-class flowchart IR. The model plans the visual structure; deterministic layout and rendering engines produce editable slides; visual validators inspect rendered output.
2. The native DeepSeek Harness should be differentiated by a Sudarshan execution experience: native skill loading, task cards, Execution Monitor, evidence drawer, artifact workspace, policy-aware approvals, and model/provider routing. The Harness runtime is a strong foundation, but its quality must be demonstrated with evaluations rather than assumed.
3. Cognee should be used as a governed graph-memory substrate for evidence, case knowledge, reusable procedures, and validated execution experience. It should not become an unrestricted transcript store or the source of truth for run state, permissions, or artifacts.
4. The backend should own durable runs, DAG execution, queues, retries, leases, artifact storage, and quality gates. The Harness agent should select a skill and submit a mission; it should not become the production scheduler.

The target boundary is:

```text
DeepSeek Harness = native host and operator experience
  sessions, model adapters, skill catalog, MCP client, approvals, UI, job interaction

Sudarshan = application control plane and execution platform
  intent, policy, evidence, memory, skill runtime, DAGs, workers, renderers, validators,
  artifacts, audit, scale-out, and MCP server

Cognee = governed knowledge and experience memory
  graph, vector/text retrieval, session memory, improvement, provenance-aware recall
```

## 1. Research conclusions that drive the design

### 1.1 Effective artifact agents plan structure before pixels

Recent presentation-generation research converges on a two-stage process: understand the source and create an explicit outline, then plan each slide's content and layout before rendering. SlideGen describes a modular visual-in-the-loop system with outliner, mapping, arrangement, note synthesis, and iterative refinement agents.[^1] PPTAgent uses reference-presentation analysis, outline drafting, and edit-based generation, and evaluates content, design, and coherence separately.[^2] A visual self-verification study represents a slide as elements with both content and layout, then generates and refines that structured representation before conversion into PowerPoint.[^3]

The practical conclusion for Sudarshan is that a slide must not be represented only as a title plus bullets. It needs an editable scene graph:

```text
PresentationSpec
  ├── narrative arc and slide order
  ├── design system and theme
  ├── SlideSpec[]
  │     ├── intent and one-message statement
  │     ├── evidence/citation bindings
  │     ├── layout type
  │     ├── element[]
  │     │     ├── text, shape, image, table, chart, flowchart
  │     │     ├── bounding/anchor constraints
  │     │     ├── style token references
  │     │     └── accessibility/legibility constraints
  │     └── speaker notes
  └── quality and release policy
```

### 1.2 Reliable multi-agent systems need contracts and verification

Recent work on automatically constructed multi-agent systems emphasizes directed acyclic graphs, explicit input/output contracts, verification criteria, execution-time gates, and targeted recovery rather than unconstrained agent conversation.[^4] This supports a coordinator plus bounded specialists:

```text
coordinator plans and assigns
specialists produce typed intermediate results
validators gate each important boundary
repair targets the failed component
```

It does not support letting the central model freely spawn agents, call all tools in arbitrary order, and decide when an artifact is acceptable.

### 1.3 Memory needs lifecycle, evaluation, and forgetting

The current graph-memory literature distinguishes short-term and long-term memory, factual knowledge and experience, structural and non-structural representations, and a lifecycle of extraction, storage, retrieval, and evolution.[^5] Newer benchmarks report that memory systems often reuse obsolete facts or fail to reconcile updates, so “we store everything in memory” is not a quality strategy.[^6]

Cognee's current documentation describes a useful lifecycle: `remember`, `recall`, `improve`, and `forget`, with session memory as a fast path and permanent graph memory as a slower enriched path.[^7] Sudarshan should adopt the lifecycle while retaining its own scope, provenance, policy, and release controls.

### 1.4 Harness quality is a product property, not a repository property

The DeepSeek Harness repository provides a strong technical foundation: replaceable model/tool/session/agent-loop plugins, layered skills, optional subagent providers, background jobs, and UI extension points. The local documentation confirms that skills are discovered through compact summaries and loaded on demand, while child agents have capability filtering, depth control, ownership, cancellation, and durable child sessions.[^8]

That makes the Harness suitable as Sudarshan's native host. It does not prove that Sudarshan's complete product is high quality. Quality must be established through end-to-end evaluations for groundedness, artifact quality, cost, latency, recovery, security, and operator usability.

## 2. Target architecture

```text
┌────────────────────────────────────────────────────────────────────┐
│ DeepSeek Harness / compatible external Harness                     │
│                                                                    │
│ Host agent → skill summaries → selected skill → MCP client         │
│ Native UI: chat, Execution Monitor, artifacts, evidence, approvals │
└───────────────────────────────┬────────────────────────────────────┘
                                │ MCP
                                ▼
┌────────────────────────────────────────────────────────────────────┐
│ Sudarshan MCP and application boundary                             │
│                                                                    │
│ discover skills · start run · observe · resume · cancel            │
│ resources: manifest · evidence ledger · quality report · artifact   │
└───────────────────────────────┬────────────────────────────────────┘
                                │
                                ▼
┌────────────────────────────────────────────────────────────────────┐
│ Sudarshan control plane                                            │
│                                                                    │
│ intent → policy → evidence → skill runtime → typed DAG → scheduler │
│                                                                    │
│ durable run store · event store · queue · leases · idempotency     │
└───────────────┬───────────────────┬───────────────────┬────────────┘
                │                   │                   │
                ▼                   ▼                   ▼
        specialist agents     deterministic workers   quality gates
        CrewAI where useful    renderers/sandboxes     promote/revise/reject
                │                   │                   │
                └───────────────────┴───────────────────┘
                                    ▼
             artifact store + evidence ledger + audit manifest
                                    │
                                    ▼
                            Cognee governed memory
```

### Ownership rules

| Concern | Owner | Reason |
|---|---|---|
| User intent and clarification | Harness agent | Best interactive surface for conversation |
| Skill selection | Harness agent plus Sudarshan router | Model proposes; server validates |
| Tool permissions | Sudarshan policy | Must not rely on model obedience |
| Durable state | Sudarshan database | Survives disconnects and restarts |
| Parallelism and retries | Sudarshan scheduler | Models are not production schedulers |
| Specialist collaboration | Selected skill and bounded workers | Avoid three independent orchestrators |
| Rendering | Deterministic renderer worker | Reproducible artifact output |
| Quality decision | Structural, semantic, visual, and policy validators | External checks are stronger than self-approval |
| Artifact release | Sudarshan policy and approval gate | Classification and distribution control |
| Long-term memory | Cognee through MemoryManager | Graph retrieval and evolution |
| Run truth | Sudarshan run store | Cognee is not a job database |

## 3. PPT evolution: from text slides to visual programs

### 3.1 Current gap in the repository

The current PPT path is a useful prototype but is not yet a presentation-quality rendering system:

- `PresentationOutput` represents slides mainly as titles, bullets, notes, and a small layout enum.
- `renderer.py` uses `python-pptx` with title/content placeholders and basic font sizes.
- The quality critic checks content and structure but does not inspect rendered slide images.
- There is no first-class flowchart schema, layout engine, or visual repair loop.

This explains why a deck can be factually correct while appearing white, empty, repetitive, or unsuitable for a presentation.

### 3.2 The flowchart requirement

The correct approach is not “ask the slide agent to draw a flowchart.” Use a dedicated `flowchart` functional skill inside the presentation skill.

```text
presentation skill
  ├── narrative planner
  ├── slide archetype selector
  ├── flowchart skill (only when graph structure is useful)
  ├── chart/table skill
  ├── theme/layout engine
  ├── PPTX renderer
  └── visual and semantic QA
```

The central presentation planner decides whether a slide benefits from a flowchart. It should select the flowchart skill when the content contains a process, dependency graph, decision tree, causal chain, system architecture, or timeline. It should not use a flowchart merely to decorate a slide.

### 3.3 Flowchart skill contract

```yaml
id: visual.flowchart
version: 1.0.0
trigger_when:
  - process or stage sequence
  - dependency or system architecture
  - decision tree or branching logic
  - causal chain or lifecycle
inputs:
  - purpose
  - nodes
  - edges
  - groups
  - audience
  - slide_bounds
  - theme
outputs:
  - flowchart_ir
  - layout_metrics
  - editable_shape_manifest
  - svg_preview
  - accessibility_summary
validators:
  - graph_integrity
  - no_unconnected_required_nodes
  - no_edge_crossing_above_threshold
  - no_text_overflow
  - readable_at_projector_scale
  - evidence_binding
max_layout_attempts: 3
requires_human_release: false
```

### 3.4 Flowchart intermediate representation

The flowchart agent should produce structured data, not SVG or PowerPoint XML directly:

```json
{
  "id": "case-processing-flow",
  "direction": "left-to-right",
  "nodes": [
    {
      "id": "ingest",
      "label": "Ingest source material",
      "kind": "process",
      "group": "input",
      "evidence_ids": ["claim-12"]
    },
    {
      "id": "review",
      "label": "Evidence review",
      "kind": "review",
      "group": "analysis",
      "evidence_ids": ["claim-17"]
    }
  ],
  "edges": [
    {"from": "ingest", "to": "review", "label": "normalized evidence"}
  ],
  "layout_hints": {
    "max_nodes_per_row": 4,
    "prefer_orthogonal_edges": true,
    "emphasize": ["review"]
  },
  "style_tokens": {
    "process": "theme.process",
    "review": "theme.review"
  }
}
```

The IR allows the same flowchart to render as:

- editable PowerPoint shapes and connectors;
- SVG for fast preview;
- PNG for visual model inspection;
- a web/MCP App view;
- an accessible text description;
- a graph resource for later revision.

### 3.5 Recommended flowchart pipeline

```text
1. Narrative planner identifies slide intent.
2. Planner chooses slide archetype: flowchart, timeline, matrix, chart, or narrative.
3. Flowchart skill extracts nodes, edges, groups, labels, and evidence bindings.
4. Graph validator checks structural completeness and reachability.
5. Layout engine computes positions and edge routes.
6. Renderer emits SVG preview and editable PPTX shapes.
7. Visual inspector renders the slide to an image.
8. Visual critic checks overlap, whitespace, font size, contrast, edge clarity, and hierarchy.
9. Repair agent changes only the flowchart IR/layout constraints that failed.
10. Final validator stores the IR, preview, artifact checksum, and quality report.
```

### 3.6 Layout engine strategy

Use a deterministic layout engine for the first production version. An ELK-style layered layout or Graphviz/Dagre-like engine is appropriate for directed flowcharts; a constraint-based layout is better for swimlanes and matrices. The LLM should select layout hints and semantic grouping, not assign every pixel.

Use a two-renderer strategy:

```text
layout engine → canonical geometry
       ├── SVG renderer → preview and visual inspection
       └── PPTX renderer → editable shapes/connectors
```

The canonical geometry must be stored so that a later revision does not ask the model to redraw the entire slide from scratch.

### 3.7 Presentation quality gates

Every generated deck should pass four independent gates:

| Gate | Examples |
|---|---|
| Schema | valid IR, required fields, no unsupported element types |
| Semantic | one-message-per-slide, correct narrative order, complete agenda |
| Evidence | every material claim has a source or is marked as assessment |
| Visual | no overflow, readable text, balanced composition, contrast, legible connectors |

The visual gate should combine deterministic checks and multimodal inspection. Deterministic checks catch bounding-box overlap, clipped text, missing fonts, off-canvas elements, and connector endpoints. A vision model or visual critic catches hierarchy, density, repetition, and whether the slide communicates its intended message.

### 3.8 PPT implementation sequence

1. Expand `SlideContent.layout` into a discriminated union of slide archetypes.
2. Add `FlowchartSpec`, `ChartSpec`, `TimelineSpec`, `MatrixSpec`, and `ImageSpec` schemas.
3. Create a theme registry with fonts, colors, spacing, corner radii, line weights, and classification banners.
4. Build canonical geometry and SVG renderers.
5. Add editable PPTX shape rendering for flowcharts.
6. Render every deck to slide PNGs or PDF pages in a worker.
7. Add structural and visual validators.
8. Add targeted repair based on validator issue IDs.
9. Store the presentation IR and quality report as run artifacts.
10. Add a benchmark set of ten representative decks, including architecture, process, timeline, comparison, and evidence-heavy briefings.

## 4. Native DeepSeek Harness: quality and differentiation

### 4.1 Is the native Harness high quality?

It appears to be a strong foundation for Sudarshan because it already provides the architectural seams we need:

- plugin-composable model, tool, session, and agent-loop components;
- layered, lazy skill discovery;
- optional subagent providers with depth, capability, ownership, and cancellation controls;
- background jobs with status, output, cancellation, and bounded waits;
- native UI extension points;
- a working MCP client integration path.

However, “good quality” must be treated as an open engineering question until Sudarshan runs a benchmark. The Harness should be judged on:

- crash/restart recovery;
- cancellation correctness;
- duplicate-run prevention;
- tool-permission enforcement;
- skill catalog latency and token overhead;
- event ordering and reconnect behavior;
- UI accessibility and operator comprehension;
- model/provider failover;
- artifact preview reliability;
- security and supply-chain review of plugins.

The product should say “built on a plugin-composable DeepSeek Harness” until these measurements support stronger claims.

### 4.2 What makes the native Harness special?

The native version should not compete on generic chat. It should be the best operating environment for Sudarshan production work:

1. **Native skill experience:** compact skill catalog, on-demand skill bodies, skill version visibility, policy-aware invocation, and skill health indicators.
2. **Execution Monitor:** parent/child DAG, parallel lanes, stage progress, retries, waiting reasons, and safe logs.
3. **Artifact workspace:** PPTX/PDF/SVG/video previews, version comparison, quality report, evidence ledger, and download/export.
4. **Evidence drawer:** source excerpts, claim IDs, confidence, uncertainty, and distribution restrictions.
5. **Native approvals:** clarification, release, classification, and revision actions embedded in the run experience.
6. **Model routing:** cheap model for classification and extraction, stronger model for narrative or difficult repair, local model for privacy-sensitive work, and deterministic code for rendering.
7. **Run-aware memory:** the Harness displays memory scope and provenance without exposing raw private memory.
8. **NTRO policy:** classification, distribution, audit, and approval rules become first-class UI and backend concepts.
9. **Offline/controlled deployment:** local workers, private model endpoints, and controlled storage for sensitive environments.
10. **MCP portability:** the same Sudarshan server can be used by another Harness, while the native Harness provides the richest operator experience.

The defensible statement is:

> Sudarshan is a policy-controlled agentic production platform built on a native Harness. Its advantage is not merely skill support; it is the combination of durable multi-agent execution, evidence-grounded artifacts, visual quality gates, memory evolution, and an operator-grade execution interface.

### 4.3 Native Harness implementation boundary

Keep DeepSeek-specific code in a thin native integration layer:

```text
integrations/deepseek_harness/
  ├── MCP client composition
  ├── skill catalog bridge
  ├── run/task UI plugin
  ├── approval and notification bridge
  └── artifact preview adapter

Sudarshan core/
  ├── skill runtime
  ├── run coordinator
  ├── queue and worker contracts
  ├── policy and evidence
  ├── memory manager
  └── artifacts and validators
```

Do not fork the Harness core for branding or application logic. Prefer composition, plugin registration, and a small patch layer. This protects the ability to use another MCP host later.

## 5. Cognee at maximum useful power

### 5.1 What Cognee should and should not do

Cognee should provide connected, searchable memory across documents, entities, cases, artifacts, procedures, and validated experience. Its current model supports permanent graph memory, fast session memory, improvement passes, forgetting, graph/vector retrieval, and MCP access.[^7][^9]

Cognee should not own:

- authoritative run status;
- queue leases or retries;
- access-control decisions;
- classification policy;
- binary artifact storage;
- the only copy of source documents;
- unreviewed chain-of-thought or unrestricted transcripts.

Sudarshan's `MemoryManager` should remain the only gateway. The existing adapter and scoped node-set design are good foundations because they keep Cognee-specific payloads behind one module and preserve scope/provenance in Sudarshan.

### 5.2 Four memory planes

Use separate datasets or strongly separated node sets for four planes:

| Plane | Contents | Lifetime | Write policy |
|---|---|---|---|
| Working memory | current run plan, active evidence, unresolved questions | run/session | automatic, expires |
| Case memory | approved facts, entities, relationships, prior artifacts | case | governed write |
| System memory | reusable procedures, successful repairs, renderer patterns, skill knowledge | system | offline promotion |
| User memory | preferences, templates, language, recurring audience needs | user | explicit consent and scoped write |

Do not mix system, user, case, and task memories in one undifferentiated dataset. Cognee's dataset and node-set controls should reflect the security model.

### 5.3 Memory lifecycle for a run

```text
input ingestion
  → source normalization
  → working/session memory
  → targeted recall for each stage
  → validated artifact and feedback
  → candidate experience record
  → offline improve/evaluation
  → promotion to system or case memory
  → expiry, correction, or forget
```

At run start, write a compact run capsule to session memory:

```text
run_id, case_id, skill_id, skill_version, objective,
constraints, audience, classification, requested outputs,
known sources, open questions, budget, created_at
```

At each major stage, retrieve a bounded context pack rather than the full conversation. At completion, write only validated summaries, claim/evidence relations, artifact metadata, quality findings, and reusable repair patterns.

### 5.4 Typed knowledge units

Use explicit types in the memory metadata and graph model:

```text
SourceDocument
  ├── contains → Claim
  ├── contains → Entity
  └── supports → Assessment

Claim
  ├── about → Entity
  ├── supported_by → SourceExcerpt
  ├── contradicted_by → Claim
  └── valid_during → TimeRange

Artifact
  ├── derived_from → Claim / SourceDocument
  ├── generated_by → SkillVersion
  ├── validated_by → QualityReport
  └── supersedes → Artifact

Experience
  ├── occurs_in → SkillVersion
  ├── triggered_by → FailureSignature
  ├── repaired_by → RepairPattern
  └── validated_by → EvalResult
```

Each memory item should carry:

```text
memory_id, scope, source_reference, provenance,
created_at, observed_at, valid_from, valid_until,
confidence, status, supersedes, permitted_distribution,
content_checksum, writer_identity, review_state
```

### 5.5 Retrieval policy

Use a retrieval router rather than one universal query:

```text
simple exact fact       → CHUNKS or metadata filter
known entity relation   → graph traversal
case synthesis          → graph + vector context
current run continuity  → session memory
renderer repair pattern → system experience memory
code structure          → code graph search
```

Cognee's current search API exposes multiple modes, including graph completion, RAG completion, chunks, summaries, and code-oriented search, with different latency and cost profiles.[^10] The skill should select the least expensive mode that can answer the current subproblem.

Use these guardrails:

- default `top_k` should be small and stage-specific;
- retrieve only permitted node sets;
- rerank by scope, freshness, confidence, and source authority;
- reject expired or superseded facts;
- include provenance in every context pack;
- store a retrieval trace with query, filters, result IDs, and token estimate;
- never silently merge contradictory claims;
- ask for clarification or route to a reviewer when the conflict matters.

### 5.6 Use `improve` as a governed learning loop

Use Cognee improvement after a run, not on every token:

```text
run feedback and quality report
  → identify repeated failure or successful repair
  → create candidate Experience record
  → improve/enrich system memory
  → evaluate against held-out tasks
  → promote only if metrics improve and security review passes
```

Examples of promotable experience:

- a flowchart layout repair that consistently eliminates edge crossings;
- a theme choice that improves readability for dense architecture slides;
- a retrieval query pattern that finds the correct case evidence;
- a provider fallback that reduces video failure rate;
- a clarification question that prevents a common artifact revision.

Do not automatically promote an agent's arbitrary text or tool trace into a reusable skill. Promotion requires validation, provenance, owner, version, and rollback.

### 5.7 Cognee datasets and deployment

For local development, a local graph store is appropriate. Cognee documents Kuzu as a local file-based option and Neo4j, Neptune, and other providers for production deployments; it also notes that dataset isolation and explicit storage paths matter for multi-user deployments.[^11]

Recommended deployment stages:

```text
development  → local Kuzu, isolated test dataset, synthetic cases
team demo     → shared Cognee API mode, per-team/case datasets, backups
NTRO pilot    → production graph store, explicit storage roots, access control,
                encrypted backups, retention and deletion workflows
```

Fix `SYSTEM_ROOT_DIRECTORY` and `DATA_ROOT_DIRECTORY` explicitly in deployed environments so graph and raw-data paths do not change across virtual environments or restarts.

### 5.8 Cognee MCP versus embedded Cognee

Use embedded Cognee through Sudarshan's `MemoryManager` for core execution. Expose a restricted Cognee MCP surface only for trusted operator/developer workflows. The official Cognee MCP integration exposes memory and dataset operations and supports standalone and API/shared modes.[^12]

Recommended separation:

```text
production skill agent → MemoryManager → Cognee API
operator/developer     → restricted Cognee MCP tools
external Harness       → Sudarshan MCP tools, not raw Cognee tools
```

External Harnesses should not receive unrestricted memory tools because that would bypass Sudarshan's scope, classification, and provenance policy.

### 5.9 Cognee success metrics

Measure Cognee as an engineering component:

- grounded-answer rate with and without memory;
- evidence recall at fixed top-k;
- stale-memory reuse rate;
- contradiction detection rate;
- memory write precision;
- memory deletion/forget correctness;
- retrieval latency and token payload size;
- per-run memory cost;
- improvement pass acceptance rate;
- cross-session task success;
- case isolation violations, target zero.

Use the recent memory-benchmark direction as guidance: test remembering, reasoning, recommending, updates, forgetting, and interdependent multi-session tasks, not only “can the agent retrieve a fact?”[^6]

## 6. Skills, agents, CrewAI, and the Harness

### 6.1 The recommended invocation model

```text
Harness central agent
  → loads high-level skill
  → calls start_sudarshan_run
  → Sudarshan compiles a typed DAG
  → DAG selects deterministic workers and bounded specialists
  → validators gate results
  → Harness observes and presents the artifact
```

The skill is a governed procedure and contract. A specialist agent may be used inside the skill when the work requires adaptive reasoning. CrewAI is useful for local role-based collaboration inside a selected pipeline, especially where existing crews already implement content analysis, writing, critique, or domain roles. It should not become a second global scheduler beside LangGraph and the Harness.

### 6.2 Decision rules for using a specialist agent

Use a specialist agent only when:

- the work requires interpretation rather than deterministic transformation;
- the subtask has a stable input/output contract;
- the subtask can be independently evaluated;
- parallel execution or expertise separation produces a real benefit;
- the token/time budget justifies the delegation.

Use deterministic code when:

- the task is parsing, geometry, rendering, file conversion, checksum, schema validation, or media composition;
- correctness is more important than open-ended reasoning;
- the operation is repeated frequently.

### 6.3 Avoiding tool and skill overload

Recent work on MCP and skill retrieval indicates that tool selection becomes harder as candidate tools increase and skills become semantically similar. Expose high-level Sudarshan tools to user-facing Harness sessions and reserve lower-level tools for trusted specialist profiles.

The native Harness skill registry should expose compact summaries only. Full skill bodies, references, assets, and examples should load on demand. The same rule should apply to MCP skill discovery.

## 7. Execution, parallelism, waiting, and recovery

### 7.1 Durable run lifecycle

```text
accepted
  → queued
  → planning
  → running
  → waiting_for_input | waiting_for_approval | retrying
  → validating
  → completed | failed | cancelled
```

Each run has an explicit `run_id`, `skill_id`, `skill_version`, `execution_version`, `idempotency_key`, policy context, and artifact manifest.

### 7.2 Parallel DAG execution

The planner emits nodes with:

```text
node_id, input_refs, output_schema, dependencies,
estimated_cost, timeout, retry_policy, concurrency_group,
required_capabilities, side_effect_class, validator_ids
```

The scheduler:

1. validates the graph is acyclic or explicitly supports a bounded loop;
2. admits nodes whose dependencies are complete;
3. acquires a worker lease and concurrency slot;
4. deduplicates by idempotency key/content hash;
5. persists heartbeats and output references;
6. retries only retryable failures;
7. releases dependents when outputs validate;
8. pauses the run when an input or approval is required.

For a PPT with a flowchart, evidence analysis, narrative planning, theme selection, and asset retrieval can run in parallel. Flowchart layout depends on the slide plan and graph IR; final rendering depends on all slide IR components; visual QA depends on rendered images.

### 7.3 Waiting semantics

The user-facing Harness should receive an immediate accepted response with a run/task handle. It can show live progress, but reconnect must work from the durable run projection. Use:

```text
live notifications → quick progress
get_status(run_id)  → durable snapshot
wait(run_id)        → bounded blocking for interactive clients
resume(run_id)      → clarification/approval/revision
cancel(run_id)      → cooperative cancellation
```

Never keep a browser request open for the full life of a video or presentation run.

### 7.4 Failure handling

Classify failures as:

- input/policy failure: ask user or reject;
- provider/transient failure: retry or fail over;
- worker failure: retry with lease recovery;
- semantic validation failure: targeted agent repair;
- visual validation failure: targeted layout/renderer repair;
- structural failure: re-plan a bounded subgraph;
- security/classification failure: stop and require operator action.

The repair loop must send the responsible worker a compact issue bundle, such as `slide-4.flowchart.edge-crossing`, rather than replaying the entire run transcript.

## 8. MCP contract and portability

The latest MCP specification now includes optional Tasks, Skills over MCP, and MCP Apps extensions, while the 2026 update emphasizes stateless requests, explicit handles, caching metadata, and better routing for Streamable HTTP.[^13]

Sudarshan should implement the following compatibility layers:

```text
baseline MCP tools
  list skills, start run, status, wait, resume, cancel, artifact

optional MCP extensions
  Tasks           long-running task handle and polling
  Skills over MCP reusable structured instructions
  MCP Apps        inline artifact preview and execution UI
```

Do not assume every external Harness supports the optional extensions. Keep ordinary tools and explicit `run_id` status calls as the fallback.

The native DeepSeek Harness can offer richer UI and skill behavior, while another MCP-compatible Harness can still submit and observe the same Sudarshan runs.

## 9. Full implementation roadmap

### Phase 0 — Baseline and safety, weeks 1–2

Deliverables:

- freeze current contracts and create an execution-version field;
- document the current synchronous MCP behavior and dependency compatibility;
- establish an artifact manifest and checksum format;
- add a run database projection and append-only safe events;
- create ten PPT/video/summary benchmark fixtures;
- measure baseline quality, latency, token use, and failure rate;
- pin Cognee storage paths and dataset naming;
- define skill governance, ownership, review, and rollback policy;
- add `.env` secret scanning and verify secrets never enter artifacts or memory.

Exit criteria:

- every run has a traceable ID;
- baseline metrics are recorded;
- current behavior can be replayed in tests;
- no secret or raw chain-of-thought appears in the dashboard contract.

### Phase 1 — Durable asynchronous execution, weeks 3–5

Deliverables:

- `start_sudarshan_run` and explicit `run_id` contract;
- durable status, events, resume, cancel, and artifact endpoints;
- queue, worker lease, idempotency, timeout, retry, and cancellation behavior;
- MCP compatibility tests for stdio and Streamable HTTP;
- Harness run card and Execution Monitor skeleton;
- token/cost/latency counters per run and child node.

Exit criteria:

- disconnect/reconnect does not lose run state;
- duplicate submissions do not duplicate artifacts;
- cancelled runs stop at safe boundaries;
- two independent tasks execute concurrently without state leakage.

### Phase 2 — Skill runtime and native Harness, weeks 6–8

Deliverables:

- versioned skill manifest format;
- compact skill catalog and on-demand loading;
- hierarchical skill router;
- tool profiles for user, analyst, renderer, operator, and developer roles;
- native Harness UI plugin for runs, artifacts, evidence, approvals, and logs;
- external Harness compatibility through baseline MCP tools;
- native model routing and provider fallback policy.

Exit criteria:

- a skill can be added without modifying the core coordinator;
- the native UI displays the same durable run projection as the API;
- an external MCP client can start and observe a run;
- full skill bodies are not injected into every turn.

### Phase 3 — PPT visual production system, weeks 9–13

Deliverables:

- `PresentationSpec` and slide archetype schemas;
- flowchart skill and `FlowchartSpec`;
- canonical geometry and SVG renderer;
- editable PPTX shape/connector renderer;
- theme registry and reusable layout templates;
- rendered-slide visual QA;
- targeted repair loop;
- evidence ledger and speaker-note/source generation.

Exit criteria:

- flowcharts are editable in PowerPoint;
- geometry is shared by preview and PPTX renderers;
- no overflow or off-canvas elements in the benchmark set;
- visual quality improves over the current placeholder-heavy renderer;
- every slide has a measurable quality report.

### Phase 4 — Cognee memory evolution, weeks 14–17

Deliverables:

- working/case/system/user memory separation;
- typed claim, source, artifact, and experience records;
- stage-specific retrieval router;
- freshness, contradiction, supersession, and forgetting rules;
- session-memory to permanent-memory improvement path;
- retrieval traces and memory evaluation suite;
- restricted operator Cognee MCP surface.

Exit criteria:

- retrieval payload is smaller than the current full-context baseline;
- groundedness improves or remains stable while token use falls;
- obsolete facts are detected or excluded;
- case isolation tests pass;
- no unreviewed run transcript becomes system memory.

### Phase 5 — Video and remaining pipelines, weeks 18–23

Deliverables:

- storyboard IR;
- scene-level cache keys;
- parallel media workers;
- provider rate limits and fallbacks;
- audio, subtitle, timing, and provenance validators;
- reusable artifact QA framework shared by PPT, video, infographic, and document skills;
- migration of executive summary, advisory, LinkedIn, infographic, and video pipelines into skill packages.

Exit criteria:

- video token use falls against baseline;
- independent media jobs run in parallel;
- partial failures resume without rebuilding successful scenes;
- all migrated pipelines expose the same run/status/artifact contract.

### Phase 6 — Evaluation, hardening, and NTRO pilot, weeks 24–28

Deliverables:

- end-to-end benchmark dashboard;
- adversarial prompt and memory-poisoning tests;
- permission and classification tests;
- load tests for concurrent runs;
- visual regression suite;
- disaster recovery and backup restore test;
- operator training and demo script;
- pilot release with rollback plan.

Exit criteria:

- quality and reliability targets are met for the selected pilot scope;
- security review passes;
- operators can understand and control a run;
- artifacts are reproducible from a manifest and pinned versions;
- the system can be used through native DeepSeek Harness and a second MCP client.

## 10. Roles and team structure

### Agentic architecture team

- skill manifest and versioning;
- coordinator/DAG contracts;
- prompt/module design and model routing;
- agent delegation policy;
- evaluation harness and benchmark design;
- CrewAI integration boundaries;
- skill promotion and governance.

### Backend and execution team

- run store, event store, queue, worker leases;
- MCP tools and task compatibility;
- LangGraph orchestration boundary;
- provider adapters and retry/failover;
- artifact storage and manifests;
- concurrency, idempotency, cancellation, and recovery;
- Cognee adapter, datasets, retrieval router, and memory governance;
- authentication, authorization, classification, and audit.

### Frontend and native Harness team

- Harness plugin/bundle composition;
- skill catalog and invocation UX;
- Execution Monitor;
- run detail and parallel lanes;
- approval/clarification UI;
- artifact workspace and previews;
- evidence drawer;
- accessibility, reconnect behavior, and visual regression tests.

### Presentation and rendering team

- design system and themes;
- slide archetypes and templates;
- flowchart IR and layout engine;
- SVG/PPTX renderers;
- visual QA and repair;
- PDF/image/video preview pipeline.

### Security and evaluation owner

- skill/package security review;
- memory poisoning and data-leak testing;
- classification and case-isolation tests;
- benchmark scoring and release gates;
- red-team scenarios and audit review.

## 11. Metrics and release gates

### Artifact quality

- content groundedness;
- claim-source coverage;
- slide narrative coherence;
- visual readability;
- layout overflow rate;
- flowchart graph integrity;
- human preference score;
- artifact editability.

### Agent quality

- task success rate;
- correct skill-selection rate;
- tool-selection error rate;
- clarification precision;
- validator catch rate;
- repair success rate;
- unsupported-claim rate;
- safe refusal rate.

### System quality

- p50/p95 time to first progress;
- p50/p95 completion time;
- concurrent-run throughput;
- queue wait time;
- retry rate;
- cancellation time;
- reconnect recovery rate;
- duplicate artifact rate;
- worker utilization;
- cost and token use per artifact.

### Memory quality

- relevant evidence recall;
- stale-memory rate;
- contradiction rate;
- retrieval payload tokens;
- case-isolation violations;
- successful experience reuse;
- forgetting/deletion correctness.

Do not release a skill because a single demo looks good. Release it only when it passes schema, policy, evidence, visual, reliability, and benchmark gates.

## 12. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Three orchestrators fight each other | Harness selects; Sudarshan coordinates; CrewAI is local specialist collaboration |
| Tool/skill overload confuses the model | hierarchical catalog, profiles, compact summaries, high-level tools |
| Beautiful but incorrect deck | evidence ledger and semantic gate before visual polish |
| Correct but ugly deck | IR, theme/layout engine, rendered visual QA, targeted repair |
| Memory poisoning | governed write path, provenance, review state, expiry, contradiction checks |
| Stale memory | validity intervals, supersession, `forget`, refresh policies |
| MCP disconnect loses work | explicit run IDs, durable state, reconnectable status |
| Native Harness lock-in | keep Sudarshan MCP contract stable and UI adapter thin |
| Harness job process dies | backend queue and durable workers own long-running work |
| Model creates unsafe skill/script | signed packages, allow-list, sandbox, code review, offline promotion |
| Token costs grow with collaboration | typed IR, compact failure bundles, caching, deterministic workers, selective delegation |
| Renderer regressions | visual snapshot tests, artifact manifests, pinned renderer versions |

## 13. First 15 engineering tickets

1. Add `execution_version`, `skill_id`, `skill_version`, and `idempotency_key` to the run contract.
2. Add asynchronous `start_sudarshan_run` while preserving `run_sudarshan` for compatibility.
3. Persist safe run events and expose reconnectable status.
4. Add a `SkillManifest` schema and one versioned `presentation` skill.
5. Replace PPT bullet-only output with a discriminated slide IR.
6. Add `FlowchartSpec` and graph validators.
7. Build canonical geometry plus SVG preview rendering.
8. Render editable flowchart shapes/connectors into PPTX.
9. Add slide image rendering and visual regression tests.
10. Add targeted visual repair issue IDs.
11. Add Cognee working/case/system/user dataset policy.
12. Add retrieval traces, freshness, supersession, and memory-write review state.
13. Add native Harness Execution Monitor skeleton.
14. Add a second MCP-client compatibility test.
15. Create the benchmark dashboard and define release thresholds.

## Final architecture statement

Sudarshan 2.0 should be a skill-driven, evidence-grounded, durable execution platform:

```text
user request
  → native or external Harness understands intent
  → Harness loads compact skill guidance
  → Harness submits one high-level Sudarshan run
  → Sudarshan validates policy and compiles a typed DAG
  → specialized agents reason where needed
  → deterministic workers render and transform artifacts
  → Cognee supplies governed connected memory
  → structural, semantic, evidence, and visual validators inspect output
  → targeted repair or approval occurs
  → artifact, manifest, evidence, and safe logs return to the user
```

The flowchart use case is therefore not an exception. It is the model for the whole product: separate intent from representation, representation from rendering, and rendering from verification. The native DeepSeek Harness becomes special because it makes this full lifecycle visible and controllable in one operator experience, while MCP keeps the execution platform portable to other Harnesses.

## 14. Competitive differentiation

### 14.1 What competitors already do well

Sudarshan should assume that generic AI creation is already competitive. Gamma now offers an agent that accepts sources, asks questions, shapes an outline, and builds presentations, documents, or social posts.[^14] Canva offers AI presentation generation, outline and content creation, and brand application through its design ecosystem.[^15] General-purpose assistants increasingly support skills, tools, memory, connectors, and custom instructions.

Therefore, these are not defensible differentiators by themselves:

- “We have an AI chat interface.”
- “We support skills.”
- “We can call MCP tools.”
- “We generate PPT files.”
- “We use multiple agents.”
- “We use a knowledge graph.”

Those are capabilities that competitors can copy or already provide.

### 14.2 The defensible position

Sudarshan should own a narrower but deeper category:

> **A policy-controlled agentic production system that turns sensitive, scattered evidence into auditable, presentation-ready and media-ready artifacts through durable execution, reusable visual programs, quality gates, and governed memory.**

The product should be differentiated on the complete lifecycle:

```text
evidence
  → understanding
  → typed skill plan
  → parallel execution
  → editable artifact IR
  → deterministic rendering
  → evidence and policy validation
  → visual quality validation
  → human release or controlled delivery
  → reusable validated experience
```

This is materially different from a general chatbot or a design-first presentation generator.

### 14.3 Five product moats

#### 1. Evidence-to-artifact traceability

Every material statement, chart, flowchart node, image, and speaker note can point to a source excerpt, claim ID, or explicitly labeled assessment. The user can inspect why an element exists and what evidence supports it.

Competitors may produce attractive slides; Sudarshan should make the artifact defensible and reviewable.

#### 2. Artifact quality as a controlled engineering process

Sudarshan should expose a measurable quality report:

```text
content groundedness: 93/100
claim coverage: 100%
visual readability: pass
flowchart integrity: pass
policy/classification: pass
unresolved gaps: 2
```

The system should reject or revise artifacts rather than treating the first model output as complete. PPTAgent's separation of content, design, and coherence evaluation supports this direction.[^2]

#### 3. Reusable visual programs, not one-shot templates

Store presentation IR, flowchart IR, layout constraints, themes, validators, and repair patterns. A later request can reuse a proven visual program while adapting the evidence and narrative.

This is stronger than caching a final slide image because the artifact remains editable, explainable, and adaptable.

#### 4. Durable agentic execution

Long-running tasks should be resumable, cancellable, parallel, observable, and recoverable after a disconnect. The system should show the user what is waiting, what failed, what was retried, and what artifact version was produced.

This gives Sudarshan a platform advantage over simple prompt-to-PPT products.

#### 5. Controlled domain memory

Cognee should connect cases, claims, entities, artifacts, procedures, and validated experience while preserving classification, scope, freshness, and provenance. The value is not “we remember everything”; it is “we retrieve the right permitted evidence and learn only from validated outcomes.”

### 14.4 Competitive comparison

| Category | Strong at | Sudarshan opportunity |
|---|---|---|
| General assistants | conversation, broad tools, flexible tasks | evidence-bound domain execution, durable runs, audit, artifact QA |
| Gamma/Canva-style products | visual templates, fast drafts, collaboration, brand design | sensitive evidence, editable analytical diagrams, claims, provenance, policy gates |
| Workflow automation platforms | connectors, triggers, deterministic business automation | adaptive agent planning plus artifact quality and visual verification |
| Agent frameworks | orchestration primitives and developer flexibility | complete operator product, memory governance, UI, artifacts, release controls |
| MCP servers | interoperability and tool exposure | a full execution platform behind a portable MCP boundary |
| Generic memory systems | retrieval and persistence | scoped case memory tied to evidence, artifact versions, validators, and corrections |

Do not position Sudarshan as universally better than Canva or Gamma at general-purpose design. Position it as better for controlled, evidence-heavy, multi-stage, reviewable production.

### 14.5 Product features competitors will find harder to copy together

The moat is the combination, not any one feature:

1. `Evidence Ledger`: claim/source/uncertainty graph attached to every artifact.
2. `Artifact IR`: one editable representation that renders to PPTX, PDF, SVG, web, and preview images.
3. `Execution Monitor`: durable parent/child DAG, safe event log, retries, waiting states, and approvals.
4. `Quality Gate`: schema, evidence, policy, semantic, and visual validators with repair issue IDs.
5. `Memory Evolution`: Cognee system memory learns from validated repairs and feedback, not raw transcripts.
6. `Skill Marketplace with Governance`: signed, versioned, benchmarked skills with permissions and rollback.
7. `Provider-neutral execution`: DeepSeek native Harness, other MCP Harnesses, and future model providers use the same run contract.
8. `Controlled deployment`: local or private infrastructure, explicit data boundaries, and classification-aware operation.

### 14.6 What to demonstrate to judges or customers

Use one end-to-end demonstration instead of a list of features:

```text
1. Give Sudarshan scattered documents and a meeting note.
2. Ask for an executive briefing with an architecture flowchart.
3. Show evidence retrieval and uncertainty separation.
4. Show the planner selecting the flowchart skill.
5. Show parallel evidence, narrative, and asset work.
6. Show the editable flowchart IR and live Execution Monitor.
7. Intentionally introduce a layout failure.
8. Show the visual validator catching it and a targeted repair.
9. Show the final PPTX, evidence drawer, and quality report.
10. Re-run a similar request and show reuse of cached IR/layout knowledge.
```

That demonstration proves a complete system advantage rather than a generic chat wrapper.

## 15. Caching architecture for Sudarshan

### 15.1 Caching is not one feature

Sudarshan needs several caches with different correctness rules:

```text
1. catalog cache       skill/tool/resource discovery
2. prompt-prefix cache repeated stable instructions and evidence prefixes
3. retrieval cache     scoped evidence/context packs
4. tool-result cache   pure or idempotent tool outputs
5. plan/IR cache       reusable structured reasoning and visual programs
6. render cache        deterministic artifact previews and conversions
7. experience cache    validated repair patterns and procedures
```

The system must never treat all cached data as equally reusable. A final answer, a classified evidence bundle, a deterministic SVG render, and a reusable layout pattern have different risk profiles.

### 15.2 Research-backed caching principles

Provider prompt caching is most effective when stable content is kept in a reusable prefix and dynamic tool results are placed outside the cached region. A 2026 evaluation across three providers found large cost and time-to-first-token improvements, but also found that naive full-context caching can increase latency and that cache-boundary design matters.[^16]

Anthropic's current documentation describes automatic or explicit prefix caching, short and extended TTLs, minimum cacheable prompt lengths, workspace isolation, and invalidation when tools, images, or other prompt configuration changes.[^17] OpenAI's current API exposes a prompt-cache key and cache options for controlling cache reuse and diagnostics.[^18]

The most important architectural insight is that agent systems should cache stable intermediate representations, not only prompt/answer pairs. SemanticALLI reports much higher reuse when it caches structured intermediate artifacts such as intent and visualization representations rather than relying only on linguistic similarity.[^19]

### 15.3 Cache layers and policies

| Layer | Cache key | Typical TTL | Safe reuse rule |
|---|---|---:|---|
| Skill/tool catalog | server version, client profile, scope | 5–60 min | safe if `ttlMs` and `cacheScope` permit |
| Stable prompt prefix | model, skill version, system prompt, tool schema | provider TTL | exact prefix and compatible model/config only |
| Run context pack | case, source snapshot, scope, query, policy | 5–30 min | invalidate on source or policy change |
| Pure tool result | tool version, normalized args, input refs | minutes–days | only for read-only/idempotent tools |
| Plan template | skill version, normalized intent, constraints | days | revalidate dependencies and policy before use |
| Slide/flowchart IR | semantic content hash, theme, renderer version | days–months | reuse only if evidence and compatibility checks pass |
| Rendered artifact | IR hash, renderer, fonts, theme | long-lived | deterministic exact match; access control still applies |
| Experience pattern | validated failure signature, skill version | weeks–months | promote only after evaluation and review |

The latest MCP revision also defines `ttlMs` and `cacheScope` for cacheable list/resource results. Sudarshan should use those hints for skill catalogs and public or private resources, while retaining its own cache policy for application runs.[^20]

### 15.4 Cache key design

Every cache key should include the dependencies that can change correctness:

```text
cache_key = hash(
  operation,
  skill_id + skill_version,
  model_id + model_version,
  model_parameters,
  tool_schema_hash,
  policy_hash,
  memory_snapshot_id,
  source_snapshot_hash,
  input_reference_hash,
  theme_version,
  renderer_version,
  locale,
  classification_scope
)
```

Do not key only on the user's natural-language prompt. Two identical prompts can require different results when the case, evidence, policy, model, renderer, or classification scope changes.

### 15.5 Prompt-prefix caching

Structure model requests like this:

```text
[stable prefix]
  system policy
  skill instructions
  tool schemas
  renderer rules
  stable case/project constraints

[dynamic suffix]
  current user request
  current evidence excerpts
  latest tool results
  validator failures
```

Keep the stable prefix byte-identical. Put changing evidence and tool results at the end. Do not add timestamps, random IDs, or changing counters inside the stable prefix.

For parallel calls, use a singleflight mechanism: the first request warms the provider cache; other identical requests wait briefly for that warm-up rather than all creating independent writes. Provider documentation notes that cache entries may not become available until the first response starts, so fan-out should coordinate the warm-up request.[^17]

Track provider-reported cache reads and writes. A cache flag without observed cache-read tokens is not evidence that caching is working.

### 15.6 Retrieval/context caching

Cache the output of retrieval, not only the query:

```text
ContextPack
  query intent
  permitted scopes
  source snapshot
  claim IDs
  excerpts and locators
  freshness and confidence
  token estimate
  generated_at
```

A context cache hit can avoid repeated Cognee calls and repeated prompt assembly. The cache must be invalidated when:

- source documents change;
- a claim is corrected or superseded;
- case permissions change;
- classification changes;
- the retrieval policy changes;
- the memory dataset is rebuilt.

Do not cache a context pack across users or cases unless the data is explicitly public and the cache scope permits sharing.

### 15.7 Tool-result caching

Classify tools before allowing caching:

```text
PURE_READ       safe exact cache
IDEMPOTENT_WRITE cache only with idempotency and state version
NON_IDEMPOTENT  never replay automatically
SIDE_EFFECTFUL  never cache as a result; cache only status metadata
```

Examples:

- cached: parse a PDF by checksum, render a fixed IR with a fixed renderer, inspect an immutable image, retrieve a public document version;
- conditionally cached: Cognee retrieval for an unchanged source snapshot;
- not cached: send email, publish artifact, change classification, delete memory, invoke a provider that charges or mutates external state.

### 15.8 Plan and IR caching: the main Sudarshan advantage

This is where Sudarshan can outperform generic prompt caching.

Cache reusable structured work products:

```text
normalized_intent
evidence_query_plan
slide_narrative_pattern
flowchart_layout_pattern
theme selection
validator repair pattern
provider fallback decision
```

For example, two different user prompts may both produce an architecture diagram with:

```text
left-to-right direction
four stages
one highlighted decision gate
two parallel branches
bottom evidence strip
```

The exact final text should not be reused blindly, but the validated layout pattern can be reused safely after filling it with new evidence.

This is more valuable than answer caching because the cache remains useful even when wording changes. It also preserves editability and makes cache reuse inspectable.

### 15.9 Artifact/render caching

Use content-addressed artifact storage:

```text
artifact_id = hash(IR + renderer_version + theme_version + fonts + locale)
```

If the same IR and renderer inputs appear again, reuse the PPTX/SVG/PDF/preview files. Store a manifest containing:

- input references;
- IR checksum;
- renderer and theme versions;
- font versions;
- quality report;
- evidence ledger;
- classification and permitted audience;
- creation and expiration timestamps.

Never bypass access control because an artifact is cached. The cache determines whether computation can be skipped; it does not determine who may read the result.

### 15.10 Invalidation and versioning

Use event-driven invalidation:

```text
skill.updated             → invalidate skill/prompt/plan caches
tool_schema.updated       → invalidate prompt/plan caches
source.ingested           → invalidate evidence/context caches
claim.corrected           → invalidate affected context and artifact caches
policy.updated            → invalidate scoped context and release decisions
theme.updated             → invalidate render caches, not evidence plans
renderer.updated          → invalidate render caches, preserve IR
model.updated             → invalidate prompt/plan caches as configured
```

Prefer immutable versioned inputs over in-place mutation. A new source snapshot or renderer version should produce a new cache key and artifact version. This makes invalidation auditable and avoids hidden stale state.

### 15.11 Semantic cache safety

Semantic caching is useful for analysis and planning but dangerous for actions. Use conservative thresholds and validators:

```text
semantic hit candidate
  → compare normalized intent
  → compare scope and policy
  → compare source freshness
  → compare required output schema
  → validate cached plan/IR
  → reuse or fall back to fresh planning
```

The cache should return a candidate plan or IR, not silently return a final answer for a materially different request. Apple's recent work on verified semantic caching similarly separates vetted static entries from dynamic online entries and emphasizes that similarity thresholds create a safety/coverage tradeoff.[^21]

### 15.12 Cache stampede, concurrency, and backpressure

At the backend, implement:

- per-key singleflight locks;
- short lock lease and owner heartbeat;
- stale-while-revalidate for safe read-only data;
- negative caching for repeated invalid inputs with short TTLs;
- bounded waiting for cache fill;
- queue-aware admission control;
- per-tenant and per-case cache quotas;
- LRU or cost-aware eviction;
- encryption or strict namespace isolation for sensitive entries.

For a PPT run, five parallel workers should not independently regenerate the same evidence pack or theme assets. One worker should fill the cache; the others should reuse it or wait for a bounded interval.

### 15.13 Cache observability

The Execution Monitor should show:

```text
cache layer
hit/miss
cache age
key version
tokens avoided
latency avoided
cache write cost
invalidation reason
false-hit or repair rate
```

Track these metrics:

- hit rate by layer and skill;
- cache-read and cache-write tokens;
- cost saved versus no-cache baseline;
- time-to-first-token improvement;
- duplicate work avoided;
- stale-hit rate;
- semantic false-hit rate;
- invalidation frequency;
- cache storage cost;
- case/tenant isolation violations.

The cache is successful only if quality is unchanged or improved. A high hit rate with stale or incorrect artifacts is a failure.

### 15.14 Recommended cache rollout

```text
Phase 1: exact artifact and deterministic tool caching
Phase 2: provider prompt-prefix caching and stable prompt layout
Phase 3: retrieval/context-pack caching with source snapshots
Phase 4: plan and presentation-IR caching
Phase 5: validated experience and semantic candidate caching
```

Start with exact and deterministic caches because they are easiest to verify. Introduce semantic plan reuse only after the benchmark suite can measure false hits and stale reuse.

## 16. Updated strategic decision

The unique value of Sudarshan should be the controlled transformation system, not the model or the chat screen:

```text
Competitors optimize for generation speed or design breadth.
Sudarshan optimizes for defensible, recoverable, evidence-grounded production.
```

Its strongest technical advantage can become the combination of:

```text
portable MCP boundary
+ native DeepSeek operator experience
+ typed artifact IRs
+ durable parallel execution
+ deterministic renderers
+ visual/evidence/policy quality gates
+ governed Cognee memory
+ cacheable intermediate reasoning
```

This combination is a credible scale strategy and a stronger competitive story than claiming that Sudarshan merely has more agents or more plugins.

## 17. Team-parallel implementation handoff

The detailed frontend, backend, agentic, rendering, memory, evaluation, fixture, branch, PR, and first-two-weeks guide is maintained in [Sudarshan 2.0 Team-Parallel Implementation Guide](sudarshan-2.0-team-parallel-guide.md). It is the execution handoff for the `Sudarshan2.0` branch and is designed so teams can build against shared contracts and fixtures without waiting for the complete backend or UI.

## Sources

[^1]: SlideGen, “Collaborative Multimodal Agents for Scientific Slide Generation,” 2025. [Project and paper summary](https://y-research-sbu.github.io/SlideGen/).
[^2]: Zheng et al., “PPTAgent: Generating and Evaluating Presentations Beyond Text-to-Slides,” EMNLP 2025. [arXiv](https://arxiv.org/abs/2501.03936).
[^3]: “Textual-to-Visual Iterative Self-Verification Slide Generation Agent,” 2025. [OpenReview paper](https://openreview.net/pdf?id=uWAAzkvRwE).
[^4]: Xu and Tai, “Meta-Agent: From Task Descriptions to Verified Multi-Agent Systems,” 2026. [arXiv](https://arxiv.org/abs/2605.25233).
[^5]: “Graph-based Agent Memory: Taxonomy, Techniques, and Applications,” 2026. [arXiv](https://arxiv.org/abs/2602.05665).
[^6]: Uddin et al., “From Recall to Forgetting: Benchmarking Long-Term Memory for Personalized Agents,” 2026. [Memora](https://arxiv.org/abs/2604.20006); Ma et al., “Benchmarking Continual Agent Memory for Online Learning, Transfer, and Forgetting,” Lifelong Agent @ ICLR 2026. [AgentMemoryBench](https://openreview.net/pdf/2cd400b6dec127be21f88da3528c021c699c914f.pdf).
[^7]: [Cognee documentation: Introduction](https://docs.cognee.ai/getting-started/introduction) and [Remember](https://docs.cognee.ai/core-concepts/main-operations/remember).
[^8]: Repository documentation: `deepseek-harness/docs/architecture.md`, `deepseek-harness/docs/subsystems/skills.md`, `deepseek-harness/docs/subsystems/subagent.md`, and `deepseek-harness/docs/subsystems/jobs.md`.
[^9]: [Cognee MCP overview](https://docs.cognee.ai/cognee-mcp/mcp-overview) and [Cognee MCP tools](https://docs.cognee.ai/cognee-mcp/mcp-tools).
[^10]: [Cognee Python search API](https://docs.cognee.ai/python-api/search).
[^11]: [Cognee graph stores](https://docs.cognee.ai/setup-configuration/graph-stores).
[^12]: [Cognee local/API MCP setup](https://docs.cognee.ai/cognee-mcp/mcp-local-setup).
[^13]: [Latest MCP specification](https://modelcontextprotocol.io/specification/latest) and [MCP 2026-07-28 update](https://blog.modelcontextprotocol.io/posts/2026-07-28/).
[^14]: Gamma, “Create with Agent.” [Gamma Help Center](https://help.gamma.app/en/articles/15002203-create-with-agent).
[^15]: Canva, “AI Presentation Maker.” [Canva](https://www.canva.com/create/ai-presentations/).
[^16]: Lumer et al., “Don’t Break the Cache: An Evaluation of Prompt Caching for Long-Horizon Agentic Tasks,” 2026. [arXiv](https://arxiv.org/abs/2601.06007).
[^17]: [Anthropic Prompt Caching documentation](https://platform.claude.com/docs/en/build-with-claude/prompt-caching).
[^18]: [OpenAI Responses API reference: prompt cache key and options](https://developers.openai.com/api/reference/cli/resources/responses/methods/create).
[^19]: “SemanticALLI: Caching Reasoning, Not Just Responses, in Agentic Systems,” 2026. [arXiv](https://arxiv.org/abs/2601.16286).
[^20]: [MCP 2026 SDK migration: cache fields and hints](https://ts.sdk.modelcontextprotocol.io/v2/migration/support-2026-07-28).
[^21]: Apple Machine Learning Research, “Asynchronous Verified Semantic Caching for Tiered LLM Architectures,” 2026. [Krites research summary](https://machinelearning.apple.com/research/semantic-caching).
