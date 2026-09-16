# agentmemory adaptation ledger

**Audit date:** 2026-09-16
**Reference:** `C:\Users\uditj\Downloads\sudarshan\references\agentmemory`
**Source classification:** executable Apache-2.0 coding-agent memory runtime,
not merely a prompt collection.

## Source truth

The checkout's `src/index.ts` starts a local memory server around a pinned
`iii-sdk`/`iii-engine` worker and registers a broad function and MCP surface.
The README and tool registry describe 54 MCP tools by default, an 8-tool core
profile, REST/MCP on port 3111, streams on 3112, a viewer on 3113, and an iii
worker WebSocket on 49134. It also provides plugin lifecycle hooks and a live
operator viewer.

The default keyless path is BM25 recall. Embeddings are opt-in, and LLM
observation compression requires both a provider and
`AGENTMEMORY_AUTO_COMPRESS=true`. The source contains persistence, hybrid
search, deduplication, sessions, relations, lessons, leases/checkpoints,
forgetting/governance, and many optional integrations. That breadth is useful
evidence, but it is also a substantial operational surface.

## Useful ideas to reimplement

| Idea | Sudarshan treatment |
| --- | --- |
| Stable fingerprints and duplicate suppression | Use request/case/evidence fingerprints; never deduplicate solely by text similarity. |
| Memory lifecycle | Keep explicit create/update/supersede/retract/forget transitions with provenance and confidence. |
| Bounded recall | Let stage policy choose memory tier, count, and character/token budget. |
| Hybrid retrieval | Compare exact evidence retrieval with Cognee semantic retrieval in evaluation; do not claim upstream benchmark results. |
| Leases and checkpoints | Apply to long-running DeepSeek/provider work, not to memory rows alone. |
| Operator visibility | Project safe lifecycle counts and provenance; never expose raw prompts, secrets, or unrestricted tool arguments. |

## Do not import wholesale

- coding-agent-specific hooks, skills, REST routes, or MCP tools;
- a second memory database beside Cognee and the local evidence index;
- automatic context injection on every turn without a measured token budget;
- provider detection, local ports, or native `iii-engine` process management;
- unreviewed `memory_compress_file`-style file mutation;
- claims that the upstream token-saving or retrieval benchmarks transfer to NTRO.

The 54-tool surface is a clear overengineering risk for the Harness model
context. Sudarshan should expose a small role-specific profile and keep
maintenance operations behind application policy.

## Sudarshan boundary

`MemoryManager`, `AccessContext`, Cognee, and the evidence index remain the
only application memory boundary. A future optional session hook may emit
content-free observations, but it must be non-blocking, tenant-scoped,
bounded, redacted, and testable. Any copied source must retain Apache-2.0
notices and receive a separate security review.

## Source locations checked

- `src/index.ts` — worker/server lifecycle and registered capabilities
- `src/mcp/tools-registry.ts` — MCP tool surface and schemas
- `src/` persistence/search modules — deduplication, indexing, and state
- `README.md` — ports, profiles, setup, and operational claims
