# Sudarshan 2.0: Native Harness and Agentic Skill Architecture

> Historical research direction. It records rationale and evidence; it does
> not override the implemented application boundary.

Status: proposed engineering direction

This document answers four questions:

1. What does a native DeepSeek Harness integration add beyond an MCP wrapper?
2. Can Sudarshan add a new Background Runs / Logs page to the Harness UI?
3. How should each existing pipeline become a powerful, reusable skill?
4. What is the scalable execution model for parallel work, waiting, quality, and recovery?

The attached OpenAI-style diagram is treated as a design reference, not as an implementation instruction. Its useful idea is the transformation from scattered context to a reusable workflow, a first draft, and a review/improvement loop. Sudarshan should implement that idea as typed contracts, durable state, evidence provenance, and validators—not as prompt text alone.

## Executive conclusion

The direction is good if the team adopts this boundary:

```text
DeepSeek Harness = host/runtime experience
  sessions, model adapter seam, skill loading, tool lifecycle, jobs, approvals, UI slots

Sudarshan = mission/application control plane
  NTRO policy, request understanding, evidence/memory, routing, DAG execution, providers,
  artifacts, quality gates, audit, classification, and scale-out workers
```

The Harness is valuable because its architecture is plugin-native: the model adapter, tool registry, session log, and agent loop are replaceable plugins, and profiles/bundles/patches compose those plugins at boot. This is a stronger host boundary than treating the Harness as a white-label chat screen. [DeepSeek Harness architecture](../../deepseek-harness/docs/architecture.md)

However, Harness does not automatically make a pipeline intelligent, cheap, safe, or horizontally scalable. Those properties must be implemented in Sudarshan. In particular, the current Sudarshan MCP `run_sudarshan` path calls the application synchronously; a production version needs an asynchronous submit/observe/resume contract backed by a durable queue and shared state.

## 1. What the native Harness adds

### 1.1 A real runtime seam, not only a branded interface

The Harness gives Sudarshan a standard host for:

- persistent session events and replayable history;
- model/provider adapters behind a replaceable seam;
- scoped tools with a guarded execution pipeline;
- agent lifecycle events and request interception;
- background jobs with ownership, status, bounded waits, and cancellation;
- approvals, commands, telemetry, and settings;
- composable browser views and typed conversation nodes.

This lets Sudarshan provide one MCP application boundary while still using native Harness lifecycle and UI capabilities. The existing repository integration already follows the right high-level ownership rule: the Harness invokes backend-owned tools while credentials, memory, providers, and pipeline execution remain in the Python service.

### 1.2 Deterministic, lazy skill loading

The Harness skill package supports a `/name` user gesture and a `skills/list` catalog. The host injects one canonical `<skill_content>` block at the pre-step boundary, and the same skill body can be loaded through the model-facing skill tool. This makes skill invocation consistent across menu selection, typed commands, and other clients. [Harness skill UI package](../../deepseek-harness/packages/client/ui-skill/README.md)

The important engineering implication is that a Sudarshan skill should be a versioned contract and policy package, not a long prompt. The skill body should tell the agent how to select typed tools and produce typed outputs; the backend should enforce those rules independently.

The skill package documentation also makes the token trade-off explicit: invoking a skill adds its rendered body to that turn. Therefore, lazy loading helps discovery and reuse, but it does not by itself solve token consumption. Sudarshan still needs compact context bundles, adaptive retrieval, caching, model routing, and strict output schemas.

### 1.3 Native background jobs and wait semantics

The Harness has a generic `ctx.jobs` runtime. Jobs have an owner, kind, label, lifecycle status, start/finish times, bounded output, cancellation, and a `wait` operation. The built-in job tools expose list/output/kill controls and clamp model-supplied waits to a configured maximum. [Harness background task runtime](../../deepseek-harness/docs/subsystems/jobs.md)

This is useful for the interactive host, but the production job of a PPT render, video encode, or external provider call must still be owned by Sudarshan's durable scheduler. Harness-local jobs are process-local in the reference implementation. They are excellent for host interaction and short-lived adapters; they are not a replacement for a shared distributed queue.

### 1.4 Native UI extension points

Yes, we can add new pages and panels. The correct approach is a Sudarshan client plugin/bundle mounted through the Harness profile, with a patch layer for configuration. Do not fork the core UI merely to change colors or insert a page.

The Harness UI supports business-owned registrations for keyed tool views and conversation nodes. A Sudarshan plugin can render a structured run card for `run_sudarshan`, a progress node for durable run events, artifact previews, and an operator view for background jobs. [Harness tool UI package](../../deepseek-harness/packages/client/ui-tool/README.md) and [Harness conversation extension model](../../deepseek-harness/docs/subsystems/conversation.md)

Recommended UI surfaces:

```text
Sudarshan client plugin
├── Run card             one tool call, current stage, status, artifact links
├── Execution Monitor    all authorized active/completed runs
├── Run detail           parent/child DAG, safe events, retries, approvals
├── Artifact workspace   PPT/video/SVG/document previews and downloads
└── Evidence drawer      claims, sources, uncertainty, quality verdicts
```

The Background Runs page should be an operator projection, not a raw log viewer. It should show safe structured events, not prompts, private memory, credentials, or hidden chain-of-thought.

### 1.5 Branding and legal boundary

The vendored Harness is MIT-licensed, but its own brand guidance says projects should describe themselves as “built on DeepSeek Harness” or “compatible with DeepSeek Harness,” avoid using the full trademark directly in the product name, and avoid implying official endorsement. Preserve the license and third-party notices in the distribution. [Harness brand guidance](../../deepseek-harness/BRAND_GUIDELINES.md) and [Harness license](../../deepseek-harness/LICENSE)

The defensible product statement is: “Sudarshan is an NTRO-focused, MCP-native agentic production system built on a plugin-composable Harness.” The differentiator is the controlled domain execution system, not the fact that another product also supports skills.

## 2. Background Runs / Logs page

### 2.1 Product name and purpose

Call the page **Execution Monitor** or **Background Runs**. Its purpose is to answer:

- What is running now?
- What is waiting, and what is it waiting for?
- Which skill, version, and pipeline produced this artifact?
- What ran in parallel and what depended on what?
- Which quality gate rejected or approved the result?
- Can an authorized operator resume, cancel, retry, or inspect the evidence?

This directly supports the NTRO demo requirement to show internal system logs on a dashboard while keeping the display safe and understandable.

### 2.2 Minimum run model

The backend should persist a parent run, child work items, and append-only safe events. A suitable first contract is:

```text
RunSummary
  run_id, parent_run_id, task_id, case_id
  skill_id, skill_version, pipeline, execution_version
  status, current_stage, progress_estimate
  started_at, updated_at, finished_at
  child_count, artifact_count, quality_status
  total_duration_ms, model_calls, input_tokens, output_tokens
  retry_count, classification_level

RunEvent
  event_id, run_id, child_id, sequence, timestamp
  stage, status, progress_estimate
  tool_name, safe_message, error_code
  duration_ms, attempt, artifact_id, requires_action
```

The repository already has a frontend-safe `ProgressEvent` shape and recommended SSE endpoints: `POST /runs`, `GET /runs/{run_id}`, `GET /runs/{run_id}/events`, `POST /runs/{run_id}/resume`, and `POST /runs/{run_id}/cancel`. Reuse that contract instead of creating a second dashboard-specific event model. [Sudarshan progress contract](../internal/pipeline-orchestration.md) and [frontend integration](../frontend-integration.md)

### 2.3 UI behaviors

The first page should include:

- status filters: queued, running, waiting for input, waiting for approval, retrying, completed, failed, cancelled;
- filters by case, skill, pipeline, date, operator, and classification level;
- live event stream over SSE with reconnect and last-sequence replay;
- expandable parent/child execution tree;
- stage timeline and parallel lanes;
- model/provider latency, token, and cost summary where available;
- quality-gate result with issues and required revisions;
- artifact links and preview cards;
- authorized cancel, resume, approve, retry, and “revise artifact” actions;
- a downloadable audit package containing the run manifest, event list, quality report, and artifact checksums.

Raw logs should be layered by role:

```text
User       stage, progress, safe message, artifact, action required
Operator   above + child graph, retries, provider timings, error codes
Developer  above + trace IDs, adapter diagnostics, bounded request metadata
Security   above + audit chain, policy decisions, access and classification events
```

Never expose raw recalled memory, API keys, unbounded agent output, or hidden chain-of-thought in the page. Use structured decision summaries, evidence references, and validator failures instead.

### 2.4 How to mount the page

Implement a `sudarshan-ui` client package that:

1. registers a typed `sudarshan/run` or `sudarshan/progress` conversation node for the chat surface;
2. registers a keyed tool view for the `run_sudarshan` MCP call;
3. subscribes to the authenticated backend event stream using `run_id` and a last-seen sequence;
4. renders the Execution Monitor route from a typed API projection;
5. registers artifact preview views for PPTX, SVG, MP4, PDF, and manifest files;
6. is included in a Sudarshan bundle/profile patch rather than modifying the Harness core.

The existing `sudarshan.cordis.yml` adds the MCP client. It must be extended with the UI bundle/plugin and, for the asynchronous design, the job/event bridge. The page should not infer state from assistant text; it must read the durable run projection.

## 3. Research-backed principles for agentic skills

The following papers support a bounded agent architecture:

### ReAct: reasoning plus actions

ReAct interleaves reasoning and tool actions so the system can update plans, use external sources, and handle exceptions. For Sudarshan, this means a skill may loop through `observe → act → validate → update plan`, but every action must be typed, authorized, and budgeted. [ReAct paper](https://arxiv.org/abs/2210.03629)

### Toolformer: learn when and how to call tools

Toolformer shows the value of selecting APIs with arguments and incorporating their results rather than forcing the model to perform every operation in text. For Sudarshan, expose narrow tools such as `retrieve_evidence`, `render_slide`, `inspect_media`, and `publish_artifact`; do not expose broad shell or provider credentials to the model. [Toolformer paper](https://arxiv.org/abs/2302.04761)

### Reflexion and CRITIC: feedback-driven improvement

Reflexion stores verbal feedback as episodic memory for later improvement, while CRITIC uses external tools to critique and revise outputs. For Sudarshan, quality review should return structured failures tied to an artifact component, and the next attempt should receive only the compact failure bundle—not the entire prior transcript. [Reflexion paper](https://arxiv.org/abs/2303.11366) and [CRITIC paper](https://arxiv.org/abs/2305.11738)

### Self-RAG and adaptive retrieval

Self-RAG argues for deciding when to retrieve and when to reflect instead of retrieving indiscriminately. This is especially relevant to the current video path, which can send large memory and plan strings into model calls. Each skill should request only the evidence needed for the current missing claim or decision, with a bounded retrieval budget. [Self-RAG paper](https://arxiv.org/abs/2310.11511)

### MemGPT and long-lived memory

MemGPT treats context as a virtual memory hierarchy, moving information between working context and longer-term storage. Sudarshan should use a compact working set for the active run, durable case memory for approved facts and artifacts, and a claim/evidence index for targeted retrieval. [MemGPT paper](https://arxiv.org/abs/2310.08560)

### Voyager: reusable executable skills

Voyager combines an automatic curriculum, a growing skill library, and iterative improvement from environment feedback and execution errors. The transferable lesson is not to let the model write arbitrary code; it is to store successful, versioned, composable skill units with preconditions, postconditions, and failure feedback. [Voyager paper](https://arxiv.org/abs/2305.16291)

### DSPy: optimize programs against metrics

DSPy treats LM calls as declarative modules and compiles them against a metric instead of hand-tuning prompt strings forever. Sudarshan can apply the idea offline: optimize each skill's prompt/module configuration against a fixed evaluation set for groundedness, structure, visual quality, latency, and cost. Do not perform uncontrolled online self-modification in the NTRO deployment. [DSPy paper](https://arxiv.org/abs/2310.03714)

### AgentBench and LongMemEval: measure the system, not the demo

AgentBench evaluates agents across multiple environments and highlights long-horizon reasoning, decision-making, and instruction-following failures. LongMemEval provides a benchmark for sustained assistant memory. Sudarshan should add a smaller domain-specific suite, using these as design references rather than claiming their scores. [AgentBench paper](https://arxiv.org/abs/2308.03688) and [LongMemEval benchmark](https://github.com/xiaowu0162/LongMemEval)

## 4. Pipeline-to-skill conversion method

Do not convert a pipeline by copying its CrewAI prompts into `SKILL.md`. Convert it into a **skill package** with a model-facing instruction, typed schemas, tools, policies, renderers, validators, recovery rules, and evaluation fixtures.

### 4.1 Skill package layout

```text
skills/<skill-id>/
├── skill.yaml              # identity, version, triggers, budgets, permissions
├── SKILL.md                # concise model-facing operating policy
├── schemas/
│   ├── input.schema.json
│   ├── plan.schema.json
│   ├── evidence.schema.json
│   ├── output.schema.json
│   └── quality.schema.json
├── tools.yaml              # allow-listed typed tools and limits
├── policy.yaml              # classification, approval, distribution rules
├── renderer.yaml            # renderer and artifact requirements
├── templates/               # deterministic layouts, prompts, visual themes
├── validators/              # structural, semantic, visual, policy validators
└── evals/                   # fixtures, expected properties, scoring harness
```

### 4.2 Required skill manifest

```yaml
id: presentation.case-brief
version: 2.0.0
triggers: [presentation, briefing, ppt, slides]
inputs: [case_context, evidence_bundle, audience, language, classification]
outputs: [presentation_spec, pptx, pdf, preview_images, evidence_ledger]
allowed_tools: [retrieve_evidence, render_pptx, inspect_slides, emit_artifact]
memory_scopes: [case-approved, run-working]
quality_gates: [schema, evidence_grounding, visual_layout, policy]
max_attempts: 2
max_model_calls: 8
requires_human_release: true
```

The backend must validate this manifest and enforce it. A model instruction is advisory; the tool registry and policy layer are authoritative.

### 4.3 Standard skill loop

```text
1. Understand: classify objective, audience, constraints, language, risk.
2. Gather: retrieve a bounded evidence bundle and identify unknowns.
3. Plan: emit a typed DAG of work items, dependencies, budgets, and stop rules.
4. Act: run deterministic code and allow-listed tools; fan out independent work.
5. Assemble: build a typed intermediate representation, not final pixels/text only.
6. Render: use the appropriate native or deterministic renderer.
7. Inspect: run schema, policy, evidence, semantic, and visual validators.
8. Repair: send compact structured failures to the responsible worker.
9. Release: require approval where policy says so; persist artifact and manifest.
10. Learn: store only validated, provenanced feedback and reusable patterns.
```

The agent decides what is missing and which allowed operation to request. The scheduler decides concurrency, admission, retries, cancellation, and fairness. This separation prevents an LLM from becoming the production scheduler.

### 4.4 Evidence bundle and compact context

Every skill should consume an `EvidenceBundle` containing:

```text
claim_id, source_id, excerpt_or_locator, timestamp, confidence,
fact_or_assessment, uncertainty, permitted_distribution, checksum
```

The model should see a compact claim ledger and only the excerpts needed for the current step. Store source documents and full extraction outside the prompt. Cache retrieval and repeated tool results by content hash. Replace full transcript replay with a typed `RunState` plus compact failure feedback.

This is the highest-priority change for the video token problem: plan once, represent the storyboard as structured data, retrieve only required facts, parallelize media work, and do not send the entire memory context to every scene call.

## 5. Conversion of the current pipelines

### Presentation / PPT skill

```text
Evidence analyst
  → narrative and slide-spec planner
  → deterministic theme/layout renderer
  → structural validator
  → rendered-image visual validator
  → bounded repair
  → PPTX + PDF/PNGs + evidence ledger + speaker notes
```

The intermediate representation should include slide intent, one message per slide, layout type, content blocks, citations, speaker notes, and classification label. The renderer should be theme-driven and use real layout components rather than only title/content placeholders. Visual QA must inspect rendered slides for overflow, contrast, hierarchy, empty space, chart readability, and citation legibility.

### Video skill

```text
Evidence/script planner
  → storyboard IR with 4–6 scenes by default
  → parallel image/TTS jobs with cache keys
  → deterministic media composer
  → audio/timing/subtitle/provenance QA
  → bounded repair or human review
```

Use one compact planning call plus targeted revisions. Keep scene prompts derived from a compact scene record, not the complete case memory. Parallelize independent image and audio jobs through the backend scheduler, cap provider concurrency, deduplicate by content hash, and persist partial outputs. Show per-scene progress in Execution Monitor.

### Executive summary skill

```text
Adaptive evidence retrieval
  → claim ledger and uncertainty map
  → concise summary IR
  → claim/source checker
  → style and policy validator
  → final artifact
```

The summary should distinguish verified facts, assessments, risks, and next steps. Its eval set should score unsupported claims, omission of high-priority facts, uncertainty calibration, and length compliance.

### Advisory skill

```text
Evidence and risk analyst
  → options and assumptions
  → recommendation with confidence
  → external/policy critic
  → human approval
  → released advisory artifact
```

Use stricter approval and provenance gates than for ordinary summaries. Store approval decisions as durable events.

### Infographic skill

```text
Structured data/evidence
  → declarative infographic IR
  → syntax/schema validation
  → SVG renderer
  → SVG/image inspection
  → artifact package
```

Keep the LLM away from raw pixel placement wherever possible. It should select a declarative template and populate validated data.

### LinkedIn/public-safe draft skill

```text
Approved public facts
  → audience/style draft
  → public-distribution policy gate
  → image decision
  → human publishing review
```

This skill must never silently publish. Make “draft only” a backend policy, not a prompt instruction.

## 6. Parallel execution and wait-time design

### 6.1 Execution model

Use one coordinator and bounded workers:

```text
Harness session
  → Sudarshan submit_run MCP tool
  → durable run record + queue
  → coordinator creates DAG work items
  → scheduler admits dependency-ready items
  → specialized workers execute skills/tools
  → event store publishes safe progress
  → quality/release gate
  → artifact store + final projection
```

The coordinator should not create arbitrary agent-to-agent conversations. Workers communicate through typed work-item inputs, outputs, and failure records. CrewAI can remain useful inside a skill for specialist roles, but it should not also own global routing and distributed scheduling. LangGraph can remain the domain graph/checkpoint layer while the queue owns durable execution.

### 6.2 Required production components

The current local SQLite/checkpointer and process-local executor are good for development and demo reliability. For scale, move to:

- shared Postgres or equivalent for run metadata, checkpoints, leases, and idempotency;
- Redis Streams, NATS, RabbitMQ, or a managed queue for work admission;
- object storage for artifacts and large logs;
- an append-only event table or event bus for progress;
- stateless API/MCP workers;
- dedicated provider workers for image, TTS, video, PPT rendering, and OCR;
- per-user, per-case, per-provider, and global concurrency limits;
- retry policies by error class, with idempotency keys;
- dead-letter queue and operator replay;
- metrics for queue wait, provider latency, token usage, quality rejection, and artifact failure.

### 6.3 Wait contract

Expose this MCP/API shape:

```text
start_sudarshan_run(request) → run_id, status=queued
get_sudarshan_status(run_id) → current projection + last events
wait_sudarshan(run_id, timeout_ms) → completed/waiting/running snapshot
resume_sudarshan(run_id, decision) → accepted status
cancel_sudarshan(run_id) → cancellation requested
```

`wait` is an observation operation, not a sleep loop. It should return on terminal state, required user action, or bounded timeout. The Harness can call it repeatedly; the UI should primarily consume SSE/WebSocket updates. A timeout must leave work alive and report `running`, not fail the run.

### 6.4 State machine

```text
queued → admitted → running → waiting_for_input
                         ├→ waiting_for_approval
                         ├→ retrying → running
                         ├→ completed
                         ├→ failed
                         └→ cancelling → cancelled
```

Every transition is durable, authorized, idempotent, and visible as a safe event. A worker lease must expire and be reclaimable. A retry must use the same logical work-item id with a new attempt number.

## 7. Evaluation plan before claiming “full agentic”

Build a 30–50 case regression set across the pipelines. Every run should be scored on:

- intent and pipeline selection accuracy;
- evidence recall and unsupported-claim rate;
- tool selection and invalid-tool rate;
- output schema validity;
- quality-gate detection precision and recall;
- visual layout and readability;
- artifact completeness and reproducibility;
- approval/policy enforcement;
- p50/p95 queue and end-to-end latency;
- input/output tokens and provider cost;
- successful recovery after tool/provider failure;
- cancellation and resume correctness;
- memory retrieval accuracy across sessions.

Run the suite on every skill version and renderer change. Add fault injection for provider timeouts, duplicate deliveries, worker death, stale leases, malformed model output, and partial artifact writes. A judge-facing demo should show the metrics dashboard, not only a successful output.

## 8. Recommended build sequence

### Phase 1: contracts and observability

1. Freeze `RunSummary`, `RunEvent`, `WorkItem`, `EvidenceBundle`, `ArtifactManifest`, and `QualityReview` schemas.
2. Add `start/status/wait/resume/cancel` semantics to the MCP boundary while preserving `run_sudarshan` compatibility.
3. Add idempotency keys, parent/child IDs, attempt numbers, correlation IDs, and safe event projection.
4. Build the Background Runs page against the existing SSE/progress contract.

### Phase 2: one end-to-end reference skill

5. Convert the PPT pipeline first because its output quality is visible to judges and users.
6. Create the skill manifest, compact evidence bundle, presentation IR, theme renderer, render-to-image QA, and bounded repair loop.
7. Register the skill in the Harness catalog and add the run/artifact tool cards.
8. Add a fixture suite and measure token, latency, grounding, and visual quality.

### Phase 3: efficient media and scale

9. Convert video to a structured storyboard skill with provider concurrency, caching, partial artifacts, and per-scene events.
10. Replace process-local fan-out with a durable queue and worker leases.
11. Move state/checkpoints and artifacts to shared production services.
12. Add quotas, fairness, rate limits, circuit breakers, and dead-letter replay.

### Phase 4: skill library and optimization

13. Add versioned reusable skill components and composition rules inspired by Voyager.
14. Add offline prompt/module optimization inspired by DSPy, evaluated only against approved fixtures.
15. Add long-horizon memory tests inspired by LongMemEval and agent/tool tests inspired by AgentBench.
16. Publish a technical comparison showing why Sudarshan is different: evidence-grounded domain skills, controlled execution DAGs, typed artifacts, visual QA, classification-aware audit, resumable runs, and MCP portability.

## Final recommendation

Proceed with the native Harness direction, but describe it precisely:

> DeepSeek Harness is Sudarshan's composable host runtime and reference UI. Sudarshan supplies the NTRO intelligence, evidence/memory layer, skill contracts, durable scheduler, provider adapters, artifact renderers, quality gates, and audit policy. The same MCP server can be mounted in another compatible host, while the Harness provides the richest native skill/session/job/UI experience.

That architecture is genuinely stronger for scale than a single workflow graph only after the asynchronous run contract, durable scheduler, typed skill packages, and evaluation gates are implemented. The most important near-term move is not adding more agents. It is making one pipeline—PPT—the reference skill with compact context, deterministic rendering, visual QA, background progress, resumability, and measurable quality.

## 9. Sandboxed artifact production

### 9.1 Direct answer

Yes. The DeepSeek Harness sandbox can materially improve Sudarshan's ability to produce valuable artifacts because it gives an agent a controlled execution workspace in which it can:

- write intermediate files and scripts;
- run deterministic renderers and converters;
- execute tests and lint/validation programs;
- inspect generated images, audio metadata, document structure, and logs;
- repair the artifact based on observed failures;
- package the final result with a manifest and checksums.

This changes the agent from “generate a text description of an artifact” to “propose work, execute tools, observe the produced artifact, and improve it.” CodeAct reports that executable code actions give agents a more composable action space and support self-debugging through execution feedback. The AI Scientist demonstrates the same general pattern for research artifacts: write code, execute experiments, visualize results, write a report, and run review. [CodeAct](https://arxiv.org/abs/2402.01030) and [The AI Scientist](https://arxiv.org/abs/2408.06292)

The benefit is therefore highest for artifact types whose quality can be inspected mechanically or visually:

```text
PPTX/PDF  → render pages → detect overflow/contrast/empty slides → repair
SVG       → validate syntax → render → inspect dimensions/text overlap → repair
Video     → encode → inspect duration/audio/subtitles/frames → repair
Document  → render pages → inspect pagination/style → repair
Data      → run schema/statistical checks → generate charts → verify values
Code      → run tests/type checks → inspect diff → package reproducible output
```

### 9.2 What the Harness sandbox actually protects

The repository's native process sandbox is a file-effect policy seam. It supports `read-only`, `workspace-write`, and `danger-full-access`; the local providers map those modes to Linux, macOS, and Windows mechanisms. The sandbox reports whether enforcement is `full` or `partial`, and confined execution must fail closed when no usable backend exists. [Harness process sandbox](../../deepseek-harness/docs/subsystems/sandbox.md)

The Harness also provides a sandboxed filesystem backend for model file mutations and a managed subprocess seam with bounded output, spill files, explicit working directories, credential scrubbing, and tree-scoped termination. These are good primitives for artifact production. They are not a complete security guarantee: the documented sandbox vocabulary governs file effects, while network access and process visibility require separate policy. [Harness sandboxed filesystem](../../deepseek-harness/packages/fs/fs-sandbox/README.md) and [Harness subprocess subsystem](../../deepseek-harness/docs/subsystems/subprocess.md)

On Windows, the repository documents ACL-based enforcement as potentially `partial` for some ambient ACL boundaries. Sudarshan must display the enforcement fact and reject workflows that require a strong isolation guarantee when the provider reports `partial`. For higher-risk execution, use a separately isolated container or microVM provider and keep the same capability seam.

### 9.3 Recommended artifact worker contract

Do not let the model directly mutate the final user artifact. Use a disposable run workspace:

```text
1. create isolated workspace for run_id/attempt
2. materialize only approved evidence, templates, and input assets
3. let the skill generate an intermediate representation and bounded scripts
4. execute the renderer/converter under the sandbox
5. run deterministic structural and policy validators
6. render previews and run visual/media inspection
7. return a candidate artifact plus a machine-readable report
8. promote only an approved candidate to object storage
9. delete or retain the workspace according to audit policy
```

The agent should receive typed tools such as:

```text
workspace_write(path, bytes/text)
run_renderer(command_id, input_manifest)
inspect_artifact(artifact_id, inspection_profile)
run_validator(validator_id, artifact_id)
request_revision(failure_bundle)
promote_artifact(artifact_id, release_policy)
```

`run_renderer` should select a backend-owned command from an allow-list. Do not pass arbitrary shell strings or provider credentials to the model. If code generation is useful, permit a bounded script in the disposable workspace and execute it with no credentials, restricted egress, CPU/memory/time limits, file-size limits, and an explicit artifact output directory.

### 9.4 Artifact manifest and promotion gate

Every candidate should carry an `ArtifactManifest`:

```text
artifact_id, run_id, attempt, artifact_type, path/object_uri
source_inputs, evidence_ids, renderer_id/version
preview_uris, sha256, size_bytes, created_at
validation_results, quality_status, sandbox_enforcement
```

Promotion requires all applicable gates:

- schema and file-integrity checks;
- evidence/provenance checks;
- policy/classification/distribution checks;
- renderer success and artifact completeness;
- visual or media inspection;
- malware/dependency/license checks for executable or imported content;
- human approval for release-sensitive or public artifacts.

This is where the product becomes differentiated. The sandbox creates a safe candidate; the promotion gate decides whether that candidate is trustworthy enough to deliver.

### 9.5 Why a custom agent-computer interface matters

SWE-agent's results support a related design lesson: agent performance depends on the interface presented to the agent, not merely on the underlying model. Its custom agent-computer interface was designed around repository navigation, editing, and execution rather than generic chat. Sudarshan should therefore expose an **Artifact-Computer Interface** with structured workspace operations, renderer commands, preview inspection, and validator feedback—not an unrestricted terminal. [SWE-agent](https://arxiv.org/abs/2405.15793)

For the PPT skill, the agent should see a slide-spec editor, render command, preview gallery, overflow report, and evidence ledger. For video, it should see a storyboard editor, per-scene render jobs, waveform/timing report, and frame samples. This gives the agent useful observations while avoiding unnecessary prompt tokens.

### 9.6 Sandbox limitations and failure modes

Do not claim that a sandbox makes the system autonomous or safe by itself. It does not guarantee:

- factual correctness of generated claims;
- good narrative, slide design, or editing;
- that an imported dependency is safe;
- that prompt-injected data cannot influence the agent's choices;
- that network calls are harmless;
- that a successful process exit means the artifact is valid;
- that the local Windows backend provides strong isolation in every configuration.

OSWorld's results are a useful warning: agents can still fail substantially on real computer tasks even when they have an interactive execution environment. The environment must therefore include domain-specific validators and reproducible final-state checks, not just a shell. [OSWorld](https://arxiv.org/abs/2404.07972)

### 9.7 How this changes the Sudarshan pipeline

The final architecture becomes:

```text
User request
  → Harness session and skill selection
  → Sudarshan request understanding + evidence bundle
  → typed plan/DAG
  → sandboxed artifact worker
      → generate IR/code
      → execute renderer/tools
      → observe previews/results
      → bounded repair
  → structural/evidence/policy/visual quality gates
  → human release approval when required
  → artifact store + manifest + safe Execution Monitor events
```

The sandbox should be a **worker capability**, not the overall agent brain. Harness controls the interactive lifecycle; Sudarshan controls policy and durable execution; sandboxed workers create and test candidates; validators control promotion.

### 9.8 Implementation priority

1. Add a sandbox capability probe and surface `full`/`partial` enforcement in health and run events.
2. Build one disposable artifact workspace per run/attempt with an explicit output directory.
3. Implement `render → inspect → repair` for PPT before video.
4. Add allow-listed renderer/validator commands and resource budgets.
5. Persist manifests, checksums, previews, validator reports, and sandbox facts.
6. Add fault-injection tests for path escape, symlink changes, timeouts, oversized output, renderer crash, partial artifact, and worker termination.
7. Only then expose sandbox-backed work as a reusable skill primitive across pipelines.

## 10. Who invokes what: skill, central agent, and specialized agents

### 10.1 The direct answer

In the current DeepSeek Harness design, a **skill does not run an agent**. A skill is a reusable instruction and resource package. The active Harness agent loads the skill through the skill tool or a user `/skill-name` gesture, receives the skill body, and then decides which visible tools to call. The Harness documentation explicitly separates the skill registry/loader from the agent loop and from the subagent capability.

Therefore the normal relationship is:

```text
Active Harness agent
  → loads presentation.case-brief skill
  → follows its policy and schemas
  → calls run_sudarshan / artifact tools
  → observes results and quality feedback
  → continues, repairs, or stops
```

The skill can instruct the active agent to delegate to a specialist, but the skill itself is not the process that performs delegation. If Sudarshan wants a truly executable skill, it should add a backend Skill Runtime around the Harness skill body:

```text
Skill package = instructions + manifest + tool allow-list + executor + validators
```

The instruction body guides the model; the manifest, executor, and validators enforce behavior in trusted code.

### 10.2 What the repository already implements

The Harness has three separate seams:

1. `dsh-skill` merges skill providers and loads one skill body on demand.
2. `dsh-tool-skill` exposes the catalog and the model-facing `skill` loader, or injects a skill when the user types `/name`.
3. `dsh-subagent` is an optional delegation capability. It supports multiple provider implementations, one-shot child agents, and continuable child sessions with ownership, depth, cancellation, and parent/child lifecycle.

This separation is a strength. It prevents every skill from spawning an invisible agent tree. See [Harness skill registry](../../deepseek-harness/packages/skill/skill/README.md), [Harness skill loader](../../deepseek-harness/packages/skill/tool-skill/README.md), and [Harness subagent seam](../../deepseek-harness/docs/subsystems/subagent.md).

Sudarshan currently has another important layer: the MCP tool calls the Python `SudarshanApplication`, which calls the LangGraph `PipelineOrchestrator`; selected pipelines then run their CrewAI/provider adapters. The current repository documentation deliberately says the Harness is the session/runtime layer, while Sudarshan owns routing, memory, pipelines, and providers. Keep this ownership boundary.

### 10.3 The three possible execution patterns

#### Pattern A: central agent → skill → direct tools

```text
User
  → Harness agent
  → load one skill
  → call typed Sudarshan MCP tool
  → backend runs deterministic/agentic pipeline
  → quality gate
  → artifact
```

This should be the default. Use it for executive summaries, PPT generation, infographic generation, and most video requests. It has the lowest token and coordination overhead, and the backend retains policy and audit authority.

#### Pattern B: central agent → skill → bounded specialized agents

```text
User
  → Harness agent loads skill
  → skill creates a bounded delegation plan
  → specialist child agents perform independent work
  → coordinator merges typed results
  → verifier checks the merged result
```

Use this only when the task benefits from genuinely independent context, parallel research, different tool permissions, or a long-running continuation. Examples include evidence analyst versus visual designer, or source investigator versus policy reviewer.

The child must return a typed result, not an open-ended conversation. Give each child a narrow tool filter, a maximum delegation depth, a token/time budget, and a clear completion contract.

#### Pattern C: skill package → backend executor

```text
User
  → Harness agent selects skill
  → Sudarshan Skill Runtime validates manifest
  → backend coordinator creates DAG
  → sandboxed workers execute tools/renderers
  → validators and quality gate
  → artifact promotion
```

This is the best pattern for production artifact generation. The model can plan and recover, but the backend owns concurrency, retries, approvals, idempotency, artifact storage, and release decisions.

### 10.4 Recommended Sudarshan flow

The recommended system is a hybrid of Pattern A, B, and C:

```text
1. Harness agent receives the request.
2. Harness skill catalog exposes only compact skill summaries.
3. Agent loads the selected skill body on demand.
4. A hierarchical skill router validates the candidate and chooses the skill version.
5. Agent calls `start_sudarshan_run` with the request and skill identity.
6. Sudarshan validates policy, evidence scope, output type, and budget.
7. Sudarshan creates a typed execution DAG.
8. Simple nodes use deterministic code or a single specialist pipeline.
9. Complex nodes may use CrewAI or a Harness child agent, but not both as competing orchestrators.
10. Independent nodes execute as durable background jobs.
11. Workers produce typed intermediate results and artifacts.
12. A verifier/quality gate checks evidence, schema, policy, and rendered output.
13. Failed nodes receive compact structured feedback and a bounded retry.
14. Approved artifacts are promoted and the run emits a safe completion event.
```

The central Harness agent should not manually call every slide-generation step or every video scene. It should submit the mission and observe the durable run. Otherwise the agent transcript becomes the scheduler, token use grows, and retries become difficult to recover.

### 10.5 What research suggests about single versus multi-agent

The most directly relevant recent paper, *When Single-Agent with Skills Replace Multi-Agent Systems and When They Fail*, argues that a multi-agent system can sometimes be compiled into one agent with a skill library. This can reduce inter-agent communication, tokens, and latency while retaining modular behaviors. Its warning is equally important: selection degrades sharply when skills become numerous or semantically confusable, and hierarchical routing helps. [Single-agent with skills](https://arxiv.org/abs/2601.04748)

SkillCraft evaluates higher-level compositions of atomic tools and reports substantial token savings from saving and reusing skills in its benchmark. This supports converting repeated pipeline sequences into reusable skills rather than asking a multi-agent team to rediscover the same procedure. [SkillCraft](https://arxiv.org/abs/2603.00718)

SkillRet finds that skill retrieval remains difficult on realistic large libraries, even with strong retrievers. Sudarshan should therefore use hierarchical metadata and top-k candidate retrieval rather than placing every full skill body in the Harness context. [SkillRet](https://arxiv.org/abs/2605.05726)

SkillX proposes a hierarchy of strategic plans, functional skills, and atomic skills, plus iterative refinement from execution feedback. This maps well to Sudarshan: a mission skill such as `case-brief` can compose functional skills such as `evidence-ledger`, `presentation-narrative`, and `visual-quality-check`, which in turn call atomic tools such as retrieval, rendering, and inspection. [SkillX](https://arxiv.org/abs/2604.04804)

Voyager provides the clearest lifecycle pattern: generate a procedure, execute it, use environment errors and self-verification, and commit it to the skill library only after success. Sudarshan should borrow the lifecycle, but replace unconstrained executable behavior with signed, reviewed, allow-listed skill packages. [Voyager](https://arxiv.org/abs/2305.16291)

The evidence therefore supports this rule:

```text
Use one coordinator by default.
Use specialized agents only for real decomposition.
Use backend workers for execution and artifacts.
Use skills as reusable policies and procedures.
Use validators before promoting a skill or artifact.
```

### 10.6 Which component should own each decision

| Decision | Owner | Reason |
|---|---|---|
| Which skill is relevant? | Harness agent + hierarchical Sudarshan router | Model understands intent; router enforces valid version and scope |
| What tools are allowed? | Skill manifest + backend policy | Must not depend on model obedience |
| Whether to delegate? | Skill policy and coordinator | Prevents arbitrary agent proliferation |
| Which child provider? | Harness subagent runtime / backend policy | Capability checks, depth, ownership, cancellation |
| Parallelism and retries? | Sudarshan durable scheduler | Models should not be production schedulers |
| How to render? | Pipeline/skill executor | Deterministic, versioned, reproducible |
| Whether output is good? | Structural/evidence/visual validators | External feedback is more reliable than self-approval |
| Whether output may be released? | Classification and human-approval policy | Safety and distribution control |
| What becomes a reusable skill? | Offline promotion process | Avoid unsafe or low-quality self-modification |

### 10.7 The exact recommendation for DeepSeek Harness

For Sudarshan 2.0, implement:

```text
Harness Agent
  ├── native skill catalog and on-demand loader
  ├── native MCP/tool lifecycle
  ├── optional bounded subagent delegation
  └── Execution Monitor UI

Sudarshan Skill Runtime
  ├── skill manifest/version/permissions
  ├── hierarchical skill router
  ├── typed plan/DAG compiler
  ├── evidence and memory policy
  └── quality/release policy

Sudarshan Execution Plane
  ├── LangGraph checkpoint/control logic
  ├── CrewAI inside selected specialist skills where useful
  ├── durable queue and worker leases
  ├── sandboxed renderers and artifact workers
  └── artifact/evidence/audit stores
```

Do not make the Harness central agent directly spawn a new child agent for every skill. Do not make every skill a CrewAI crew. Do not let LangGraph, CrewAI, and Harness all independently decide routing. One coordinator should own the plan; other agents and workers should execute bounded work under that plan.

### 10.8 Skill quality and trust gates

A skill is production-ready only when it has:

- a precise trigger and non-trigger condition;
- typed input/output contracts;
- required evidence and uncertainty rules;
- an allow-listed tool set;
- memory read/write scopes;
- budget, timeout, retry, and delegation-depth limits;
- structural, policy, and quality validators;
- evaluation fixtures and baseline metrics;
- owner, version, provenance, and rollback information;
- a security review before executable scripts or external network access.

This last point is essential. Recent empirical studies report substantial vulnerabilities in community agent skills, especially skills bundling executable scripts, including prompt injection, data exfiltration, privilege escalation, and supply-chain risks. Sudarshan skills should be treated as governed software packages, not harmless markdown. [Agent Skills in the Wild](https://arxiv.org/abs/2601.10338) and [Malicious Agent Skills in the Wild](https://arxiv.org/abs/2602.06547)

### 10.9 Final decision

For DeepSeek Harness, the best design is:

> The central Harness agent loads a skill. The skill supplies the operating policy and composition rules. The central agent invokes one Sudarshan execution tool. Sudarshan compiles the request into a typed DAG. Specialized agents are optional bounded workers inside that DAG. Sandboxed deterministic workers create and inspect artifacts. Validators and release policy decide whether the result reaches the user.

This gives Sudarshan the token efficiency of skill reuse, the flexibility of selective delegation, the reliability of backend-controlled execution, and the native Harness experience without turning the Harness transcript into an ungoverned multi-agent workflow.

## 11. MCP as the external Harness capability boundary

### 11.1 Does the MCP client provide Sudarshan tools to another Harness?

Yes, with precise terminology:

```text
Sudarshan MCP server  = publishes tools, resources, prompts, and progress
External Harness MCP client = connects and imports those capabilities
External Harness host/agent = decides when and how to use them
```

The MCP specification defines hosts as LLM applications, clients as connectors inside the host, and servers as services that provide context and capabilities. Servers expose tools, resources, and prompts; tools are model-controlled executable functions, resources are application-controlled context, and prompts are user-controlled templates. MCP itself does not decide the plan or guarantee that a model will use a tool correctly. [MCP specification](https://modelcontextprotocol.io/specification/2025-06-18/index)

The current repository already provides the server side. `sudarshan.cordis.yml` configures the DeepSeek Harness MCP client to launch the Python stdio server, and `mcp_server.py` exposes `run_sudarshan`, `get_sudarshan_status`, `resume_sudarshan`, `cancel_sudarshan`, health, pipeline discovery, and bounded memory tools. Any other MCP-capable Harness can connect to the same server if it supports the chosen transport and authentication boundary. [Sudarshan Harness overlay](../../integrations/deepseek_harness/sudarshan.cordis.yml) and [Sudarshan MCP server](../../integrations/deepseek_harness/mcp_server.py)

What does not automatically travel to another Harness is the DeepSeek-specific UI, skill catalog presentation, job cards, subagent UX, and profile composition. The external Harness receives the MCP contract; it does not automatically receive the full Sudarshan experience unless we provide equivalent MCP resources, prompts, and client-side adapters.

### 11.2 The two-level planning model

Use two planning levels, with a strict boundary:

```text
Level 1 — external Harness plan
  Understand the user's request
  Decide whether Sudarshan is relevant
  Select a high-level skill/capability
  Ask for missing information or approval
  Call the Sudarshan entry tool

Level 2 — Sudarshan execution plan
  Validate NTRO policy and classification
  Build the evidence bundle
  Compile a typed pipeline/skill DAG
  Admit parallel work
  Run CrewAI/provider/sandbox workers
  Validate, repair, approve, and promote artifacts
```

The external Harness should not recreate the internal DAG from prose. It should call one high-level operation and observe the durable run. Sudarshan should not assume the external Harness can understand internal provider details. This keeps the system portable and prevents two planners from fighting over the same execution.

### 11.3 Recommended MCP contract

Keep the current tools for compatibility, but add an asynchronous capability set:

```text
list_sudarshan_skills()
  → compact skill summaries, versions, triggers, required inputs

get_sudarshan_skill_contract(skill_id, version?)
  → typed inputs, outputs, permissions, estimated stages, approval rules

start_sudarshan_run(request, skill_id?, idempotency_key)
  → run_id, task_id, status=queued, accepted skill/version

get_sudarshan_status(run_id, cursor?)
  → safe durable projection, child summaries, artifacts, required action

wait_sudarshan(run_id, timeout_ms, cursor?)
  → completed/running/waiting snapshot; timeout does not cancel the run

resume_sudarshan(run_id, decision)
  → accepted clarification/approval/revision decision

cancel_sudarshan(run_id, reason)
  → cancellation requested and current state

get_sudarshan_artifact(artifact_id)
  → manifest or resource links, never raw credentials or private memory
```

`run_sudarshan` can remain as a foreground compatibility tool for short operations. Long PPT, video, and research work should use `start_sudarshan_run`; otherwise an external Harness may hold a request open while the backend performs provider calls and rendering.

MCP tools can return structured content and resource links. Use that to return an artifact manifest, preview links, and an evidence ledger instead of putting the entire artifact or long log in the model transcript. [MCP tools and structured/resource-linked results](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)

### 11.4 Exact external-Harness workflow

```text
1. External Harness initializes its MCP client connection.
2. Client negotiates capabilities and calls tools/list.
3. External agent sees compact Sudarshan tool schemas.
4. Agent calls list_sudarshan_skills or uses a configured skill hint.
5. Agent calls get_sudarshan_skill_contract for the selected skill.
6. Agent asks the user for missing required inputs if necessary.
7. Agent calls start_sudarshan_run with request, skill/version, and idempotency key.
8. Sudarshan validates the request and returns run_id immediately.
9. Sudarshan builds the internal DAG and schedules dependency-ready work.
10. External Harness calls wait_sudarshan or consumes progress notifications.
11. Sudarshan reports safe stage/child/artifact events.
12. If clarification or approval is needed, the Harness presents it to the user.
13. Harness calls resume_sudarshan; if the user cancels, it calls cancel_sudarshan.
14. Sudarshan renders and validates the artifact in its controlled workers.
15. The result returns as structured data plus resource links and manifest.
16. External Harness presents the artifact using its own UI.
```

The external Harness can therefore use Sudarshan without knowing whether the backend used LangGraph, CrewAI, a queue, a sandbox, or a future provider. That implementation detail stays behind the MCP boundary.

### 11.5 Progress and waiting

MCP supports optional progress notifications for long-running requests using a progress token. This is useful for live feedback, but it is not sufficient as the only durable run protocol: a notification stream can be disconnected, and a restarted client needs a replayable run projection. The MCP specification also includes cancellation and logging utilities. [MCP progress](https://modelcontextprotocol.io/specification/2025-03-26/basic/utilities/progress)

Use both mechanisms:

```text
MCP progress notifications = low-latency live hints
run_id + get_status/wait = durable truth and reconnect recovery
SSE/WebSocket dashboard = rich operator monitoring
```

Progress messages should contain stage, status, safe message, child id, percentage estimate, and artifact references. Never include raw memory, credentials, unrestricted model output, or chain-of-thought.

### 11.6 Why high-level Sudarshan tools are better than exposing every internal tool

Research on MCP-mediated agents supports exposing a focused server contract rather than flooding the external model with every pipeline and provider operation:

- MCP-AgentBench evaluates multi-server workflows and emphasizes end-to-end task success rather than exact tool-call traces. It finds that MCP agents must handle sequential dependencies and information synthesis, not merely isolated function calls. [MCP-AgentBench](https://ojs.aaai.org/index.php/AAAI/article/download/40347/44308)
- MCPAgentBench tests candidate tool lists containing distractors and measures tool selection and execution efficiency. Its results show that tool selection degrades as candidate tools increase, including for DeepSeek model configurations. [MCPAgentBench](https://arxiv.org/abs/2512.24565)
- ToolSandbox shows that agents frequently call dependent tools in parallel when order matters, hallucinate arguments under insufficient information, and need explicit intermediate milestones and forbidden-action checks. [ToolSandbox](https://arxiv.org/abs/2408.04682)
- MCPWorld demonstrates the value of programmatic verification of application state rather than judging only the agent's visible UI or text. [MCPWorld](https://arxiv.org/abs/2506.07672)

For Sudarshan, this means the external Harness should usually see a small number of high-value tools:

```text
start_sudarshan_run
get_sudarshan_status
wait_sudarshan
resume_sudarshan
cancel_sudarshan
get_sudarshan_artifact
```

Do not initially expose every internal `retrieve`, `render`, `compose`, `quality`, and provider operation to the external agent. Those operations belong inside the Sudarshan execution plan, where the backend can enforce ordering, permissions, budgets, and idempotency.

### 11.7 When to expose lower-level tools

Expose lower-level MCP tools only for an external Harness that is explicitly operating as a developer/operator or as a trusted specialist. Use separate tool profiles:

```text
user profile       high-level run/artifact/status tools
analyst profile    evidence retrieval and inspection tools
renderer profile   render/preview/validate tools
operator profile   status/resume/cancel/replay tools
developer profile  diagnostics, test, and sandbox tools
```

The Harness should receive only the profile appropriate to the session. This reduces tool confusion, context cost, accidental action, and permission risk.

### 11.8 MCP resources and prompts for Sudarshan

Tools are not the only useful protocol primitive:

- Resources can expose a run manifest, evidence ledger, quality report, artifact preview, or event cursor by URI.
- Prompts can expose user-controlled templates such as “create a case brief” or “revise this artifact,” while the backend still validates the request.
- Tools perform the state-changing actions: start, resume, cancel, approve, and promote.

This separation follows MCP's control model and allows an external Harness to browse context without granting write authority. Resource links in tool results are preferable to copying large JSON or binary content into the conversation.

### 11.9 Security and trust boundary

An external Harness is not automatically trusted because it speaks MCP. The MCP specification emphasizes user consent, access control, and caution around arbitrary tool execution. Tool descriptions and annotations must not be treated as a security policy by themselves. [MCP security principles](https://modelcontextprotocol.io/specification/2025-06-18/index)

Sudarshan must enforce on the server side:

- authenticated operator and case ownership;
- classification and distribution checks;
- server-side skill/version allow-list;
- idempotency and replay protection;
- per-tool and per-run budgets;
- approval for sensitive actions;
- no provider credentials in tool schemas or results;
- safe structured outputs only;
- audit logging of every state-changing tool call;
- capability profiles for external clients.

### 11.10 Final answer for the team

Yes: an external Harness can connect through its MCP client and use Sudarshan's tools. The external Harness owns user interaction and high-level planning. Sudarshan owns domain planning, durable execution, parallelism, memory, providers, sandboxed workers, quality gates, and artifacts.

The strongest product claim is not “any Harness automatically understands all Sudarshan workflows.” The accurate claim is:

> Sudarshan exposes a versioned, policy-controlled MCP capability layer. Any MCP-compatible Harness can discover and invoke its approved skills and execution tools; the DeepSeek Harness integration additionally provides native skill loading, session state, progress UI, subagent lifecycle, and operator experience.

That is genuinely portable and defensible. It also gives the team a clean migration path: keep the Sudarshan MCP server stable, add a native DeepSeek Harness client plugin for the best UX, and allow other MCP hosts to use the same backend contract.
