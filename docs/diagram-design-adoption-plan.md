# Diagram Design adoption plan

This plan turns the checked-out `diagram-design` reference into a native
Sudarshan capability. The reference is used for semantic routing, editorial
layout discipline, style profiles, import normalization, accessibility, and
visual verification. Sudarshan keeps ownership of evidence, skill execution,
budgets, cancellation, artifact lineage, approvals, and renderer selection.

Reference ledger: [diagram-design adaptation ledger](reference-adaptations/diagram-design.md)

## Target architecture

```text
Parent skill (PPT, infographic, video, LinkedIn, report)
        |
        v
Visual router
  - semantic pattern
  - visual type
  - audience
  - detail and size
        |
        v
DiagramIR v1
  - nodes, edges, groups
  - evidence/source bindings
  - style profile
  - accessibility
  - fidelity ledger
        |
        +--> native SVG/HTML renderer
        +--> PNG exporter
        +--> PPTX embed adapter
        +--> video-frame adapter
        +--> Mermaid/interchange exporter
        |
        v
Geometry + evidence + accessibility + visual QA
        |
        v
Immutable artifact, quality report, and frontend preview
```

`DiagramIR` is the semantic source of truth. HTML, SVG, PNG, Mermaid, PPTX,
and video frames are compiled targets. No child agent should regenerate the
same diagram separately for different destinations.

## Contract additions

Extend the existing `DiagramSpec` without breaking current callers:

```yaml
schema_version: "1"
diagram_id: diagram-...
semantic_pattern: null
visual_type: flowchart
audience: mixed
detail: balanced
format: svg
size_preset: slide-16x9
motion: none
nodes: []
edges: []
groups: []
evidence_ids: []
style_profile: ntro-default
accessibility:
  title: ...
  description: ...
fidelity_ledger: []
```

Compatibility rules:

- Existing `kind`, `direction`, nodes, edges, and style tokens remain valid.
- New fields have safe defaults.
- Evidence IDs are required for source-derived claims when the parent task has
  an evidence ledger.
- A child returns an immutable `DiagramIR` and `QualityReport`; the parent may
  reference it but must not mutate it in place.
- Motion is `none` unless the parent explicitly requests an approved mode.
- Renderer-specific source is never accepted as the only semantic output.

## Ticket plan

DD-1 and DD-2 are complete locally. They established the MIT adaptation
boundary and the current static SVG safety/accessibility checks. The current
implementation pass also completed the first local slice of DD-3, DD-6, and
the HTML/SVG, importer, and frontend-preview portions of DD-4, DD-5, and DD-9.
The remaining work is called out explicitly below rather than treated as
complete by documentation alone.

### DD-3 — Semantic diagram registry and deterministic routing

Owner: agentic/rendering. Depends on: DD-1, DD-2, T57.

Implement an allow-listed registry for semantic patterns and visual types.
Separate behavior from layout: for example, `secure_paved_road` may route to
`architecture`, while `paired_policy_traces` routes to `flowchart`.

Acceptance:

- Registry entries have stable IDs, descriptions, complexity budgets, and
  allowed output targets.
- Explicit user type wins over inference when it is compatible with policy.
- Ambiguous requests use a bounded clarification or a documented default.
- Routing is deterministic for the same request and policy inputs.
- Unsupported types fail as a typed routing error rather than silently falling
  back to a generic diagram.

### DD-4 — Safe output and export contracts

Owner: rendering/backend. Depends on: DD-3, T50.

Add artifact contracts for standalone HTML/SVG/PNG and embeddable PPTX/video
outputs. Use the same `DiagramIR` and renderer version in every artifact
manifest.

Acceptance:

- SVG and HTML contain no unapproved executable scripts or remote code.
- PNG is rendered from the approved visual source, not from a second layout.
- PPT and video adapters receive an immutable artifact reference.
- Artifact paths are workspace-contained and manifests include hashes,
  renderer version, style profile, and quality report ID.
- Export cancellation and timeout are cooperative and bounded.

Current slice: safe HTML/SVG export and artifact manifests are implemented in
`pipelines/diagram/export.py`. PNG rasterization and target-specific PPTX/video
promotion remain open because they require the shared browser/media export
boundary and visual regression fixtures.

### DD-5 — Sanitized import adapters

Owner: ingestion/rendering/security. Depends on: DD-3, DD-4, T48.

Add bounded Mermaid, Draw.io, and Excalidraw adapters. Parse each source into
typed intermediate data, apply the requested audience/detail/size policy, and
compile to `DiagramIR`. Do not execute imported HTML, JavaScript, or remote
assets.

Acceptance:

- Valid fixtures preserve node, edge, group, label, and source references.
- Adversarial fixtures cannot escape the workspace or execute code.
- Malformed input returns a structured partial/failure result with no silent
  data loss.
- Simplification produces a fidelity ledger describing merges and omissions.
- Imported Mermaid is an interchange source, never the final quality renderer.

Current slice: bounded basic Mermaid, Draw.io XML, and Excalidraw JSON adapters
are implemented in `pipelines/diagram/importers.py`. Compressed Draw.io payloads,
large-corpus fixtures, and broader adversarial coverage remain open.

### DD-6 — NTRO style profiles and contrast policy

Owner: rendering/frontend. Depends on: DD-3, T50.

Implement versioned semantic tokens and project-scoped profiles. Keep NTRO
defaults separate from any user/client profile.

Acceptance:

- Tokens use semantic roles such as `paper`, `ink`, `muted`, `accent`, and
  `link`, not scattered renderer-specific hex values.
- Contrast is checked before promotion, including bilingual labels.
- A profile records version, owner, source, and approval state.
- No external website or remote font is fetched without explicit policy.
- PPT, infographic, and standalone diagrams can share a profile safely.

Current slice: the versioned `ntro-default` semantic profile and WCAG AA
contrast checks are implemented in `pipelines/diagram/style.py`. Persistent
client profiles and marker-first resolution remain open.

### DD-7 — Geometry, density, bilingual, and visual regression gates

Owner: rendering/evaluation. Depends on: DD-4, DD-6, T50.

Add deterministic structural checks and rendered-image checks based on the
reference’s geometry-first philosophy.

Acceptance:

- Checks cover node/edge budgets, label length, overlap, crossings, connector
  attachment, safe areas, clipping, and canvas bounds.
- Accessibility checks require a title, description, stable IDs, and a valid
  accessible name.
- Text-size and contrast thresholds vary by output size preset.
- Golden fixtures cover flowchart, architecture, mind map, sequence, timeline,
  and one imported diagram.
- A failed check returns a targeted repair issue such as
  `diagram.edge-crossing` instead of replaying the complete run.

Current slice: the existing native flowchart structural/SVG gates are reused by
the new export path. Browser screenshot regression, full connector geometry,
and bilingual golden fixtures remain open.

### DD-8 — Optional motion with a pinned controller

Owner: frontend/rendering/security. Depends on: DD-4, DD-7.

Keep static output as the default. If motion is requested, allow only reviewed
`reveal`, `step`, or `loop` modes through one pinned controller and preserve a
complete static first frame.

Acceptance:

- Reduced-motion output is complete and hides or disables playback controls.
- No arbitrary inline script, external asset, or executable HTML attribute is
  accepted.
- Motion has a bounded duration and a deterministic frame/state contract.
- Static and motion artifacts share the same `DiagramIR` and evidence map.

### DD-9 — Frontend, plugin, MCP, and A2A delivery boundary

Owner: frontend/backend/harness. Depends on: DD-4, DD-7, T45, T49, T51.

Expose preview, export, quality diagnostics, fidelity notes, and approval
through the existing frontend/plugin and MCP/A2A contracts.

Acceptance:

- The frontend receives projections and artifact references, never credentials
  or hidden model reasoning.
- Users can preview the diagram, inspect evidence and omissions, request a
  bounded repair, and approve an export.
- MCP/A2A clients observe the same run, artifact, quality, and approval states
  as the native Harness.
- Reconnect, wait, cancel, and retry preserve the same run identity.
- Export remains a separate side-effecting action behind approval where
  required.

Current slice: `frontend/diagram/preview.js` provides an isolated safe preview
boundary for `diagram` and `visual.flowchart` artifact projections. Edit,
approval, and MCP/A2A diagram-specific projections remain open.

## Execution order

```text
DD-3 semantic registry
   |
   +--> DD-4 export contracts ----+
   |                              |
   +--> DD-6 style profiles ------+--> DD-7 visual QA --> DD-9 delivery
   |
   +--> DD-5 import adapters

DD-7 --> DD-8 optional motion
```

Recommended implementation slices:

1. Extend contracts and add registry fixtures without changing the current
   flowchart renderer.
2. Add deterministic routing and compile one `DiagramIR` to native SVG and
   PPTX.
3. Add size/audience/detail budgets and fidelity reporting.
4. Add style profiles and contrast checks.
5. Add geometry and screenshot regression gates.
6. Add import adapters one at a time, starting with Mermaid.
7. Add frontend preview/repair/approval projections.
8. Evaluate motion only after static quality is stable.

## Parallel team split

### Agentic/Harness

- DD-3 registry and routing.
- `DiagramIR` versioning and child-skill contracts.
- Evidence inheritance, child budgets, cancellation, and typed repairs.

### Backend/platform

- DD-4 artifact/export manifests.
- Workspace containment, hashes, renderer versions, and lifecycle events.
- MCP/A2A projections and approval state.

### Rendering/evaluation

- Native SVG/HTML/PPT/video adapters.
- DD-6 style compiler.
- DD-7 geometry, accessibility, and screenshot gates.

### Frontend/plugin

- Preview and artifact workspace.
- Evidence and fidelity drawers.
- Repair, export, approval, reconnect, and wait states.

### Security/release

- Import fuzz fixtures and sandbox policy.
- Remote asset/font policy.
- License/provenance ledger and promotion sign-off.

## Cross-skill demonstration

The first end-to-end acceptance demo should be:

```text
User: Create a PPT explaining the Sudarshan pipeline and include an architecture diagram.
  -> presentation planner creates DeckPlan and evidence bindings
  -> visual router selects architecture + slide-16x9 + mixed audience
  -> diagram skill returns DiagramIR, SVG, evidence map, and quality report
  -> PPT skill embeds the immutable diagram artifact
  -> PPT renderer produces preview and editable PPTX from the same layout source
  -> visual QA checks the slide and diagram together
  -> frontend shows artifact, evidence, fidelity, and internal logs
```

The same `DiagramIR` should then be reused in an infographic and a LinkedIn
visual without asking an agent to redraw it.

## Metrics and release gates

Track per run:

- correct semantic-type selection;
- evidence coverage for nodes and edges;
- percentage of diagrams within complexity budget;
- overflow, clipping, crossing, and contrast failure rates;
- import fidelity and number of omitted/merged source elements;
- repair success rate and repair token cost;
- cache hit rate by IR, profile, and renderer version;
- P50/P95 render latency and queue wait;
- human approval and correction time.

Do not claim that the reference makes Sudarshan more capable until a matched
baseline shows improvement in visual quality, groundedness, latency, or repair
cost.

## Non-goals and assumptions

- No second scheduler, agent runtime, or memory database.
- No full reference editor or plugin marketplace is copied.
- Cognee remains the governed retrieval/memory backend; it does not become the
  visual source of truth.
- Mermaid remains useful for interchange but is not the quality renderer.
- Static diagrams are the MVP; motion is optional and later.
- A production browser/renderer sandbox, approved fonts, and the final NTRO
  visual acceptance owner still need deployment confirmation.
