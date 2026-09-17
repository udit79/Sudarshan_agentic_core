# Agent documentation

This is the short machine-facing index. It is intentionally separate from the
human architecture and operations documents. Read the root
[agent map](../../AGENT_MAP.md) first; use this page to choose the smallest
runtime source set for a change.

## Status and truth

- [Current status](../current-status.md) — what is implemented, partial, or
  release-gated.
- [Code-truth notes](../../DEEPSEEK_CODE_TRUTH_NOTES.md) — source/test-based
  findings for DeepSeek, timeouts, memory, PPT, DAG, fallbacks, and
  overengineering. It is an audit note, not an architecture authority.
- [Assumption ledger](../sudarshan-2.0-assumptions.md) — unresolved deployment
  assumptions and evidence requirements.
- [Tools, prompts, and Cognee map audit](tools-and-prompts-audit.md) — source-
  backed audit of the internal MCP surface, pipeline prompts, and the safe
  graph-projection plan.
- [Next execution plan](../next-plan.md) — active NP-01–NP-19 tickets derived
  from the source audit.
- [Reference adaptation ledgers](../reference-adaptations/README.md) — source-
  backed truth for every local reference checkout, adoption boundaries,
  fallbacks, rendering paths, and licenses.

## Code ownership

| Change | Read first | Authority |
| --- | --- | --- |
| request routing and lifecycle | `pipelines/orchestrator/graph.py`, `understanding.py` | LangGraph/application boundary |
| child handoff and parallel work | `pipelines/orchestrator/contracts.py`, `skill_runtime.py`, `cross_skill.py` | typed skill contracts |
| durable queue/DAG | `api/scheduler.py`, `api/dag_scheduler.py`, `pipelines/orchestrator/dag.py` | scheduler state, not UI trajectory |
| memory | `memory/`, `pipelines/common/memory_tools.py` | `MemoryManager` and `AccessContext` |
| providers and model configuration | `integrations/providers/` | provider adapters/router |
| artifacts and quality | `api/artifacts.py`, pipeline `quality.py`/`repair.py` | manifest, validator, receipt |
| Harness/MCP/A2A | `integrations/deepseek_harness/` | application boundary; no second orchestrator |

## Change rules

1. Preserve `run_id`, `attempt_id`, `node_id`, `child_id`, and artifact lineage.
2. Put hard constraints in typed validation and post-generation quality gates;
   prompts alone are not enforcement.
3. Keep local and A2A execution behind the same `ChildTaskSpec` and
   `SkillResult` contract.
4. Make retries, fallbacks, degradation, and uncertainty visible in receipts.
5. Add a focused regression test before calling a behavior fixed.
6. Do not copy reference code without checking `THIRD_PARTY_NOTICES.md`.

## Human documentation

Use the [human documentation index](../human/README.md) for architecture,
operations, integration, rendering, and reference material. Do not duplicate
those explanations in agent instructions.
