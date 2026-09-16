# MiniMax-H3 reference audit

**Reviewed:** 2026-09-16  
**Reference:** `C:\Users\uditj\Downloads\sudarshan\references\MiniMax-H3`  
**Checkout:** commit `d21241f`  
**Status:** reference-only; the checkout was not modified and no model weights
or upstream source were copied into Sudarshan.

## Corrected classification

MiniMax-H3 is not itself a complete video-maker agent or a MoneyPrinterTurbo-
style application. The checked-out repository contains:

- model/configuration indexes and large checkpoint components;
- 48 Python files implementing transformer/VAE/model support, split between
  `FL2VA/` and `Ref2VA/`;
- 18 shell examples for local SGLang and hosted API requests;
- 9 prompt/production skills, of which only `h3-prompt-writing` is declared
  portable to a generic agent;
- example MP4/GIF/PNG assets;
- no application database, case store, memory manager, agent scheduler, or
  generic MCP/A2A server.

The previous reference audit treated the repository too much like an agent
runtime. The accurate adoption target is a provider/model adapter plus selected
prompt-planning ideas. The Hub canvas workflows are product-specific workflow
instructions, not portable runtime code.

## What actually renders video

### Local H3-Base path

The repository documents two task-specific model families:

- `FL2VA`: text-to-audio-video and first/last-frame-to-audio-video;
- `Ref2VA`: multimodal reference-to-audio-video using images, videos, and/or
  audio.

The model indexes connect processors/tokenizers, Qwen3-VL text encoding, video
VAE, audio VAE, transformer, and schedulers. The README describes a 33B dense
Omni Transformer, BF16 inference, 24 FPS output, 32 kHz stereo audio, and
4–15-second clips. The initial open release uses full attention; sparse
attention is described but not included.

The documented local render operation is an external SGLang server:

```text
POST http://localhost:30010/v1/videos       # FL2VA
POST http://localhost:30011/v1/videos       # Ref2VA
GET  /v1/videos/{id}                         # status
GET  /v1/videos/{id}/content                 # MP4 content
```

The shell examples submit a request, capture a provider video ID, query status,
and download the MP4. They do not implement durable polling, cancellation,
leases, retries, idempotency, artifact manifests, quality gates, or case
ownership. The comments say to query again, but the examples themselves perform
one status query rather than a production polling loop.

### Hosted Context-IR and 2K path

The documented quality path is a multi-stage provider workflow:

```text
user multimodal input
  -> hosted H3-Context-IR
  -> expanded structured prompt
  -> local H3-Base 768p render
  -> hosted H3-Regenerate-2K with the 768p video as base input
  -> downloadable 2K result
```

`H3-Context-IR` is explicitly not open-sourced. It performs instruction
parsing, cross-modal association, temporal understanding, and reasoning. The
repository provides API examples, not the implementation. `H3-Regenerate-2K`
is also explicitly not open-sourced; it is an in-context regeneration service,
not a conventional upscaler.

The API examples use task IDs and query endpoints, but they do not provide a
Sudarshan-compatible job record. The provider task ID must therefore remain a
child-provider identity under a Sudarshan `run_id` / `node_id` / `attempt_id`,
never become the application’s only identity.

### Agent/Hub production path

The eight style-specific skills describe Hub-native canvas workflows with
choice cards, canvas nodes, approval gates, `hub_generate_image`,
`hub_generate_video`, audio tools, and `hub_video_edit`. They can plan a
multi-shot film and assembly, but those tools are not present in this
repository and are explicitly marked non-portable in the skill metadata.

Useful ideas are the staged creative brief, anchor assets, shot table, user
approval, per-shot generation, latest-approved-asset rule, assembly, and final
review. They must be re-expressed using Sudarshan contracts rather than copied
as if Hub were available.

## Rendering comparison with Sudarshan and MoneyPrinterTurbo

| Concern | MiniMax-H3 reference | Sudarshan today | Adoption decision |
| --- | --- | --- | --- |
| Generation unit | one 4–15s native audiovisual model job | per-scene package with local/native or legacy provider path | add an H3 provider adapter at scene level |
| Multi-shot film | Hub skills plan shots and assemble them; model/API examples do not | `VideoPackage`, scene manifests, timeline, FFmpeg composition | keep Sudarshan assembly authoritative |
| Audio | H3 jointly generates stereo audio/video; 32 kHz | native TTS/BGM/FFmpeg path; legacy provider may return media | expose native-audio mode explicitly; do not silently duplicate BGM |
| 2K | separate hosted regeneration stage from 768p base | no H3 regeneration stage | model it as a dependent child job, not a renderer fallback |
| Status | provider task ID and status endpoint | durable run/node/scene state and progress | wrap provider IDs inside durable manifests |
| Retry | examples have no production retry policy; skills suggest creative retry ladders | scene fingerprints, bounded workers, cancellation, quality reports | use deterministic retry limits and record every attempt |
| Quality | README examples and human/reference outputs | `inspect_video`, manifest, FFmpeg/ffprobe checks | add codec/audio/frame/duration checks for H3 results |
| Memory | no case/user/task memory implementation found | `MemoryManager` + Cognee + local store + access policy | H3 receives a bounded context pack only |
| Orchestration | SGLang/API/Hub-specific | Sudarshan scheduler/DAG/trajectory | do not move orchestration into the provider |

This makes H3 a potentially strong provider, not a replacement for the
MoneyPrinter-compatible renderer architecture. H3 can improve native video
quality and native sound, while Sudarshan remains responsible for lifecycle,
scope, artifacts, retries, and delivery.

## Memory and context audit

I scanned the checkout’s source, shell examples, model indexes, and all skill
instructions for memory/state concepts. There is no implementation of:

- Cognee, vector search, graph memory, case memory, or user memory;
- `run_id`, `case_id`, task ownership, access context, retention, or redaction;
- a database, checkpoint store, durable job ledger, or memory write-back;
- a generic agent context manager or retrieval tool.

The only relevant uses are ordinary model concepts such as cached AdaLN
parameters, gradient checkpointing compatibility, prompt “memory sentence”
language in a creative skill, and provider task IDs. None is an application
memory system.

The safe Sudarshan integration is:

```text
MemoryManager / AccessContext
  -> bounded ContextPack with provenance and classification
  -> H3 prompt planner or H3-Context-IR input
  -> provider task
  -> video artifact + quality receipt
  -> optional approved summary write-back through MemoryManager
```

Do not send an entire Cognee graph or raw case memory into H3. Pass only the
facts, evidence references, visual anchors, timeline constraints, and
uncertainty that the current shot needs. Never let H3-generated prompt text
become trusted memory without provenance, confidence, and an explicit write-back
policy.

## Prompt audit

### Strong parts worth adopting

- The portable `h3-prompt-writing` skill separates T2VA, I2VA, FL2VA, L2VA,
  and Ref2VA modes.
- It preserves exact field names and section order such as
  `integrated_multimodal_description`, `overall_soundscape`, and
  `non_diegetic_music`.
- Reference mode uses subject definitions and retention analysis, which is a
  useful input to a typed reference-anchor plan.
- The creative skills insist on approvals before expensive generation,
  consistent style/identity anchors, shot timing, and final cleanup.

### Problems to avoid

- Hub-only skills promise canvas nodes and tools unavailable in a generic
  runtime. They must be capability-checked and downgraded to a plan/package,
  not claimed as generated output.
- Choice-card approvals are UI behavior, not authorization by themselves.
  Sudarshan must persist approval and bind it to the run, revision, and artifact
  fingerprint.
- Prompt instructions such as “preserve identity,” “make text readable,” and
  “match timing” are not deterministic validation. H3 output still needs
  media inspection and an explicit human-quality gate for important results.
- Creative fallback ladders can become expensive overengineering: strengthened
  prompt, shorter shot, alternate model, and re-planning should be bounded by
  policy and surfaced as separate attempts. Never silently switch a model or
  alter duration.
- Some skills are long, repetitive, and opinionated about a specific Hub UI.
  Do not inject all of them into every H3 call. Store them as versioned
  capability-specific guidance and compile only the active mode’s rules.

## Proposed Sudarshan H3 adapter

Do not import the H3 checkpoint repository into the application process first.
The scalable path is an external H3 worker/provider:

1. Add a provider adapter with `submit`, `status`, `download`, and `cancel`
   capabilities. Start with SGLang or the MiniMax API; do not support both in
   one untyped branch.
2. Compile a `VideoScene` plus authorized anchors/context into a mode-specific
   H3 request. Keep prompt planning separate from provider transport.
3. Persist provider task ID, mode, model revision, request hash, source asset
   IDs, attempt ID, and expected duration/ratio before submission.
4. Poll asynchronously under the existing scheduler. A provider timeout means
   “unknown/pending and reconcile,” not “submit again.”
5. Download to a temporary object, verify the file, compute a checksum, and
   publish only a validated `VideoAsset`/`ArtifactManifest`.
6. For 2K, represent regeneration as a dependent child node whose input is the
   validated 768p artifact. It is not a generic fallback.
7. Keep per-scene manifests and final FFmpeg assembly so one failed scene does
   not regenerate the entire film.
8. Emit trajectory events for provider submit, queued, running, download,
   validation, retry, and terminal state. Redact prompts and provider URLs.

Suggested provider options, subject to contract review:

```text
h3_mode: t2va | i2va | fl2va | l2va | ref2va
h3_endpoint_kind: sglang | minimax_api
h3_model_revision: explicit revision, never implicit latest
h3_generate_audio: true/false
h3_resolution: 768P | 2K
h3_regenerate_from_artifact_id: optional validated base artifact
```

The current `VideoScene` contract needs an explicit provider metadata area or
an H3-specific typed options model; do not put arbitrary H3 JSON into the
general `provider_options` dictionary without validation.

## Overengineering and fallback audit

- `delete:` Do not add an H3-specific scheduler; reuse Sudarshan’s scheduler
  and child-run contracts. [`api/scheduler.py`, `pipelines/orchestrator/`]
- `yagni:` Do not embed 33B H3 weights into the web/API process; run a separate
  GPU worker and use the provider adapter. [`references/MiniMax-H3/model_index.json`]
- `shrink:` Keep one mode compiler plus typed mode policies rather than nine
  separate H3 transport implementations. [`skills/h3-prompt-writing/SKILL.md`]
- `delete:` Do not copy Hub-only canvas/choice-card instructions into runtime
  code. Implement equivalent approval state in Sudarshan only where the
  product actually needs it. [`skills/*/SKILL.md`]
- `yagni:` Do not introduce an H3 memory database; pass bounded ContextPacks to
  the existing memory boundary. [`memory/`, `pipelines/common/memory_tools.py`]
- `shrink:` Treat hosted Context-IR and 2K regeneration as typed provider
  stages, not as generic model fallbacks hidden in a renderer. [`scripts/readme/`]

## License and asset boundary

The README links to the **MiniMax H3 Community License Agreement**. This is not
an MIT reference. The checked-out directory has no local license file, so the
linked upstream license must be retrieved and reviewed before copying any
source, skill text, model configuration, or asset. Model weights and example
media must not be redistributed under Sudarshan’s MIT license.

This project therefore records H3 as a consulted reference/provider target,
not as vendored code. See `THIRD_PARTY_NOTICES.md` for the repository-level
boundary.

## Evidence files

- Reference README: `references/MiniMax-H3/README.md`
- Model graph: `references/MiniMax-H3/model_index.json`,
  `references/MiniMax-H3/FL2VA/model_index.json`,
  `references/MiniMax-H3/Ref2VA/model_index.json`
- Local request examples: `references/MiniMax-H3/scripts/readme/`
- Portable prompt skill: `references/MiniMax-H3/skills/h3-prompt-writing/`
- Hub-only workflows: `references/MiniMax-H3/skills/*/SKILL.md`
- Current native video contracts: `pipelines/video/contracts.py`,
  `pipelines/video/native_generator.py`, `pipelines/video/quality.py`
- Current legacy boundary: `integrations/providers/moneyprinterturbo/client.py`
