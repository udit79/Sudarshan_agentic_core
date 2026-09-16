# AntV Infographic adaptation ledger

**Audit date:** 2026-09-16
**Reference:** `C:\Users\uditj\Downloads\sudarshan\references\infographic`
**Source classification:** MIT TypeScript rendering/runtime package, not only
documentation.

## Source truth

`package.json` identifies `@antv/infographic` version 0.2.20 and exports a
runtime, an SSR entry point, and JSX runtime. `src/index.ts` exposes
`Infographic`, syntax parsing, templates, themes, fonts/palettes/resources,
SVG/PNG exporters, and editor commands/interactions/plugins.

`src/runtime/Infographic.tsx` parses options, composes a template, renders an
SVG tree, optionally creates an editor, waits for SVG resources, and exports
SVG or PNG. The renderer includes layouts, bounds, text measurement, fonts,
themes, palettes, gradients/patterns, and resource loaders. The package also
contains a remote icon-service constant; that is an external dependency risk,
not a reason to allow arbitrary remote resources in Sudarshan.

## Adopt

- declarative, typed visual IR compiled to SVG;
- template/theme registries as versioned allow-lists;
- explicit font/resource loading and bounded waiting;
- deterministic structural and text checks after rendering;
- SVG as the editable/intermediate artifact, with PNG as a derived export.

## Do not import wholesale

- editor state and browser interactions into the backend;
- arbitrary AntV syntax, remote icon URLs, or unbounded resource loaders;
- the site/dev/marketplace and its task lifecycle;
- renderer success without SVG integrity, text, bounds, contrast, and evidence
  checks.

## Current mapping

Sudarshan's `InfographicIR`, normalization, `pipelines/infographic/quality.py`,
and `antv_renderer` bridge are the authority. The Node bridge is a deliberately
small child-process boundary. The remaining release work is an allow-listed
template/theme registry, broader browser visual regression, and honest
fallback receipts—not exposing the AntV editor.

The reference supports custom themes and layered SVG composition, but it does
not by itself guarantee that a user-requested PPT palette or layer structure
survives export. Those requirements belong in the post-render/PPT validators.

## License and source locations

The checkout is MIT licensed. Reviewed files include `package.json`,
`src/index.ts`, `src/runtime/Infographic.tsx`, JSX/SVG renderer and exporter,
theme/template/resource modules, and README examples. Runtime integration is
recorded in `THIRD_PARTY_NOTICES.md`.
