# AntV Infographic adaptation ledger

Status: native SSR boundary hardened locally. This ledger applies to the
checked-out reference at `C:\Users\uditj\Downloads\sudarshan\references\infographic`.

## License boundary

The reference is MIT licensed. Sudarshan uses the pinned `@antv/infographic`
runtime through its own small Node SSR bridge; it does not copy the reference
editor, site, skill marketplace, or task/runtime layer into the application.

## Adopted concepts and modules

| Capability | Sudarshan implementation | Adoption boundary |
|---|---|---|
| Declarative infographic syntax | `InfographicOutput` and `InfographicIR` | Syntax is generated from typed, evidence-backed contracts only |
| High-quality SVG SSR | `pipelines/infographic/antv_renderer` | Node receives validated syntax and bounded render settings only |
| Templates and structure selection | Current syntax prompts and normalization | Future template registry must be allow-listed and versioned |
| Themes and design tokens | NTRO prompt guardrails and `InfographicIR.style_tokens` | Future theme packs must be sanitized and evidence-neutral |
| Editor/export ecosystem | Not copied | Add only through an explicit frontend/plugin ticket |

## Deliberately not copied

- The reference editor, site, and browser state
- Its AI skill installation/marketplace workflow
- Unbounded syntax or arbitrary JavaScript execution
- Reference project orchestration or provider configuration

## Review rule

Every future adaptation must add a row here, retain the upstream license notice
when code is copied, add a focused regression test, and pass Sudarshan's
evidence, budget, cancellation, provenance, and SVG quality gates.
