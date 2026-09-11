# MoneyPrinterTurbo adaptation ledger

Status: in progress. This ledger applies only to the local checked-out
reference at `references/MoneyPrinterTurbo`.

## License boundary

MoneyPrinterTurbo is MIT licensed. Any copied or materially adapted code must
retain its copyright and license notice. Sudarshan does not import the
MoneyPrinterTurbo package, run its WebUI, or copy its task manager/controller
layer.

## Adopted concepts and modules

| Capability | Sudarshan implementation | Adoption boundary |
|---|---|---|
| Material cache keys and atomic files | `pipelines/video/media.py` | Reimplemented with scoped paths and provider provenance |
| Stock material selection | `MaterialResolver` | Local materials by default; Pexels is explicit opt-in |
| Subtitle sidecar generation | `write_scene_subtitles` | Deterministic scene cues; no unbounded model call |
| BGM selection/mixing | `select_music` and native FFmpeg composition | Local/licensed music only; explicit degradation on failure |
| FFmpeg composition | `NativeVideoGenerator` | Sudarshan timeline, cancellation, manifest, and QA remain authoritative |
| Scene retry/cache | `VideoSceneManifest` and fingerprints | Exact-input and authorization-scoped reuse only |

## Deliberately not copied

- MoneyPrinterTurbo WebUI and API controllers
- Its linear task orchestration and global task state
- Its provider credential/configuration ownership
- Unscoped raw provider payloads or source paths

## Review rule

Every future adaptation must add a row here, retain the upstream license
notice when code is copied, add a focused regression test, and pass the
Sudarshan security, budget, cancellation, provenance, and quality gates.
