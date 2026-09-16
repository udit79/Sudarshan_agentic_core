# OpenViking adaptation ledger

**Audit date:** 2026-09-16
**Reference:** `C:\Users\uditj\Downloads\sudarshan\references\OpenViking`
**Source classification:** executable AGPL-3.0 context database/service plus a
VikingBot integration.

## Source truth

The repository contains a substantial memory subsystem under
`openviking/session/memory/`. It includes memory schemas, isolation, lineage,
graph views, patch/replace/sum/link merge operations, streaming updates,
trajectory extraction, and experience extraction. The
`AgentTrajectoryContextProvider` extracts trajectories from archived
conversations; `AgentExperienceContextProvider` searches bounded candidate
experiences, includes a few source trajectories as grounding, and decides
whether to update, replace, create, or skip.

The VikingBot integration documents a real loop:

```text
recall → execute → feedback → consolidate → recall
```

It separates Resources, Peer/User Memories, Skills, Sessions, and Experiences.
Recall is bounded by type quotas and character budgets, with degradation from
full content to summary or URI. Session synchronization tracks local indexes,
pending tokens, commit indexes, errors, and recent-turn retention. Trusted
request identity includes account/user/agent/actor-peer/role/namespace;
workspace IDs do not replace authentication.

The repository also contains local file and workspace fallbacks such as
`MEMORY.md` and `HISTORY.md`. Those are a degradation path in VikingBot, not
the authoritative OpenViking memory model.

## Adopt in Sudarshan as contracts

- keep L0/L1/L2 progressive context, explicit `context_uri`, and bounded
  degradation;
- isolate memory by tenant, case, user, agent, and actor where applicable;
- record extraction lineage from trajectory → summary → memory/experience;
- use patch/merge semantics for case-memory updates instead of blind append;
- expose trajectory and memory projections to the UI without making them the
  scheduler or source of truth;
- commit long-term memory only when policy or the user explicitly authorizes
  it.

## Do not add

- OpenViking as a second memory store while Cognee is the product backend;
- the AGPL source or a linked derivative in the MIT Sudarshan distribution;
- a virtual filesystem, FUSE mount, or full VikingBot integration merely to
  obtain progressive context;
- untrusted client-supplied identity fields;
- silent fallback from authenticated memory to another tenant or workspace.

## Current mapping

Sudarshan already has `ContextPack`, stage-specific context policy, source
references, retrieval traces, lifecycle events, and bounded memory access.
The remaining useful work is measured case-memory extraction/merge quality and
trajectory projection—not importing OpenViking.

## Source locations checked

- `openviking/session/memory/core.py`
- `openviking/session/memory/agent_trajectory_context_provider.py`
- `openviking/session/memory/agent_experience_context_provider.py`
- `bot/docs/en/concepts/04-openviking-integration.md`
- repository `LICENSE` and component license files
