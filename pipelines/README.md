# Sudarshan pipelines

These application-specific pipelines turn person-provided case information
plus permitted memory into controlled outputs. The advisory pipeline produces
a formal case advisory for authorized review. The LinkedIn and executive-
summary pipelines return validated drafts; the frontend owns preview, editing,
and upload. The infographic pipeline produces validated AntV syntax and an SVG
artifact. None of these pipelines is a cybersecurity generator, and none
claims to represent an official NTRO template or classified operating
procedure.

## Ownership boundary

```text
MemoryManager.recall(User/Case bounded context)
             -> RequestUnderstandingAgent
             -> MemoryManager.recall(User/Case/Task context)
             -> PromptCrafterAgent -> CrewAI specialist crew
             -> Pydantic output + QualityReview
             -> optional artifact renderer
             -> MemoryManager.remember() [case only after validation/approval]
             -> DeepSeek harness/application handoff
```

The available flows are:

- `AdvisoryFlow`: quality review, human approval, formal Markdown artifact,
  then Case-memory write-back.
- `LinkedInPostFlow`: quality review, validated post returned to the frontend;
  no direct LinkedIn upload. It reads explicit image instructions from the
  user query and otherwise lets the writer decide whether a visual improves
  the post. OpenAI image generation is optional.
- `ExecutiveSummaryFlow`: quality review, validated summary returned to the
  frontend.
- `InfographicFlow`: quality review, validated AntV syntax, SVG rendering, and
  Case-memory write-back. The frontend receives the SVG artifact path and may
  preview, edit, or upload it.
- `PresentationFlow`: quality review and native `.pptx` rendering. The public
  `ppt` route is a compatibility alias for `presentation`.
- `VideoPipeline`: CrewAI evidence/script/storyboard/critic planning followed
  by native OpenAI image/TTS and local FFmpeg rendering, or explicit
  MoneyPrinterTurbo compatibility mode.

Updates to an existing output are modeled as revisions. The frontend creates a
new task with `operation="revise"`, a `parent_artifact_id` or `parent_run_id`,
the user's `revision_instruction`, and an optional `revision_scope`. The old
artifact is never overwritten; the new result goes through the same validation
and approval policy.

For the central LangGraph router, backend/frontend event contract, approval
resume flow, and Harness boundary, see
[`docs/internal/pipeline-orchestration.md`](../docs/internal/pipeline-orchestration.md).

When the central router is used, a small User/Case memory context is recalled
before request understanding. Once one or more pipelines are selected, a
second recall uses the permitted User/Case/Task scopes and the bounded result
is passed into each child flow's CrewAI tasks. Calling a flow directly remains supported
for compatibility; in that mode the flow performs its own scoped recall.

For multi-pipeline requests, the coordinator creates a typed collaboration
plan containing each pipeline's capability proposal, shared constraints,
declared dependencies, and execution waves. Pipelines can receive validated
upstream results only when a dependency is explicitly declared. This is
bounded coordination, not unrestricted LLM-to-LLM chat, and it adds no model
call by default.

The frontend can stop a run through the orchestrator's cancellation endpoint.
Cancellation is cooperative: active graph boundaries observe it, record a
Task-memory cancellation event, and return status `cancelled`. A provider call
already executing may finish before the worker observes the cancellation.

## Video package contract

The video pipeline accepts an optional `metadata.video_package` object. It can
contain the complete transcript, validated script, ordered storyboard scenes,
visual terms, and provider options. If no package is supplied, the video CrewAI
planning crew creates and reviews the story, script, and storyboard from the
bounded memory context before media rendering begins.

The default native path uses OpenAI for script planning, scene images, and TTS;
local FFmpeg writes a durable package under `artifacts/videos/<run_id>/`:
`script.txt`, `storyboard.json`, `images/scene_*.png`, `audio/scene_*.mp3`,
`segments/scene_*.mp4`, `final.mp4`, `manifest.json`, and the final MP4. The DeepSeek Harness
only calls the application boundary and never calls OpenAI, Cognee, or the
native renderer directly.

`MONEYPRINTERTURBO_BASE_URL` is an explicit compatibility mode for deployments
that still operate the upstream asynchronous worker contract. It is not used
when blank, and it is not required for the native OpenAI/local path.

Example metadata payload:

```json
{
  "video_package": {
    "subject": "Case briefing",
    "transcript": "The bounded source transcript...",
    "storyboard": [
      {
        "scene_id": "scene-1",
        "narration": "Verified opening statement.",
        "visual_description": "A restrained briefing room.",
        "duration_seconds": 5
      }
    ],
    "video_terms": ["briefing room", "document review"]
  }
}
```

The router supports fan-out requests such as `Create outputs A and B`. It runs
registered adapters concurrently, gives every child its own task/run identity,
and returns `result.responses` keyed by pipeline. A later revision should send
only the selected pipeline and its `parent_artifact_id`; sibling artifacts are
not re-run or overwritten. Any new output adapter can be registered through
the central plugin contract.

CrewAI agents receive a scoped recall tool and injected bounded context. They
do not receive Cognee credentials or a Cognee client. Task lifecycle output is
written automatically as task-scoped memory by CrewAI task callbacks. Failed
and incomplete runs remain visible in Task memory.

## Required request fields

Every run requires `user_id`, `case_id`, and `task_id`. The task ID is not
optional because it is the audit boundary for agent execution.

```python
from pipelines import AdvisoryFlow, AdvisoryRequest
from memory import MemoryManager

request = AdvisoryRequest(
    query="Assess the reported case information and recommend next actions",
    user_id="operator-1",
    case_id="case-1",
    task_id="task-1",
)
result = AdvisoryFlow(MemoryManager.from_env()).run(request)
```

Configure the OpenAI-backed CrewAI model tiers through `CREWAI_MODEL` and
`CREWAI_FAST_MODEL`, with optional per-role overrides. Flow checkpoints are stored at
`CREWAI_FLOW_DB_PATH` (default `artifacts/.state/flow_states.db`) so pending
human approvals and retries are application-owned and durable. No API key is
read or printed by the pipeline package. `CREWAI_DISABLE_TELEMETRY=true` is the
safe default for case-sensitive deployments; enable CrewAI telemetry only if
your deployment explicitly permits it.

## Human approval and advisory artifact handoff

The quality critic must approve the structured advisory before the Flow opens
the human release gate. The gate can produce `approved`, `rejected`, or
`needs_revision`:

- `approved`: renders a formal Markdown advisory in `artifacts/advisories/` and
  writes the approved artifact to Case memory.
- `rejected`: produces no artifact and keeps the decision visible in Task
  memory.
- `needs_revision`: produces no artifact; the run remains incomplete with the
  review feedback available for a controlled retry or application-side
  revision flow.

## LinkedIn image option

The LinkedIn pipeline accepts `metadata={"linkedin_image": {"requested": True}}`
to force an image or `requested=False` to disable one. If omitted, the user
query is inspected: explicit image/visual language forces an image, explicit
no-image language disables it, and otherwise the writer decides. The result
includes image type, alt text, and a case-grounded generation prompt. An
OpenAI image adapter can turn that prompt into an asset URI; without it, the
frontend receives the prompt fallback.

Set `OPENAI_API_KEY` and optionally `OPENAI_IMAGE_MODEL`. The adapter defaults
to `gpt-image-1` and writes returned base64 image data to
`artifacts/linkedin/images/`.

## Infographic renderer setup

The root setup command installs AntV Infographic as a deterministic
syntax-to-SVG renderer. If setting up manually, install its pinned Node
dependency from this directory:

```bash
cd pipelines/infographic/antv_renderer
npm install
```

`InfographicFlow` owns memory recall, CrewAI syntax generation, validation, and
provenance. The Node bridge owns only AntV SSR rendering. It does not receive
Cognee credentials or raw unvalidated agent output.
