# Sudarshan agent map

This file is the agent-facing navigation map. Human/developer explanations
live under `docs/human/`; the short agent index lives under `docs/agent/`. This
file tells an agent which runtime owner and source files to inspect before
changing behavior.

## Start here

1. Read `README.md` for product scope, boundaries, and commands.
2. Read `docs/current-status.md` for implemented versus release-gated work.
3. Read `docs/internal/pipeline-orchestration.md` for the request graph.
4. Read `docs/skill-authoring.md` before adding a skill or child capability.
5. Read `docs/sudarshan-2.0-assumptions.md` before changing a contract or
   interpreting an unfinished ticket.
6. Check `git status --short` and preserve unrelated user changes.
7. Use `docs/agent/README.md` for the compact status/code/change checklist;
   use `docs/human/README.md` only when architecture or operations context is
   needed.
8. For the internal tool, prompt, and Cognee-map audit, read
   `docs/agent/tools-and-prompts-audit.md` before changing the Harness surface.
9. For external reference repositories, read
   `docs/reference-adaptations/README.md` and the specific ledger before using
   a reference pattern, prompt, asset, or code.

## Runtime ownership map

| Agent or responsibility | Source of truth | Inspect first | Do not put here |
| --- | --- | --- | --- |
| Orchestrator / supervisor | `integrations/deepseek_harness/application.py` and `pipelines/orchestrator/graph.py` | `pipelines/orchestrator/` | provider-specific rendering or raw memory access |
| Request understanding | `pipelines/orchestrator/understanding.py` | `RequestUnderstanding`, `PromptPlan`, validators | authorization or artifact side effects |
| Memory agent/tools | `memory/` and `pipelines/common/memory_tools.py` | `memory/memory_manager.py`, `memory/context_builder.py` | direct Cognee calls from pipelines |
| Pipeline agents | `pipelines/<name>/` and `skills/` | pipeline `crew.py`, `schemas.py`, skill manifest | credentials, unrestricted tools, hidden fallback behavior |
| Child-agent handoff | `pipelines/orchestrator/contracts.py` and `skill_runtime.py` | `ChildTaskSpec`, `SkillResult`, `SkillManifest` | nested prompt transcripts or direct public-run recursion |
| Parallel execution | `pipelines/orchestrator/cross_skill.py`, `graph.py`, `dag.py` | dependency waves, budgets, leases | unbounded threads or fake completion percentages |
| Durable execution graph | `pipelines/orchestrator/dag.py`, `api/dag_scheduler.py` | node states, dependencies, retries, repairs | UI trajectory as state authority |
| A2A boundary | `integrations/deepseek_harness/a2a.py` | agent card, task/status/cancel mapping | a second scheduler or memory store |
| MCP boundary | `integrations/deepseek_harness/mcp_server.py` | allow-listed profiles and safe projections | provider keys, raw memory, raw filesystem paths |
| Harness adapter | `integrations/deepseek_harness/` and `deepseek-harness/` | `README.md`, `sudarshan.cordis.yml` | pipeline ownership or policy duplication |
| Trajectory projection | Harness session events plus Sudarshan progress events | `pipelines/orchestrator/progress.py`, Harness trajectory plugin | raw prompts, secrets, unrestricted tool arguments |
| Artifacts and quality | `pipelines/common/renderers.py`, `api/artifacts.py`, pipeline quality modules | manifests, checksums, validators, receipts | returning unvalidated output as success |
| PPT agent | `pipelines/ppt/` and `integrations/providers/pptmaster/` | `schemas.py`, `repair.py`, `ppt_master_adapter.py` | full-deck rebuild for a one-slide update |
| Infographic agent | `pipelines/infographic/` | `ir.py`, `normalization.py`, `quality.py`, AntV bridge | arbitrary syntax or unvalidated SVG |
| Diagram agent | `pipelines/diagram/` | `family.py`, `style.py`, `export.py` | unsafe HTML/SVG or style-token bypass |
| Video agent | `pipelines/video/` and `integrations/providers/moneyprinterturbo/` | contracts, planner, timeline, native generator | silent provider changes or unrecorded degradation |
| Gateway/frontend | `backend-node/`, `landing page/`, `chakra-app/` | route contracts and projections | making the browser the security boundary |

## Request and handoff flow

```text
user / client
  -> API, MCP, or A2A boundary
  -> idempotent run admission
  -> request understanding + scoped memory
  -> orchestrator selects pipeline agent(s)
  -> typed ChildTaskSpec handoffs
  -> local adapter or remote A2A agent
  -> dependency waves / bounded parallelism
  -> artifact + quality validation
  -> case-memory write-back when approved
  -> safe response, DAG state, progress, trajectory events
```

Example: a Presentation Agent needing a visual submits a typed child request
for `infographic` or `visual.flowchart`. The orchestrator checks capability,
case scope, budget, dependencies, idempotency, and side effects. The child
returns artifact IDs and a quality receipt. The parent consumes the artifact;
it does not read another agent's private memory or credentials.

## Local versus remote agents

Every child should use the same `ChildTaskSpec` / `SkillResult` contract whether
it runs through a local Python adapter or a remote A2A agent. Keep local calls
for same-process work. Use A2A for an independent deployment, process,
security boundary, or reusable specialist. Harness is one client of this
orchestrator; it is not required by the pipeline agents.

## Parallel-work visibility

One parent run may contain many child lanes. The status/API/trajectory
projection should preserve each child’s `child_id`, dependency state,
attempt/retry, progress, artifact, quality, usage, wait reason, and terminal
status. Show them as nested child cards or lanes. Never collapse parallel work
into one synthetic “agent is working” message.

## Safe change checklist

- Find the owning boundary before editing.
- Reuse existing typed contracts before adding a new abstraction.
- Preserve `run_id`, `attempt_id`, `node_id`, `child_id`, `artifact_id`, and
  event sequence/correlation fields.
- Keep hard constraints in schemas/validators, not only prompts.
- Make retries and fallbacks explicit in status and receipts.
- Do not expose prompts, raw memory, credentials, or hidden reasoning in safe
  events.
- Add or update a focused test and the relevant documentation.
- If reference code or assets are copied, update `THIRD_PARTY_NOTICES.md` and
  the relevant `docs/reference-adaptations/` ledger.

## Documentation split

- Human/developer architecture and operations: `docs/human/` and the detailed
  documents linked from it
- Compact agent status/code/change guidance: `docs/agent/`
- Agent navigation and ownership: `AGENT_MAP.md`
- Product skill instructions: `skills/<skill>/SKILL.md`
- Runtime skill contracts: `pipelines/orchestrator/contracts.py`
- Reference audit: `docs/reference-architecture-audit.md` and the separate
  Codex audit bundle when that external bundle is available
