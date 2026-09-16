# MoneyPrinterTurbo adaptation ledger

**Audit date:** 2026-09-16
**Reference:** `C:\Users\uditj\Downloads\sudarshan\references\MoneyPrinterTurbo`
**Source classification:** MIT video application with WebUI/API/CLI, task
state, provider adapters, and FFmpeg composition.

## Source truth

The application path is `app/services/task.py` plus `state.py`,
`task_artifacts.py`, `material.py`, `subtitle.py`, `bgm.py`, `video.py`,
provider modules, controllers, Redis integration, WebUI, and CLI. It covers
script/term generation, stock or generated material, subtitles, BGM, voice,
composition, and optional cross-posting.

The strongest reusable implementation is `app/services/material_cache.py`:
it uses a 24-hour TTL, a SHA-256 key over provider/search/duration/aspect,
256 in-process lock shards, temporary files plus `os.replace`, sanitized public
URLs, and a storage directory shared by WebUI/API/CLI/Docker restarts. The
video path records material sources and uses practical duration/resolution
selection. Subtitle and provider paths contain compatibility fallbacks and
retry behavior.

## Adopt

| Idea | Sudarshan treatment |
| --- | --- |
| Stable material cache | Reuse the key/atomic-write/provenance pattern under scoped artifact paths. |
| Provider-neutral timeline | Keep `VideoPackage`/timeline and scene manifests as the authority. |
| Scene-level recovery | Retry or reuse one scene by exact fingerprint; never rerun the whole video for one failure. |
| Source ledger | Persist provider, source page, asset ID, local hash, license/provenance, and selection reason. |
| FFmpeg composition | Use the native renderer and inspect the finished media before promotion. |

## Fallback audit

MPT's pragmatic fallbacks are useful in a single-user app but dangerous as
silent defaults in an evidence-governed service: missing Whisper can return an
empty subtitle result, composition may reuse overflow clips, provider failures
can leave partial material, and global/process task state is not a distributed
lease. Sudarshan must convert every such choice into an explicit warning or
failed quality gate with the selected fallback, reason, and artifact receipt.

## Do not import wholesale

- WebUI/controllers, Redis task ownership, cross-post publishing, or global
  state;
- provider credentials and raw remote payloads;
- default music/media without a rights and provenance check;
- a fallback that changes the user's requested duration, aspect, asset type, or
  quality without reporting it.

## Current mapping

`pipelines/video/timeline.py`, `media.py`, `native_generator.py`, and the
MoneyPrinter adapter already keep the application contract, cancellation,
manifest, and quality checks in Sudarshan. The reference remains an explicit
compatibility backend, not the default orchestrator.

## License and source locations

The checkout is MIT licensed. Reviewed files include `app/services/task.py`,
`material_cache.py`, `material.py`, `subtitle.py`, `video.py`, controllers,
README, and provider modules. Any copied code/assets must retain notices and
receive an asset/license review.
