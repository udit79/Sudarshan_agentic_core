# Diagram Design adaptation ledger

**Audit date:** 2026-09-16
**Reference:** `C:\Users\uditj\Downloads\sudarshan\references\diagram-design`
**Source classification:** MIT Agent Skill/reference pack with static HTML/SVG
examples and validation scripts; it is not a general-purpose rendering
service.

## Source truth

The reference's shipped diagrams are self-contained static HTML/SVG specimens.
Its skill separates semantic pattern from layout, keeps static output as the
default, supports optional motion, and provides bounded Mermaid/draw.io/
Excalidraw extraction. The import procedures explicitly treat labels, URLs,
styles, and embedded content as untrusted data; they parse rather than execute
or fetch it. The repository includes stdlib validators for geometry,
accessibility/contrast, semantic metadata, and documentation synchronization.

The “39 types” and many screenshots are a design catalog, not evidence that
Sudarshan should add 39 independent renderers. The reference itself recommends
deletion and a low visual density; that principle is more reusable than its
catalog size.

## Adopt

| Idea | Sudarshan treatment |
| --- | --- |
| Semantic pattern before layout | Keep `DiagramSpec`/family selection separate from geometry. |
| Static-first output | Native SVG/PPTX is the default; motion is opt-in and never the only artifact. |
| Accessible SVG | Require title/description, stable IDs, contrast, and decorative-element handling. |
| Complexity budget | Reject disconnected, overcrowded, off-canvas, or unreadable graphs before promotion. |
| Safe import | Parse bounded source text into typed IR; never execute Mermaid, HTML, links, or embedded payloads. |
| Semantic tokens | Use versioned NTRO style roles; do not scrape a remote website at render time. |

## Deliberately not copied

- plugin marketplace and multi-host installation instructions;
- every catalog type, screenshot, or prompt/reference file;
- arbitrary HTML/JavaScript output, remote assets, or browser execution;
- optional motion controller as a replacement for durable artifact state.

## Current mapping

`pipelines/diagram/family.py`, `style.py`, `importers.py`, `export.py`, and
the native renderer already own the runtime boundary. The reference is best
used for style/semantic fixtures and validator cases. It does not solve the
missing DAG return problem; the typed graph must still be returned and checked
by Sudarshan's orchestrator.

The main remaining gap is a reviewed visual-regression corpus for the selected
families, not a wholesale port of the repository.

## License and source locations

The checkout includes MIT `LICENSE` and `THIRD_PARTY_LICENSES.md`. Files
reviewed include `README.md`, `skills/diagram-design/SKILL.md`, the import/export
references, `scripts/verify-*.py`, and the semantic-pattern ADRs. Any copied
asset or code needs its own notice.
