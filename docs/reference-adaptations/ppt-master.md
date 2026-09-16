# PPT Master adaptation ledger

**Audit date:** 2026-09-16
**Reference:** `C:\Users\uditj\Downloads\sudarshan\references\ppt-master`
**Source classification:** MIT routed presentation skill package with Python
SVG/PPTX tooling, templates, validators, and confirmation UI.

## Source truth

The package is version 6.3.2. Its top-level skill routes requests to Generate
PPTX, Create Template, or Edit Native PPTX. The package has a large workflow,
reference, template, and script surface; it is not a small reusable library.

The most important source-preserving path is Edit Native PPTX. Its
`pptx_to_svg.py --roundtrip` workspace keeps immutable native backing, compact
editable SVGs, source media, notes, and a `page_plan.json`. Unchanged pages are
referenced/restored byte-for-byte; edited pages are rebuilt only where needed.
`svg_quality_checker.py --roundtrip` gates capacity and export prints
`passthrough`, `cloned_passthrough`, `patched`, and `rebuilt` counts. Delivery
checks and PPTX read-back verify slide count, text, notes, and receipt buckets.

Generate is a separate Plan → Do/Check/Act route. Its confirmation UI, prompts,
templates, and profile catalog are useful workflow material, but are not a
durable multi-tenant scheduler or memory system.

## Adopt

| Idea | Sudarshan treatment |
| --- | --- |
| Page-local jobs | Stable `slide_id`, page job, evidence bindings, and dependency invalidation. |
| Native round-trip | Preserve untouched slide/package parts; rebuild only changed slides or dependent resources. |
| Render → inspect → repair | Enforce text capacity, bounds, contrast, structure, and output read-back before success. |
| Explicit receipts | Surface passthrough/rebuilt pages, warnings, fallbacks, and export path. |
| Style/profile separation | Keep colors, typography, layers, and layout as typed profile tokens rather than prompt prose. |

## Do not import wholesale

- the confirmation web server as the application scheduler;
- the entire template catalog and all 285 scripts into runtime;
- UI prompts as enforcement for page count, colors, layers, or edit scope;
- full-deck regeneration for a one-slide update;
- tolerant conversion that silently drops unsupported native objects.

## Current mapping and gap

Sudarshan already has page jobs, PPT quality/repair, renderer registry, and
native artifact checks. The reference confirms the correct direction for the
remaining selective-edit work: a per-slide artifact manifest with stable IDs,
dependency edges, native source backing, and a receipt proving untouched slides
were not rebuilt. Custom colors and layers must be asserted after export; a
prompt or style profile alone is not proof.

## License and source locations

The checkout is MIT licensed. Reviewed files include `skills/ppt-master/SKILL.md`,
`workflows/routing.md`, `workflows/edit-native-pptx.md`, `scripts/pptx_to_svg.py`,
`scripts/svg_to_pptx.py`, `scripts/svg_quality_checker.py`, delivery checks,
and the PowerPoint mapping documentation. Any copied script, template, font,
icon, or image needs an asset-level notice/review.
