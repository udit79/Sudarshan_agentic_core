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

#### Bug #3: Corrupted / Empty Files Triggered 502 Bad Gateway Instead of 422
* **Observed Behavior**: When a user uploaded an empty, malformed, or damaged file (e.g. truncated PDF or corrupt PPTX), PyMuPDF raised `EmptyFileError` and `python-pptx` raised `PackageNotFoundError`. In `api/server.py`, the exception handler only caught `(FileNotFoundError, ValueError)`, causing these parser errors to fall into `except Exception:` and return `HTTP 502 Bad Gateway` ("Source extraction or memory persistence failed"). On the frontend, Node's gateway caught 502 and rendered an internal server error JSON alert.
* **Root Cause**: Neither PyMuPDF's `EmptyFileError` nor `python-pptx`'s `PackageNotFoundError` inherits from `ValueError`.
* **Fix Applied**: 
  1. Updated `ingestion_pipelines/extract_pdf.py` to catch all PyMuPDF and pypdf corruption errors and raise clean `ValueError("Corrupted or unreadable PDF file...")`.
  2. Updated `ingestion_pipelines/extract_pptx.py` to catch `PackageNotFoundError` and bad archives, raising clean `ValueError("Corrupted or unreadable PowerPoint presentation...")`.
  3. Expanded `api/server.py` catch to `(FileNotFoundError, ValueError, OSError)` returning `HTTP 422 Unprocessable Entity` with exact details instead of 502.
* **Automated Regression Test**: `tests/component/test_ingestion_edge_cases.py`.

#### Bug #4: Windows File Descriptor Locks on Temporary Files
* **Observed Behavior**: On Windows systems, PyMuPDF opened documents via `pymupdf.open(str(path))` without an explicit `doc.close()` in a `finally` block, and OpenCV `cv2.VideoCapture` was not guarded by `try...finally`. This held an active OS file lock on the temporary file, raising `PermissionError [WinError 32]` when `api/server.py` attempted to clean up the temporary upload via `Path(temp_path).unlink()`.
* **Fix Applied**: Added `try...finally: doc.close()` in `extract_pdf.py` and `try...finally: cap.release()` in `extract_video.py`.
* **Automated Regression Test**: `test_pdf_extractor_closes_doc_and_prevents_file_lock` in `tests/component/test_ingestion_edge_cases.py`.

#### Enhancement #1: Node.js Gateway Asynchronous Ingestion Pass-Through (T46)
* **Goal**: Support high perceived upload speed for heavy files (scanned PDFs, videos) without hitting the 180s synchronous HTTP timeout.
* **Implementation**: Added `submitIngestion` and `getIngestionStatus` in `backend-node/src/python-client.js`. Exposed `POST /api/v1/ingestions` (returns `202 Accepted` in milliseconds) and `GET /api/v1/ingestions/:id` in `backend-node/src/routes.js` while maintaining 100% backward compatibility for the existing `POST /api/v1/ingest` route.
* **Automated Regression Test**: `submitIngestion forwards multipart upload and custom headers to Python API` in `backend-node/test/python-client.test.js`.

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

* **2026-09-13 16:18:00 UTC+05:30**: Option A Ingestion Hardening & Leak Prevention Verified:
  * Edge Cases Regression Suite (`test_ingestion_edge_cases.py`): 5 passed in 1.51s.
  * Node.js Gateway Test Suite (`backend-node/test`): 12 passed in 1.17s; 13 files checked clean.
  * Python Component & Ingestion Suite: 247 passed, 2 skipped in 21.86s.
  * Live Physical Server Verification:
    * Real PDF (`dsaqueue.pdf`): 201 Created (`status: partial`).
    * Real PPTX (`dummy_presentation.pptx`): 201 Created (`status: partial`).
    * Corrupted PDF: Clean `415 Unsupported Media Type` (`"source content does not match its declared file type"`), zero 502 errors.
    * Asynchronous route (`POST /ingestions`): Returned `202 Accepted` with queued status and token/parser budget.


