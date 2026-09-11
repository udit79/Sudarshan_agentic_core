# Diagram Design adaptation ledger

Status: native flowchart SVG/PPTX boundary hardened locally. This ledger
applies to the checked-out reference at
`C:\Users\uditj\Downloads\sudarshan\references\diagram-design`.

## License boundary

The reference is MIT licensed. Sudarshan adopts design and validation ideas
through its typed flowchart IR and native renderers; it does not copy the
reference plugin marketplace, editor, HTML assets, or controller runtime.

## Adopted concepts and modules

| Capability | Sudarshan implementation | Adoption boundary |
|---|---|---|
| Static-by-default output | `render_flowchart_svg` | SVG contains no executable behavior; motion remains out of scope for this slice |
| Accessible SVG contract | Native SVG title/description metadata and safety checks | Text and provenance still come from typed, authorized IR |
| Geometry-first QA | `inspect_flowchart` plus SVG safety inspection | Promotion blocks off-canvas, overlap, crossing, unsafe, and missing-label output |
| Semantic layout selection | `FlowchartSpec` direction/kind/layout hints | Broader type registry is ticketed, not inferred from arbitrary HTML |
| Import/export ecosystem | Not copied | Mermaid, draw.io, and Excalidraw require sanitized adapters and separate contracts |

## Deliberately not copied

- The reference editor, plugin marketplace, and multi-host installation layer
- Arbitrary generated HTML or JavaScript
- Its motion controller and animation assets
- Unvalidated imports or remote assets

## Review rule

Every future adaptation must add a row here, retain the upstream license notice
when code is copied, add a focused regression test, and pass Sudarshan's
evidence, budget, provenance, security, and quality gates.
