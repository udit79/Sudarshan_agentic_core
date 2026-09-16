# Sudarshan Agentic Core

<p align="center">
  <img src="https://img.shields.io/badge/Smart%20India%20Hackathon-2026-ff6b00?style=flat-square" alt="Smart India Hackathon 2026">
  <img src="https://img.shields.io/badge/Problem%20Statement-SIH26154-2457a6?style=flat-square" alt="SIH26154">
  <img src="https://img.shields.io/badge/Adversarial%20Brains-6f42c1?style=flat-square" alt="Adversarial Brains">
</p>
<p align="center">
  <img src="https://img.shields.io/badge/Python-3.13%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.13 or newer">
  <img src="https://img.shields.io/badge/Node.js-22%2B-339933?style=flat-square&logo=nodedotjs&logoColor=white" alt="Node.js 22 or newer">
  <img src="https://img.shields.io/badge/FastAPI-API-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/LangGraph-Control%20Plane-1f6feb?style=flat-square" alt="LangGraph control plane">
  <img src="https://img.shields.io/badge/CrewAI-Pipeline%20Workers-6f42c1?style=flat-square" alt="CrewAI pipeline workers">
  <img src="https://img.shields.io/badge/OpenAI-Provider-412991?style=flat-square&logo=openai&logoColor=white" alt="OpenAI provider">
</p>

Sudarshan is a governed, case-grounded agent platform. It ingests source
material, builds bounded User/Case/Task context, routes requests to typed
pipelines, validates outputs, and returns classified artifacts with progress
and audit metadata.

This repository is a local/release-candidate implementation for the Smart
India Hackathon 2026 NTRO problem statement SIH26154. It is not an official
NTRO system and must not be connected to classified production data without
approved identity, storage, network, security, and operating controls.

## Project status

The Python application boundary, LangGraph orchestrator, memory policy,
specialist pipelines, quality gates, artifacts, scheduler, telemetry, and
DeepSeek Harness/MCP integration form a tested local vertical slice.

Production readiness is still open for distributed workers, shared durable
storage, sandboxing, live provider/Cognee smoke tests, visual approval,
real-corpus benchmarks, backup/restore, and release sign-off. See
[current status](docs/current-status.md) for the authoritative readiness view.

## Pipelines

| Route | Output | Honest status |
| --- | --- | --- |
| `advisory` | Reviewed case advisory | Local implementation |
| `executive_summary` | Evidence-linked summary | Local implementation |
| `linkedin_post` | Humanized draft and optional image | Draft-only by design |
| `presentation` | Native PPTX deck | Native local path with exact-count, theme, editability, manifest, and post-render gates; PowerPoint/LibreOffice visual smoke remains environment-dependent |
| `infographic` | AntV syntax and SVG | Native/fallback local implementation with structural safety and degraded-mode gates; browser visual regression remains a release gate |
| `video` | Storyboard, media bundle, and MP4 | Native local path; provider/codec production gates remain |
| `visual_flowchart` | Typed SVG/PPTX child artifact | Child capability, not a standalone diagram agent |

`ppt` is a legacy alias for `presentation`. The semantic diagram package is
available as a typed library and child capability; it is not currently a
separate top-level registry route.

## Architecture

```text
Gateway / Harness / API
          -> SudarshanApplication
          -> LangGraph lifecycle and routing
          -> bounded memory recall through MemoryManager
          -> typed pipeline or child skill execution
          -> schema + deterministic quality gates
          -> artifact manifest, safe events, and approved memory write-back
```

LangGraph/application services own routing, lifecycle, retries, checkpoints,
parallel fan-out, cancellation, budgets, and delivery policy. CrewAI is the
specialist collaboration layer inside pipelines. MemoryManager is the only
Cognee boundary. The Harness is a client, not the scheduler or source of
truth. Local child handoffs and future remote A2A handoffs use the same typed
contracts.

## Quick start

Requirements: Windows PowerShell 7, Python 3.13+, Node.js, and configured
service credentials for any live provider you intend to use.

```powershell
Copy-Item .env.example .env
# edit .env; never commit it
pwsh -NoProfile -ExecutionPolicy Bypass -File .\startup.ps1
```

Default local services:

| Service | URL |
| --- | --- |
| FastAPI | http://127.0.0.1:8000 |
| Node gateway | http://127.0.0.1:8080 |
| Frontend | http://127.0.0.1:3000 |

Stop them with:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\stop-servers.ps1
```

Use [operations](docs/operations.md) for configuration, deployment, and
troubleshooting details.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp .pytest-tmp-current

Push-Location backend-node
npm test
npm run check
Pop-Location
```

The latest local Python run passed 500 tests with 8 skips. This does not prove
live MongoDB, Cognee, OpenAI, AntV SSR, external worker, or multi-host
behavior.

## Where to work

| Need | Start here |
| --- | --- |
| Agent navigation and ownership | [AGENT_MAP.md](AGENT_MAP.md) |
| Human documentation index | [docs/README.md](docs/README.md) |
| Current implementation/readiness | [docs/current-status.md](docs/current-status.md) |
| Active tickets and release gates | [docs/next-plan.md](docs/next-plan.md) |
| Request lifecycle and orchestration | [docs/internal/pipeline-orchestration.md](docs/internal/pipeline-orchestration.md) |
| Pipeline contracts and quality | [pipelines/README.md](pipelines/README.md) |
| Pipeline benchmarking | [docs/pipeline-benchmarking.md](docs/pipeline-benchmarking.md) |
| Runtime/Cognee tracing | [docs/pipeline-observability.md](docs/pipeline-observability.md) |
| Memory and Cognee boundary | [memory/README.md](memory/README.md) |
| Harness/MCP boundary | [integrations/deepseek_harness/README.md](integrations/deepseek_harness/README.md) |
| Skill and agent authoring | [docs/skill-authoring.md](docs/skill-authoring.md) |
| Reference adoption and licenses | [docs/reference-adaptations/README.md](docs/reference-adaptations/README.md), [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) |

## Development rules

- Keep routing, authorization, budgets, memory scope, quality, and artifact
  ownership in Sudarshan; do not move them into a provider or Harness plugin.
- Do not call Cognee or provider SDKs directly from agents.
- Preserve typed evidence, artifact, lineage, attempt, and progress contracts.
- Add deterministic tests for success, invalid output, timeout, cancellation,
  duplicate admission, unauthorized scope, and degraded/fallback results.
- Treat passing unit tests as local evidence, not production certification.
- Keep reference repositories and their licenses separate from runtime code.

## License

Sudarshan code is MIT licensed; see [LICENSE](LICENSE). Vendored and external
references retain their own licenses. Review [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
before copying code, prompts, assets, or models.
