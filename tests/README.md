# Test suite

This folder contains the cross-package test suite for the memory-aware
orchestration layer. It is intentionally deterministic and does not call live
Cognee, OpenAI, CrewAI providers, AntV, or external upload services.

```text
tests/
├── component/   # isolated component and contract behavior
├── pipeline/    # each registered pipeline adapter contract
└── system/      # complete orchestration scenarios
```

Run everything from the repository root:

```bash
uv run pytest -q --basetemp .pytest-tmp-current
```

On Windows environments where the system pytest temp directory is locked,
use the workspace-local temporary root shown above. The local suite currently
finishes with 178 passed and 1 skipped; third-party deprecation warnings are
expected and do not indicate a provider smoke test.

The system scenarios currently cover:

1. ingestion → `KnowledgeUnit` → Case memory → request understanding → memory
   recall → prompt plan → pipeline result;
2. clarification interrupt → frontend answer → same-run resume → generation;
3. pipeline approval interrupt → authorized decision → same-run resume.

Live provider smoke tests should be added separately and must be explicitly
opted into so normal CI never sends case data to external services. The video
adapter component tests use a transport seam to verify the documented request
and response contract; they do not claim that a video was generated. A real
MoneyPrinterTurbo or multimodal ingestion smoke test should use synthetic
input, an explicitly configured worker, and `RUN_LIVE_PROVIDER_TESTS=1` only.

For focused work:

```powershell
# Orchestration, scheduler, memory, cache, and security contracts
.\.venv\Scripts\python.exe -m pytest tests/component -q --basetemp .pytest-tmp-component

# PPT, infographic, video, and text pipeline contracts
.\.venv\Scripts\python.exe -m pytest tests/pipeline pipelines/tests -q --basetemp .pytest-tmp-pipeline

# API/application boundary
.\.venv\Scripts\python.exe -m pytest api/tests tests/system -q --basetemp .pytest-tmp-system
```
