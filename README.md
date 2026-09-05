# Sudarshan Agentic Core

The `memory` package is the Sudarshan-side memory unit. It accepts ingestion
`KnowledgeUnit` objects, applies User/Case/Task scope policy, and delegates
knowledge graph and semantic retrieval to Cognee. See
[`memory/README.md`](memory/README.md) for setup and usage.

## One-command setup

From PowerShell, run:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

This installs the locked Python dependencies and the pinned AntV infographic
renderer together. It requires `uv` and Node.js/npm. The setup script uses
`npm install --ignore-scripts`; runtime rendering is performed by the checked-in
AntV bridge under `pipelines/infographic/antv_renderer/`.

After setup, use the Python environment with `uv run ...`; no separate npm
installation command is needed.

## Start testing

Copy `.env.example` to `.env` if needed, then add the Cognee Cloud values and
the CrewAI provider credentials. The example disables optional CrewAI telemetry
by default. Run the focused unit suite with:

```powershell
uv run pytest -q
```

The test configuration intentionally targets the Sudarshan-owned suites and
does not collect the vendored DeepSeek Harness test tree.

Generated advisory, LinkedIn image, and infographic files are written below
`artifacts/`, which is intentionally ignored by Git.

## DeepSeek Harness integration

The pipeline package is currently testable as an independent application
boundary. The Harness should own session, tool, and runtime execution; these
pipelines should continue to own CrewAI orchestration and memory policy. The
recommended next step is a thin adapter exposing one stable request/result
envelope to the Harness. Do not make each pipeline depend directly on Harness
internals. We can add that adapter after the PPT and video pipelines adopt the
same envelope; the current pipelines and memory unit do not need to wait for
those implementations to begin testing.
