# Sudarshan Agentic Core — MVP Progress & Status

> **Last updated:** 2026-09-07  
> **Problem statement:** SIH 2026 — NTRO SIH26154  
> **Test suite:** 78 passed, 1 skipped (deterministic, offline)

---

## What this system does

NTRO receives raw intelligence as reports, images, videos, and documents.
This platform extracts that information, stores it in semantic memory, and
on request produces controlled, auditable communication artefacts — formal
advisories, executive summaries, LinkedIn posts, infographics, and briefing
presentations — reducing the manual effort of reformatting the same
intelligence for different audiences.

```
Analyst uploads file
  → ingestion extracts text / audio / frames
  → KnowledgeUnit stored in Cognee memory
  → analyst requests output ("Create an advisory")
  → LangGraph orchestrator recalls memory
  → CrewAI agents draft the artefact
  → quality gate validates draft
  → (Advisory only) human reviewer approves
  → artefact stored in Case memory + delivered
```

---

## Architecture overview

```
Frontend (frontend/)
  → Node/Express gateway (backend-node/)   ← auth, quotas, MongoDB
    → Python FastAPI (api/)                ← REST endpoints
      → SudarshanApplication               ← single application boundary
        → Ingestion (ingestion_pipelines/) ← file → KnowledgeUnit
        → Memory (memory/)                 ← Cognee: User/Case/Task scopes
        → Orchestrator (pipelines/orchestrator/) ← LangGraph router
          → CrewAI Pipelines (pipelines/)  ← advisory, summary, linkedin,
                                              infographic, presentation
```

---

## Component status

### Ingestion — DONE

| Format | Extractor | Method |
|--------|-----------|--------|
| `.txt` | `extract.py` | Direct read |
| `.pdf` | `extract_pdf.py` | PyMuPDF digital + OpenAI vision OCR for scanned pages |
| `.pptx` | `extract_pptx.py` | python-pptx: slides, shapes, tables, speaker notes |
| `.png / .jpg / .bmp / .tiff / .webp` | `extract_image.py` | OpenAI `gpt-4o-mini` → Gemini fallback |
| `.mp4 / .mov / .avi / .mkv / .webm` | `extract_video.py` | Whisper audio + OpenCV keyframe OCR |

All formats → `to_knowledge_unit()` → `MemoryManager.remember()`.

### Memory — DONE

`MemoryManager` is the single boundary for all Cognee operations.
Three scopes: **User** (preferences) → **Case** (facts, approved artefacts)
→ **Task** (events, intermediate results, failures).

### LangGraph orchestrator — DONE

- Two-stage memory recall (before and after request understanding)
- `RequestUnderstandingAgent` + `PromptCrafterAgent`
- Clarification interrupt when query is ambiguous
- Fan-out: up to 8 pipelines concurrently, each with isolated identity
- Approval interrupt / resume seam
- Cooperative cancellation
- SSE `ProgressEvent` at every stage
- SQLite durable checkpoints (dev/single-instance default)

### CrewAI pipelines — DONE

| Pipeline | Adapter name | Human gate | Artefact |
|----------|-------------|------------|---------|
| `AdvisoryFlow` | `advisory` | Yes | Markdown in `artifacts/advisories/` |
| `LinkedInPostFlow` | `linkedin_post` | No | Optional OpenAI image |
| `ExecutiveSummaryFlow` | `executive_summary` | No | Returned to frontend |
| `InfographicFlow` | `infographic` | No | SVG via AntV renderer |
| `PresentationFlow` | `presentation` | No | `.pptx` in `artifacts/presentations/` |

Each pipeline: `schemas.py` (strict Pydantic) → `agents.py` → `tasks.py`
→ `crew.py` (subclasses `TextTransformationFlow`).

### Application boundary — DONE

`integrations/deepseek_harness/application.py` — `SudarshanApplication`:
`run`, `ingest_path`, `status`, `resume`, `cancel`, `health`, `list_pipelines`.

Also: MCP server for registered Harness deployments + JSONL stdin runner.

### Python FastAPI — DONE

`api/server.py`:

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | System health |
| GET | `/pipelines` | Registered pipeline names |
| POST | `/ingest` | File upload → extraction → memory (201) |
| POST | `/runs` | Create generation run (202, returns `run_id`) |
| GET | `/runs/{run_id}` | Poll durable run state |
| GET | `/runs/{run_id}/events` | SSE progress stream |
| POST | `/runs/{run_id}/resume` | Clarification answer or approval decision |
| POST | `/runs/{run_id}/cancel` | Cooperative cancellation |

### Node/Express gateway — DONE

`backend-node/` — browser-facing production service:

- Google OAuth2/OpenID Connect login → MongoDB user upsert → HttpOnly JWT cookies
- MongoDB Atlas-backed: users, cases, tasks, OAuth state, rate-limit buckets
- Case ownership and task isolation per authenticated user
- `/api/v1/transform` — main frontend-facing endpoint
- Task polling (`?wait=true` long-poll), resume, cancel, SSE proxy
- `js-tiktoken` token accounting → `X-Input-Tokens` / `X-Output-Tokens` headers
- MongoDB-backed rate limiting (shared across instances)
- `Idempotency-Key` protection against duplicate tasks
- Helmet, strict CORS, request IDs, graceful shutdown

### Reference frontend — DONE

`frontend/` — dependency-free vanilla JS/HTML:

- `login.html` + `login.js` — Google OAuth flow
- `index.html` + `script.js` — cases, output submission, polling, cancellation
- `api.js` — cookie-authenticated gateway helpers

Serve with: `python -m http.server 3000 --directory frontend`  
Open: `http://localhost:3000/login.html`  
(**Must** be HTTP — not `file://` — cookies and CORS require an HTTP origin.)

### DeepSeek Harness — DONE (vendored + integrated)

Full harness source in `deepseek-harness/`. Bridge in `integrations/deepseek_harness/`.

---

## What needs credentials to run

The code is complete. A live demo requires:

```dotenv
# Cognee (memory backend)
COGNEE_BASE_URL=http://localhost:8011      # or Cloud URL
COGNEE_API_KEY=<key>
COGNEE_TENANT_ID=<tenant>                 # Cloud only
COGNEE_DATASET_NAME=sudarshan_memory

# AI providers
OPENAI_API_KEY=<key>                      # already set (ingestion + pipelines)
GEMINI_API_KEY=<key>                      # already set (fallback)
CREWAI_MODEL=openai/gpt-4o-mini
CREWAI_DISABLE_TELEMETRY=true

# Node gateway
MONGODB_URI=mongodb+srv://...             # not yet set
GOOGLE_CLIENT_ID=<id>                     # not yet set
GOOGLE_CLIENT_SECRET=<secret>             # not yet set
JWT_ACCESS_SECRET=<long-random>           # not yet set
JWT_REFRESH_SECRET=<long-random>          # not yet set
FRONTEND_URL=http://localhost:3000
PYTHON_API_BASE_URL=http://localhost:8000
```

---

## What still needs to be done

### Blockers for live demo
- [ ] Cognee live instance or Cloud account + API key
- [ ] MongoDB Atlas cluster (free tier) + connection URI
- [ ] Google Cloud Console OAuth2 client (authorized redirect: `http://localhost:8080/api/v1/auth/google/callback`)
- [ ] Fill `.env` with all values above
- [ ] AntV renderer setup: `cd pipelines/infographic/antv_renderer && npm install`

### Known gaps (post-demo)
- [ ] End-to-end integration tests with real credentials (currently all offline/deterministic)
- [ ] HTTPS + `NODE_ENV=production` + WAF/edge for production hardening
- [ ] Durable worker queue for fan-out (current: in-process threads, dev only)
- [ ] Batch approval for multiple human-gate pipelines in one run
- [ ] `git rm -r artifact-pipeline` — old dummy folder still in repo

---

## Starting the full system

```powershell
# One-time: copy and fill environment file
Copy-Item .env.example .env

# Install all dependencies + start all services
pwsh -NoProfile -ExecutionPolicy Bypass -File .\startup.ps1
```

Services started:
- Python FastAPI on `http://localhost:8000`
- Node gateway on `http://localhost:8080`
- Frontend on `http://localhost:3000`

Smoke test:
```powershell
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8000/pipelines
```

Run the full test suite:
```powershell
uv run pytest -q
```

---

## Ownership

| Area | Owner |
|------|-------|
| `ingestion_pipelines/` | Abhishek |
| `pipelines/ppt/` | Abhishek |
| `memory/` | Udit |
| `pipelines/` (advisory, linkedin, exec summary, infographic) | Udit |
| `pipelines/orchestrator/` | Udit |
| `api/` | Udit |
| `backend-node/` | Udit |
| `integrations/` | Udit |
| `frontend/` | Udit |
| `deepseek-harness/` | Vendored — DeepSeek AI open source |
