# Sudarshan frontend

This is a dependency-free static frontend for the Node/Express gateway in
`../backend-node`. It uses Google OAuth through HttpOnly cookies, loads
user-owned cases, adds source files to case memory, submits selected output
pipelines, polls task status, and renders transformed output as text. The
result panel's Stop action requests cooperative cancellation at a safe
orchestration boundary; it is not a resumable provider pause.

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

Open `http://localhost:3000/login.html`. Do not open the HTML files with
`file://`; browser cookies and CORS require an HTTP origin.

The gateway defaults to `http://localhost:8080`. To use another gateway,
define `window.SUDARSHAN_API_ORIGIN` before `api.js` in both HTML files:

```html
<script>window.SUDARSHAN_API_ORIGIN = "https://api.example.com";</script>
<script src="api.js"></script>
```

## Frontend structure

- `api.js` — shared gateway client, cookie credentials, one-refresh retry,
  multipart source upload, errors, and idempotency keys.
- `login.html` / `login.js` — Google OAuth entry point.
- `index.html` / `script.js` — authenticated case selector, file attachments,
  output selection, transformation submission, task polling, live agentic
  progress, cooperative stop/cancellation, and output display.
- `styles.css` / `login.css` — visual system and responsive layout.

Never put Google secrets, JWTs, provider API keys, or MongoDB credentials in
this directory. The gateway owns those secrets.

When the backend reports that the development process is missing
`OPENAI_API_KEY`, the dashboard displays a one-time session setup dialog. The
key is sent to the authenticated backend and kept only in process memory; it
is not saved in browser storage. Production disables this flow.

Completed artifacts are delivered through the authenticated task artifact
route. Videos and rendered images are previewed in the result panel; PPTX and
Markdown artifacts are opened or downloaded from the same panel.
