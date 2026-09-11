# Sudarshan frontend

This is a dependency-free static frontend for the Node/Express gateway in
`../backend-node`. It uses Google OAuth through HttpOnly cookies, loads
user-owned cases, adds source files to case memory, submits selected output
pipelines, follows live progress, and renders safe transformed output and
artifact previews. It is the reference operator dashboard; the gateway and
Python backend remain responsible for identity, ownership, classification,
quotas, artifact access, and provider credentials.

## Run locally

From the repository root, the one-command bootstrap installs dependencies,
initializes MongoDB Atlas indexes, and starts Python, Node, and the frontend:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\startup.ps1
```

To serve only this folder during frontend-only work:

```powershell
Set-Location .\frontend
python -m http.server 3000
```

Open `http://localhost:3000/` for the public landing page. After sign-in,
`index.html?dashboard=1` opens the native Sudarshan dashboard. The normal
`startup.ps1` path installs and runs no external Harness checkout. An optional
Harness profile can be launched with `index.html?harness=1` only when
`window.SUDARSHAN_HARNESS_URL` is configured. Sudarshan does not require the
Harness repository to run. Do not open the HTML files with
`file://`; browser cookies and CORS require an HTTP origin.

The gateway defaults to `http://localhost:8080`. To use another gateway,
define `window.SUDARSHAN_API_ORIGIN` before `api.js` in both HTML files:

```html
<script>window.SUDARSHAN_API_ORIGIN = "https://api.example.com";</script>
<script src="api.js"></script>
```

## Frontend structure

- `api.js` — shared gateway/FastAPI client, canonical run projection, cookie
  credentials, one-refresh retry, multipart source upload, event-cursor
  persistence, artifact manifests, errors, and idempotency keys.
- `landing.html` / `landing.css` / `landing.js` — public product landing page and entry point.
- `landing-react.js` / `landing-react.css` — React robot island with cursor parallax and reduced-motion fallback.
- `landing-three.js` — lightweight Three.js hero scene with an orbital intelligence core and adaptive particles.
- `login.html` / `login.js` — Google OAuth entry point; successful sign-in continues to `index.html`.
- `index.html` / `script.js` — authenticated case selector, file attachments,
  output selection, transformation submission, task polling, live agentic
  progress, wait/quality/telemetry display, cooperative stop/cancellation,
  artifact preview/download, artifact selection, lineage-preserving revision
  commands, approval/resume actions, and output display.
- `styles.css` / `login.css` — visual system and responsive layout.
- `diagram/preview.js` — isolated diagram artifact preview module used by the
  dashboard for `diagram` and `visual.flowchart` artifact projections.

Never put Google secrets, JWTs, provider API keys, or MongoDB credentials in
this directory. The gateway owns those secrets.

When the backend reports that the development process is missing
`OPENAI_API_KEY`, the dashboard displays a one-time session setup dialog. The
key is sent to the authenticated backend and kept only in process memory; it
is not saved in browser storage. Production disables this flow.

Completed artifacts are delivered through the authenticated task artifact
route. Videos and rendered images are previewed in the result panel; PPTX and
Markdown artifacts are opened or downloaded from the same panel. The frontend
stores the last SSE sequence per task in `sessionStorage`, so reconnects ask
the backend for only events after the last acknowledged sequence. Terminal
FastAPI runs also hydrate their artifact manifests through the canonical
manifest endpoint.

## Artifact updates

Use **Revise this artifact** beside a rendered artifact, then describe the
bounded change in the prompt. The frontend submits a new operation with the
parent artifact ID; the original artifact remains immutable and the backend
creates a new version after the normal planning, quality, and approval gates.

Examples:

```text
Revise presentation artifact artifact-deck-v1: change slide 4 title to
"Collection priorities"; preserve all evidence bindings and speaker notes.

Revise video artifact artifact-video-v1: replace scene scene-04 narration
with a 12-second neutral explanation; keep all other scenes unchanged.

Revise infographic artifact artifact-infographic-v1: increase the contrast of
the risk panel without changing any claim or source reference.
```

For an exact field-level repair, include a scope such as
`slides[4].title`, `scenes[04].narration`, or `layout.risk_panel`. The system
uses the selected artifact as `parent_artifact_id`, routes only the requested
output type, and never overwrites sibling artifacts.

The current UI does not yet expose a full parent/child execution graph,
interactive visual repair editor, or audit-log explorer. Those are planned
operator-surface improvements, not backend prerequisites.

## T09 migration boundary

The API client is the first migration boundary for the agentic dashboard. It
normalizes gateway task responses and FastAPI run summaries into the same
projection fields (`task_id`, `run_id`, `status`, `stage`, `progress`,
`event_cursor`, `output_types`, `artifact_manifests`, and quality metadata).
The richer parent/child execution lanes, quality-report views, and durable
cross-session history UI remain follow-up work; callers should consume the
projection instead of depending on either backend's raw response shape.

The projection contract has dependency-free Node tests:

```powershell
node --test .\frontend\tests\api-projection.test.mjs
```
