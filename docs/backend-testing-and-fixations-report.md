# Sudarshan Backend Testing & Fixations Ledger

This document serves as an immutable verification and test audit log for the Sudarshan Agentic Core (`sudarshan2.2` branch). It details the test execution records, environment baselines, critical bugs identified, and the architectural fixations applied.

---

## Log Entry: 2026-09-13 — Phase 1 to Phase 5 Backend & Ingestion Hardening

* **Tester**: Abhishek Padi (Ingestion Pipeline & Testing) + AI Pair Teammate
* **Branch**: `sudarshan2.2`
* **Target Components**: 
  * Python FastAPI Application (`api/`)
  * Multimodal Ingestion Pipeline (`ingestion_pipelines/`)
  * Node.js API Gateway (`backend-node/`)
  * Shared Memory & Control Plane (`memory/`, `integrations/deepseek_harness/`)

---

### 1. Test Suite Summary & Pass Rates

| Suite | Command | Result | Duration | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Node.js Gateway Tests** | `npm test` in `backend-node` | **11 passed / 0 failed** | 6.5s | Contract, token accounting, validation |
| **Node.js Gateway Syntax** | `npm run check` in `backend-node` | **13 passed / 0 failed** | ~1s | All gateway JS modules syntax valid |
| **Bug Verification Suite** | `pytest tests/component/test_evidence_index.py tests/component/test_ingestion_application_cache.py` | **8 passed / 0 failed** | 0.6s | Verifies idempotent re-indexing & memory fallback |
| **Ingestion Real Files** | `pytest ingestion_pipelines/tests` | **10 passed / 1 skipped** | 0.7s | Real extraction on `sample_text.txt`, `dsaqueue.pdf`, `dummy_presentation.pptx`, `sample_briefing.mp4` |
| **Multimodal Component Tests** | `pytest tests/component/test_evidence_*.py ...` | **34 passed / 0 failed** | 1.25s | Evidence index, chunks, temporal graph, budget |
| **Full Repository Test Suite**| `pytest tests/ -q` | **333 passed / 7 skipped** | 23.11s | 100% pass across all system, pipeline, and unit tests |
| **Live Physical HTTP Smoke** | Real multipart POST to `http://127.0.0.1:8000/ingest` | **201 Created** | Live | Tested real PDF, PPTX, and TXT uploads |

---

### 2. Critical Bugs Identified & Architectural Fixations

#### Bug #1: SQLite Primary Key Collision on Document Re-Upload (502 Bad Gateway)
* **Observed Behavior**: When an operator re-uploaded or attached a previously seen file (e.g. `dsaqueue.pdf` or `dummy_presentation.pptx`) from the frontend dashboard, the API failed with `HTTP 502 Bad Gateway` returning `{ "detail": "Source extraction or memory persistence failed" }`.
* **Root Cause**: In `ingestion_pipelines/evidence_index.py`, `evidence_blocks` has `evidence_id TEXT PRIMARY KEY`. The evidence ID is deterministically derived from `source_hash` and modality. The previous code ran `INSERT INTO evidence_blocks`, causing a hard `sqlite3.IntegrityError: UNIQUE constraint failed: evidence_blocks.evidence_id`.
* **Fix Applied**: Updated `ingestion_pipelines/evidence_index.py` to use `INSERT OR REPLACE INTO evidence_blocks`, `INSERT OR REPLACE INTO evidence_chunks`, and `INSERT OR REPLACE INTO evidence_relationships`. Re-indexing is now completely idempotent.
* **Automated Regression Test**: `test_evidence_index_reindex_idempotent` in `tests/component/test_evidence_index.py`.

#### Bug #2: File Ingestion Crash on External Memory Network Failure
* **Observed Behavior**: During `POST /ingest` or `POST /ingestions`, if the Cognee memory service was offline, slow, or experienced a network timeout, `project_to_memory()` threw an unhandled `URLError` / `CogneeRequestError` that aborted the entire upload with `502 Bad Gateway`, discarding the parsed source file.
* **Root Cause**: Lack of an adaptive fallback seam around memory projection in `integrations/deepseek_harness/application.py`. Cognee is a projection layer, not the source of truth for raw evidence.
* **Fix Applied**: Wrapped `project_to_memory()` in a resilient `try...except` block. If the memory service is unreachable or errors out, the upload still succeeds (`201 Created`), the file and evidence chunks are safely indexed for presentation/video/infographic generators, and the receipt records `"status": "partial"`, `"memory_persisted": false`, and `"fallbacks": ["memory_projection_unavailable"]`.
* **Automated Regression Test**: `test_memory_projection_failure_returns_partial_status_and_records_fallback` in `tests/component/test_ingestion_application_cache.py`.

---

### 3. Environment & Deployment Notes

1. **Windows UV Link Mode**:
   * On Windows development environments (especially inside synced user folders such as Downloads or OneDrive), hardlinking wheel files can fail with OS Error 396. Always ensure `$env:UV_LINK_MODE="copy"` is set prior to running `uv sync --locked`.
2. **Cognee Cloud vs Local**:
   * In production, `COGNEE_BACKEND=cloud` communicates over HTTPS with the AWS-hosted Cognee service (`https://...`) using `COGNEE_API_KEY` and `COGNEE_TENANT_ID`.
   * In local development/testing without cloud credentials, setting `COGNEE_BACKEND=local` allows tests to run deterministically against the local development contract without blocking on external cloud authentication.

---

### 4. Verification History (Append-Only Log)

* **2026-09-13 15:45:00 UTC+05:30**: Hands-on run verified by Abhishek Padi:
  * Step 1 (Bug Verification): 8 passed in 0.59s.
  * Step 2 (Ingestion Suite): 10 passed, 1 skipped in 0.66s.
  * Step 3 (Node.js Gateway): 11 passed in 6.49s; check clean.
  * Step 4 (Full Repo Suite): 333 passed, 7 skipped in 23.11s.

