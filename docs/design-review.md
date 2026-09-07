# Design review of the SIH presentation

The supplied presentation assets are included in the root README for project
context. This review separates visual communication improvements from the
implemented software contract. The diagrams should be updated before a final
jury/demo presentation so they do not imply behavior the repository does not
perform.

## Image 1 — title page

### Keep

- SIH 2026 identity, problem statement number, team name, and Sudarshan
  branding.
- The simple title-page hierarchy.

### Improve

- Fill the missing Team ID.
- Use one exact problem title consistently: “Gen-AI Platform for Automated
  Content Transformation.”
- Add a one-line value proposition below the title: “One bounded case source
  transformed into validated advisory, summary, social, infographic,
  presentation, and video artefacts.”
- Reduce competing logos and decorative mascot scale so the problem statement
  remains the visual focus.
- Add a small “Adversarial Brains” credit line and the Figma board link only on
  a final credits/reference slide, not on the title page.

## Image 2 — proposed solution

### Keep

- The input, orchestration, memory, and output story.
- The emphasis on reducing repeated manual transformation work.

### Improve

- Replace “appropriate process” with concrete language: “understands intent,
  validates constraints, selects pipelines, and coordinates execution.”
- Show the actual order: request understanding -> pipeline router -> bounded
  memory recall -> structured prompt plan -> selected pipelines. The current
  slide can be read as prompt enhancement deciding the pipeline.
- Separate the three memory scopes visibly: User memory, Case memory, and Task
  memory.
- Name the result as “validated artefacts with provenance and progress state,”
  not just “communication artefacts.”
- Add the human approval boundary for advisory output and the provider-pending
  state for asynchronous video compatibility mode.

## Image 3 — technical approach and memory

### Keep

- The User/Case/Task memory explanation.
- The visual separation between agent framework, memory, and pipelines.

### Improve for implementation accuracy

- The current diagram names LangChain, LangGraph, and CrewAI. The implemented
  control plane is LangGraph; CrewAI runs specialist pipeline agents. Do not
  imply LangChain is a separate runtime dependency unless it is intentionally
  added.
- Replace generic “DeepSeek Harness” center text with “Harness session/runtime
  boundary -> SudarshanApplication -> LangGraph.” The Harness does not call
  Cognee or native renderers directly.
- Label Cognee as the memory backend and separately label MongoDB Atlas as the
  Node gateway database. MongoDB is not the Cognee memory layer.
- Do not show Postgres/Redis as implemented defaults. The repository currently
  uses SQLite state stores locally and expects approved durable shared stores in
  production.
- Change “Pipelines powered by DeepSeek Harness plugins” to “Sudarshan
  pipelines behind the application boundary.” The Harness supplies session,
  tool, and runtime integration; it does not implement the pipelines.
- Add a quality gate after every pipeline and show that only validated outputs
  write back to Case memory.

## Image 4 — system architecture

### Highest-priority correction

The top sequence currently places prompt enhancement before pipeline routing.
That is misleading for the implemented system.

Use this order:

1. User request or source upload.
2. Request-understanding agent.
3. Pipeline router.
4. User/Case/Task memory resolver.
5. Context assembly.
6. Structured prompt plan.
7. Pipeline fan-out or dependency waves.
8. CrewAI pipeline agents and quality gates.
9. Artifact renderer/provider adapter.
10. Safe result, progress events, and validated memory write-back.

### Additional improvements

- Replace “Memory Resolver” with the concrete MemoryManager boundary.
- Show the two recalls: bounded User/Case recall before understanding and
  task-oriented User/Case/Task recall after routing.
- Show LangGraph as the lifecycle/control-plane owner around routing, retries,
  checkpoints, cancellation, and resume.
- Show DeepSeek Harness entering through MCP/application boundary rather than
  above the router.
- Add explicit result states: succeeded, partial, failed, pending,
  waiting_for_input, waiting_for_approval, and cancelled.
- Show the video package as script + storyboard + scene assets + manifest +
  final MP4; show PPT as native PPTX and infographic as validated AntV/SVG.

## Image 5 — feasibility and viability

### Keep

- Modular, integrable, AI-powered, scalable framing.
- The separation between challenges and mitigations.

### Improve factual precision

- Replace “DeepSeek/LLMs handle reasoning” with “OpenAI model adapters handle
  generation; DeepSeek Harness provides session/tool/runtime integration.”
- State that model calls are bounded by typed schemas, quality gates, retry
  budgets, memory policy, and audit events.
- Replace “existing open-source pipelines” with “native and adapter-backed
  pipelines behind a common PipelineAdapter contract.”
- Add deployment dependencies: MongoDB Atlas for the gateway, Cognee for
  memory, OpenAI for model/media calls, and a durable shared checkpointer for
  multi-instance production.
- Add a clear “offline tests are not live provider validation” caveat.
- Replace “failure and scalability” with measurable controls: bounded retries,
  isolated child task IDs, cooperative cancellation, idempotency keys, and
  parent/child fan-in.

## Image 6 — impact and benefits

### Keep

- One source of information to multiple delivery formats.
- Productivity, reach, resource efficiency, and scalability themes.

### Improve evidence quality

- Avoid numerical improvement claims unless a benchmark is recorded.
- Use measurable evaluation metrics in the slide: source-grounding rate,
  schema-validation rate, critic rejection rate, average latency by pipeline,
  artifact completion rate, and operator edit distance.
- Distinguish generated drafts from approved deliverables.
- State that public outputs such as LinkedIn posts remain drafts and are not
  automatically published.
- State that advisory output has a human approval seam.
- Include classification-aware delivery and provenance as impact dimensions,
  not only speed and cost.

## Image 7 — research and references

### Keep

- DeepSeek Harness, Cognee, NIST AI RMF, memory research, and Figma references.

### Improve

- Use stable, direct URLs and meaningful link labels in the actual slide.
- Add access dates or version identifiers for fast-changing software projects.
- Add references for LangGraph, CrewAI, OpenAI model/media APIs, AntV
  Infographic, imageio-ffmpeg, FastAPI, and MongoDB Atlas if they are shown in
  the architecture.
- Separate “technical dependency” references from “research/background”
  references.
- Replace an unqualified research link with the paper title, authors, year,
  and one sentence explaining which design decision it supports.
- Keep the FigmaJam link as the design artifact reference, not as a technical
  runtime dependency.

## Shared presentation improvements

- Use one vocabulary throughout: artifact, pipeline, memory scope, quality
  gate, provider pending, and human approval.
- Fix spacing and capitalization variations such as “PPT Master,” “AntV
  Infographic,” “Case memory,” and “Task memory.”
- Add a small legend for solid arrows, dashed compatibility paths, memory
  reads, memory writes, and user-action interrupts.
- Avoid drawing every implementation component on every slide. Use the title
  and solution slides for value, the technical slides for contracts, and the
  feasibility slide for deployment realities.
- Make the architecture diagram match the code and keep the README architecture
  diagram synchronized with it.

