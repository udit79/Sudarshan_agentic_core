# Sudarshan 2.0 assumptions and deployment checklist

This file is a living risk register for assumptions made while implementing
the execution plan. Each assumption must be confirmed, changed, or retired
before production deployment. Coding agents should add a new ID instead of
silently changing a public contract.

| ID | Assumption today | Evidence / scope | Deployment action | Status |
|---|---|---|---|---|
| AS-01 | SQLite queue, DAG store, progress store, and LangGraph checkpoints are single-instance local stores. | Current implementation uses local SQLite paths under `artifacts/.state/`. | Replace or front them with a shared broker/database and define ownership, backup, failover, and migration procedures before multi-host workers. | Open |
| AS-02 | Python threads cannot be forcibly stopped. | Scheduler and child runtime use cooperative events, network timeouts, and killable subprocess boundaries. | Require every provider adapter to observe cancellation and bound network/process work; add provider-specific watchdog tests. | Open |
| AS-03 | Skill discovery can contain skills that are not executable in the current deployment. | `visual.flowchart` is catalogued but currently reports `available=false`. | Gate UI/Harness selection on availability and register the executable adapter before enabling the skill. | Open |
| AS-04 | The scheduler stores only safe typed skill references, not model output or raw memory. | `skill_result_json` is limited to `SkillResult`-style references. | Verify retention, access control, artifact lineage, and recovery behavior for result references. | Open |
| AS-05 | MCP schema compatibility tests are local; a live external Harness/MCP client has not yet completed the full lifecycle. | T12 local adapter and schema tests pass. | Run a staging test with the actual Harness client, reconnect, cancellation, artifact download, and an independent MCP client. | Open |
| AS-06 | Provider usage may be unavailable or estimated for some model/media adapters. | `UsageRecord.is_estimate` exists and gateway counts are not billing truth. | Require provider-normalized usage where available and label estimates in operator dashboards and promotion gates. | Open |
| AS-07 | Runtime secrets are supplied through deployment configuration, not committed files. | `.env` is ignored and has not been edited by this work. | Use a secret manager, rotation policy, least-privilege service accounts, and secret-scan gates. | Open |
| AS-08 | Classification and distribution policy values are valid at every boundary. | `AdvisoryRequest` and NTRO policy validators enforce the current values. | Confirm the production classification taxonomy, cross-case rules, retention, and external-agent restrictions with the security owner. | Open |
| AS-09 | Local artifact paths are available to the current process. | Artifact manifests expose stable URIs while local development uses filesystem storage. | Use durable object storage, immutable versioning, checksum verification, signed access, and disaster recovery before distributed deployment. | Open |
| AS-10 | In-process child concurrency counters are sufficient for one runtime instance. | `SkillRuntime` limits active children per parent in memory. | Move concurrency reservations to the shared budget/queue control plane for multi-process execution. | Open |
| AS-11 | A successful quality verdict requires deterministic validators in addition to model critics. | The plan requires schema, evidence, render, media, and visual gates. | Define release thresholds and matched legacy-versus-staged evaluations for every artifact class. | Open |
| AS-12 | The current skill catalog version is `1.0.0` for the first canonical adapters. | Catalog manifests define explicit versions and legacy aliases. | Freeze compatibility policy, migration rules, deprecation dates, and signed manifest distribution. | Open |
| AS-13 | The first budget ledger is process-local and child-skill scoped. | `BudgetController` is wired into `SkillRuntime` and exposes safe counters through MCP. | Persist reservations/usage and coordinate them across workers before allowing multi-process child execution or treating counters as billing truth. | Open |
| AS-14 | The first artifact cache is process-local SQLite and exact-match only; cache hits are permitted only after an explicit `quality_status=passed` result. | `CacheStore` fingerprints skill/version, contract, input refs, tool/provider versions, model policy, and authorization scope; it stores artifact references and quality metadata, not raw prompts or memory. | Move cache coordination to shared durable storage for multi-host deployment, define tenant/case namespaces and invalidation events, and measure false-hit/stale-hit rates before enabling semantic reuse. | Open |
| AS-15 | Packaged skill resources use a validated folder contract and JSON manifests; full instruction bodies/resources are loaded only after selection. | `skills/` contains versioned manifests, `SKILL.md`, schemas, policies, failure cases, and smoke eval fixtures; the Harness catalog consumes these manifests with legacy fallback. | Add signed package distribution, owner/version compatibility rules, schema migration policy, resource integrity checks, and a reviewed install path for user-created skills before production enablement. | Open |
| AS-16 | The first presentation IR is renderer-neutral but is not yet the renderer or visual QA source of truth. | `pipelines/ppt/schemas.py` now validates deck plans, slide content, visuals, evidence bindings, normalized bounds, and targeted repair patches while preserving `PresentationOutput`. | Connect IR conversion to the PPT/SVG renderers, add slide image rendering and visual regression gates, and define migration/round-trip rules before switching production deck generation. | Open |
| AS-17 | The staged PPT flow is opt-in and still converts its typed plan into the legacy `PresentationOutput` delivery contract. | `SUDARSHAN_PPT_FLOW=staged` adds grounding, deck planning, visual routing, slide content, and quality tasks; legacy mode remains the default and both paths use CrewAI callbacks. | Run matched legacy/staged evaluations, connect `DeckPlan` to real child-skill execution and renderers, then promote the staged flag only after quality, cost, and latency thresholds pass. | Open |

## Update rule

At the end of each implementation ticket, update this file if a new
assumption, resolved risk, or deployment dependency was discovered. An
assumption is not considered resolved merely because a local unit test passes;
it is resolved only when the deployment action has evidence from staging or
production-like infrastructure.
