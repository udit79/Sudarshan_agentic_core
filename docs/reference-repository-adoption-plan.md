# Reference-repository adoption plan

This plan extracts proven patterns from the local reference repositories without
coupling Sudarshan to their runtimes or copying incompatible license models.

License notices are centralized in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).
The source-first per-repository notes are indexed in
[reference-adaptations/README.md](reference-adaptations/README.md).
The references do not share one license: diagram-design, AntV Infographic,
linkedin-skills, MoneyPrinterTurbo, and ppt-master are MIT; agentmemory is
Apache-2.0; and the main OpenViking repository is AGPL-3.0. A design idea is
not a source-code license grant. Any future copied code or asset needs its own
notice and review.

## Decisions

| Reference | Sudarshan adoption | Boundary |
| --- | --- | --- |
| agentmemory | Lifecycle events, lessons, hybrid recall evaluation, project/session scope | Cognee remains the semantic backend; do not import its 54-tool coding-agent runtime |
| OpenViking | L0/L1/L2 context selection, retrieval trajectory, workspace identity | Reimplement contracts; do not copy AGPLv3 code |
| diagram-design | Semantic visual types, style profiles, complexity budget, self-checker | Native SVG/PPTX adapters own delivery |
| AntV Infographic | Typed templates, resource/font loaders, SSR/export lifecycle | Node renderer stays behind a Python adapter |
| ppt-master | Routed workflows, page jobs, style profiles, Plan → Do → Check → Act | Use the concepts, not the whole workflow package |
| linkedin-skills | Narrow skills, humanizer report, draft-only approval | NTRO evidence and release policy override marketing rules |
| MoneyPrinterTurbo | Video timeline, material matching, subtitles, scene-level retry/cache | Native Sudarshan video renderer remains default; all fallbacks stay explicit |
| MiniMax-H3 | External audiovisual provider candidate and prompt/reference ideas | Community License boundary; no model weights/source/assets copied; H3 is not a scheduler or memory agent |

## Tickets

### T54 — Hierarchical context selection

Status: implemented locally; focused/offline tests pass. Full-suite promotion
still has an environment-sensitive AntV timeout and is not represented as
green until that run is reproduced and explained.

- Support optional L0/L1/L2 context layers in retrieved memory.
- Select the layer by stage policy and preserve the selected level in the
  `ContextPack` and retrieval trace.
- Treat legacy content as L2 so existing memory remains compatible.
- Add tests for selected layers and safe fallback.

Implementation: `memory/context_builder.py` and `memory/memory_manager.py`.
Stage defaults are understanding=L1, grounding=L2, visual=L1, quality=L1,
and delivery=L0. The selected level and fallback count are exposed through the
bounded context trace and `ContextPack`.

### T55 — Skill reference and resource policy

Status: implemented locally; pilot manifest enabled for `visual.flowchart`.

- Add manifest declarations for context policy, reference load order, renderers,
  and checkers.
- Load references lazily with package-bound path validation and character/token
  limits.
- Add explicit prompt-layer ownership: skill craft in `SKILL.md`, enforcement in
  code/checkers, examples in references.

Implementation: `SkillPackage.load_text()` validates package boundaries and
supports bounded lazy loading. `SkillManifest` now carries context policy,
reference, renderer, and checker metadata with backwards-compatible defaults.

### T56 — Shared renderer registry

Status: implemented locally; existing adapters are represented without provider imports.

- Define one small renderer capability record: `render`, `export`, `inspect`,
  `fallback`, and version.
- Register the existing native SVG, AntV, PPTX, and FFmpeg adapters.
- Keep renderer failures explicit and promote artifacts only after inspection.

Implementation: `pipelines/common/renderers.py` and the shared visual-QA gate.
The registry currently describes native SVG, editable PPTX, AntV/native SVG,
and FFmpeg capabilities with explicit fallback IDs.

### T57 — Diagram skill family

Status: implemented locally; semantic planning pilot is available.

- Add diagram type selection and semantic patterns for flowchart, sequence,
  swimlane, architecture, timeline, state, dependency, and mind-map outputs.
- Port the reference self-checker principles: accessibility, local assets,
  connector validity, complexity limits, and no unsafe scripts.

Implementation: `pipelines/diagram/family.py` supports all eight diagram kinds,
keyword/requested-type selection, complexity/disconnected-node checks, and
compilation to the existing native graph renderer.

### T58 — Presentation quality workflow

Status: implemented locally; PPT flow records the quality report.

- Add slide-level page jobs, relationships, evidence bindings, and style profile.
- Run render → inspect → repair before delivery.
- Preserve editable PPTX objects; never use a full-slide screenshot as the final
  presentation surface.

Implementation: `pipelines/ppt/presentation_quality.py` creates ordered
slide jobs, carries evidence IDs, enforces density, and runs the shared PPTX
integrity gate after rendering. Repair recommendations remain targeted rather
than regenerating the whole deck.

### T59 — Video timeline and asset ledger

Status: implemented locally; native video manifests now include the ledger.

- Introduce a provider-neutral timeline IR.
- Track scene assets, source provenance, subtitles, narration, and fallbacks.
- Cache and retry scenes independently; compose only immutable verified assets.

Implementation: `pipelines/video/timeline.py` records clips, source/material
references, verified files, and fallback reasons. `NativeVideoGenerator` stores
the timeline beside the resumable scene manifest.

### T60 — Memory lifecycle and evaluation

Status: implemented locally; offline evaluation and safe lifecycle events are available.

- Capture safe run/decision/lesson/correction events.
- Add importance, confidence, supersession, expiration, and forget semantics.
- Benchmark token usage, retrieval recall, evidence faithfulness, and latency.

Implementation: `memory/lifecycle.py`, `memory/evaluation.py`, and
`MemoryManager` now record content-free lifecycle events, importance,
confidence, expiry, supersession, retract/forget transitions, and evaluation
metrics. Cognee remains the retrieval backend.

## Execution order

```text
T54 → T55 → T56
              ├── T57
              ├── T58
              └── T59
T54 → T60
```

## Guardrails

- No new scheduler: LangGraph/application services remain the lifecycle source
  of truth.
- No direct model access from renderers.
- No raw prompts, full source documents, or provider payloads in safe dashboard
  events.
- No reference code is copied until its license and security boundary are
  reviewed.
- Every ticket must add a focused regression test and run the full suite before
  promotion.
