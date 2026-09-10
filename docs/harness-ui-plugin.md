# Harness UI composition

Sudarshan's visual changes are now loaded as replaceable DeepSeek Harness
plugins rather than by forking or relabeling the official branding package.

## Product plugins

| Package | Owns | Does not own |
| --- | --- | --- |
| `@deepseek-ai/dsh-experimental-client-ui-sudarshan` | Sidebar mark, wordmark, and empty-session hero mark | Sessions, model calls, MCP, artifacts, or routing |
| `@deepseek-ai/dsh-experimental-client-ui-sudarshan-theme` | Product stylesheet and lifecycle-owned `<style>` tag | Generic Harness theme services and settings |

The web bundle registers both packages in
`deepseek-harness/packages/bundle/web-app/cordis.patch.yml`. To create a
white-label build, replace those two package rows with another brand/theme
pair; the core Harness packages and the Sudarshan backend remain unchanged.

## Local build

From `deepseek-harness/`:

```powershell
node node_modules/typescript/bin/tsc -b packages/experimental/client-ui-sudarshan/tsconfig.json
node node_modules/typescript/bin/tsc -b packages/experimental/client-ui-sudarshan-theme/tsconfig.json
node node_modules/tsdown/dist/run.mjs --config packages/experimental/client-ui-sudarshan/tsdown.config.ts
node node_modules/tsdown/dist/run.mjs --config packages/experimental/client-ui-sudarshan-theme/tsdown.config.ts
```

The normal repository build should be preferred once the workspace package
manager has linked the new packages. The package lock contains workspace links
for both additions.

## Preview-state security

`.dsh-preview/` is local Harness state and is ignored. It must never be copied
into a commit because it can contain credentials, session transcripts, caches,
and machine-specific absolute paths. A credential that was present in an
earlier commit must be revoked/rotated even after the file is removed locally;
removing a working-tree file does not erase Git history.
