/* Browser client for the Node/Express gateway. Keep provider credentials out of this file. */
(function installSudarshanApi(global) {
  const configuredOrigin = global.SUDARSHAN_API_ORIGIN || "http://localhost:8080";
  const apiOrigin = configuredOrigin.replace(/\/$/, "");
  let refreshPromise = null;

  function apiUrl(path) {
    return `${apiOrigin}${path}`;
  }

  async function parseBody(response) {
    const text = await response.text();
    if (!text) return null;
    try { return JSON.parse(text); } catch { return { error: text }; }
  }

  async function readError(response, payload) {
    const error = new Error(payload?.error || `Request failed (${response.status})`);
    error.status = response.status;
    error.requestId = payload?.request_id || response.headers.get("X-Request-Id") || "";
    error.retryAfter = response.headers.get("Retry-After") || "";
    return error;
  }

  async function refresh() {
    if (!refreshPromise) {
      refreshPromise = fetch(apiUrl("/api/v1/auth/refresh"), {
        method: "POST",
        credentials: "include",
        headers: { Accept: "application/json" },
      }).then(async (response) => {
        const payload = await parseBody(response);
        if (!response.ok) throw await readError(response, payload);
        return payload;
      }).finally(() => { refreshPromise = null; });
    }
    return refreshPromise;
  }

  async function request(path, options = {}, canRefresh = true) {
    const headers = new Headers(options.headers || {});
    headers.set("Accept", "application/json");
    const init = { ...options, credentials: "include", headers };
    if (init.body && typeof init.body !== "string") {
      headers.set("Content-Type", "application/json");
      init.body = JSON.stringify(init.body);
    }
    const response = await fetch(apiUrl(path), init);
    if (response.status === 401 && canRefresh && path !== "/api/v1/auth/refresh") {
      try {
        await refresh();
        return request(path, options, false);
      } catch { /* The caller handles the original authentication failure. */ }
    }
    const payload = await parseBody(response);
    if (!response.ok) throw await readError(response, payload);
    return payload;
  }

  function googleLogin() {
    global.location.assign(apiUrl("/api/v1/auth/google"));
  }

  function idempotencyKey() {
    if (global.crypto?.randomUUID) return global.crypto.randomUUID();
    return `frontend-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  global.SudarshanAPI = Object.freeze({
    apiOrigin,
    apiUrl,
    request,
    refresh,
    googleLogin,
    getCurrentUser: () => request("/api/v1/auth/me"),
    logout: () => request("/api/v1/auth/logout", { method: "POST" }, false),
    listCases: () => request("/api/v1/cases"),
    createCase: (body) => request("/api/v1/cases", { method: "POST", body }),
    createTransform: (body, key = idempotencyKey()) => request("/api/v1/transform", {
      method: "POST",
      headers: { "Idempotency-Key": key },
      body,
    }),
    getTask: (taskId) => request(`/api/v1/tasks/${encodeURIComponent(taskId)}`),
    cancelTask: (taskId) => request(`/api/v1/tasks/${encodeURIComponent(taskId)}/cancel`, { method: "POST" }),
    getUsage: () => request("/api/v1/usage"),
  });
}(window));
