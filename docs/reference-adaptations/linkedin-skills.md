# linkedin-skills adaptation ledger

**Audit date:** 2026-09-16
**Reference:** `C:\Users\uditj\Downloads\sudarshan\references\linkedin-skills`
**Source classification:** MIT skill/reference pack with optional Python
helpers for Apify and publishing-related workflows.

## Source truth

The checkout contains many Markdown/YAML skills and a small Python `lib`
surface. The humanizer has forensic, strict, aesthetic, all, audit, and
profile modes. Its own references distinguish genuine model leakage from
normal human vocabulary and explicitly do not promise to beat AI detectors.
Voice profiling asks for multiple user samples; Apify is an optional
accelerator, not a requirement.

The hook extractor treats fetched posts/comments/headlines as untrusted data,
never follows instructions embedded in fetched text, asks the user to paste
content when Apify is unavailable, and does not spend a credit on an
unrequested call. The illustration/publish procedures require showing the
result and obtaining approval before attaching media or publishing.

## Adopt

- separate writing/drafting, audit, visual child work, and publishing;
- preserve a humanizer report with rule IDs and paragraph-level findings;
- use user-provided samples and confidence/coverage metadata for voice profile;
- treat external social content as data, never as instructions or approval;
- keep publication as an explicit side effect behind user approval and a
  configured connector.

## Do not import wholesale

- automatic LinkedIn publishing or Apify credentials;
- detector scores or reach claims as quality truth;
- aggressive rewrites that erase the user's meaning or voice;
- the repository's marketing/platform assumptions as NTRO policy;
- dozens of independently discoverable skills in the Harness context.

## Current mapping

Sudarshan's `linkedin.post` is draft-first and already supports claim/evidence
bindings, quality review, optional visual-child planning, and explicit publish
policy. The useful next step is a reviewed humanizer evaluation corpus and
clear report-vs-rewrite behavior. A LinkedIn agent may request the diagram or
infographic agent through `ChildTaskSpec`; it must not call the public run API
recursively.

## License and source locations

The checkout is MIT licensed. Reviewed files include root `SKILL.md`,
`AGENTS.md`, `skills/linkedin-humanizer` and its sub-skills/references,
`linkedin-hook-extractor`, and `lib`. Any copied skill or asset needs the MIT
notice and an explicit policy review.
