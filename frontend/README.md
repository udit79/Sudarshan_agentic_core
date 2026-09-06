# Sudarshan frontend

This is a dependency-free static frontend for the Node/Express gateway in
`../backend-node`. It uses Google OAuth through HttpOnly cookies, loads
user-owned cases, submits selected output pipelines, polls task status, shows
token usage and renders transformed output as text.

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
  errors, and idempotency keys.
- `login.html` / `login.js` — Google OAuth entry point.
- `index.html` / `script.js` — authenticated case selector, output selection,
  transformation submission, task polling, cancellation, and output display.
- `styles.css` / `login.css` — visual system and responsive layout.

Never put Google secrets, JWTs, provider API keys, or MongoDB credentials in
this directory. The gateway owns those secrets.
