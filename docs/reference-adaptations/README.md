# Reference adaptation ledgers

These are source-first notes for the repositories under
`C:\Users\uditj\Downloads\sudarshan\references`. They are decision records,
not runtime instructions and not substitutes for the code. The reference
checkouts are read-only inputs; Sudarshan owns its contracts, scheduler,
security policy, memory gateway, and artifact quality gates.

| Reference | What it actually is | Ledger |
| --- | --- | --- |
| agentmemory | Large Apache-2.0 coding-agent memory runtime with MCP, hooks, viewer, and an `iii-engine` worker | [agentmemory](agentmemory.md) |
| OpenViking | AGPL-3.0 context database/service with memory extraction, progressive context, and VikingBot integration | [OpenViking](openviking.md) |
| diagram-design | MIT skill/reference pack with static HTML/SVG specimens and stdlib validators | [diagram-design](diagram-design.md) |
| AntV Infographic | MIT TypeScript infographic renderer/runtime with templates, themes, resource loaders, editor, and SVG/PNG export | [AntV Infographic](antv-infographic.md) |
| ppt-master | MIT routed presentation skill package with SVG↔PPTX tooling and native round-trip editing | [ppt-master](ppt-master.md) |
| MoneyPrinterTurbo | MIT video application with WebUI/API/CLI, provider adapters, task state, material cache, and FFmpeg composition | [MoneyPrinterTurbo](moneyprinterturbo.md) |
| linkedin-skills | MIT LinkedIn skill/reference pack with optional Apify helpers and draft/publish procedures | [linkedin-skills](linkedin-skills.md) |
| MiniMax-H3 | MiniMax Community-Licensed model/VAE code, examples, and Hub-only prompt skills; not a complete video agent | [MiniMax-H3](minimax-h3.md) |

## How to use these notes

- Read the ledger before copying code, assets, prompts, or workflows.
- Treat “adopt” as a contract or test idea to reimplement, not permission to
  copy source.
- Treat “avoid” as an identified coupling, fallback, credential boundary, or
  feature surface that would make Sudarshan less portable or less safe.
- Verify every claim against the referenced checkout and then against current
  Sudarshan code before changing behavior.

The legal summary is centralized in
[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
