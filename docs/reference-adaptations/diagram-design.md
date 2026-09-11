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
| Semantic layout selection | `diagram_type_registry`, `choose_semantic_pattern`, and `DiagramSpec` metadata | Registry is allow-listed; unsupported types do not become arbitrary HTML |
| Semantic style profiles | `pipelines/diagram/style.py` and `ntro-default` tokens | Profiles are versioned semantic roles; remote brand scraping is not enabled |
| Import/export ecosystem | `pipelines/diagram/importers.py` and `export.py` | Basic bounded Mermaid/Draw.io/Excalidraw import and HTML/SVG export are implemented; broader fidelity and PNG/browser export remain ticketed |
| Frontend artifact boundary | `frontend/diagram/preview.js` | Preview consumes authorized artifact URLs and projections; editing and approval remain outside this slice |

## Deliberately not copied

- The reference editor, plugin marketplace, and multi-host installation layer
- Arbitrary generated HTML or JavaScript
- Its motion controller and animation assets
- Unvalidated imports or remote assets

## Review rule

Every future adaptation must add a row here, retain the upstream license notice
when code is copied, add a focused regression test, and pass Sudarshan's
evidence, budget, provenance, security, and quality gates.
