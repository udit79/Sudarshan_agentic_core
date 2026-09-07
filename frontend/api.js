/* Browser client for the Node/Express gateway. Keep provider credentials out of this file. */
(function installSudarshanApi(global) {
  let configuredOrigin = global.SUDARSHAN_API_ORIGIN || "http://localhost:8080";
  let activeOrigin = configuredOrigin.replace(/\/$/, "");
  let activeMode = "gateway"; // 'gateway' (8080) or 'fastapi' (8000)
  let refreshPromise = null;

  function apiUrl(path) {
    return `${activeOrigin}${path}`;
  }

  async function parseBody(response) {
    const text = await response.text();
    if (!text) return null;
    try { return JSON.parse(text); } catch { return { error: text }; }
  }

  async function readError(response, payload) {
    const error = new Error(payload?.error || payload?.detail || `Request failed (${response.status})`);
    error.status = response.status;
    error.requestId = payload?.request_id || response.headers.get("X-Request-Id") || "";
    error.retryAfter = response.headers.get("Retry-After") || "";
    return error;
  }

  async function checkHealth() {
    // 1. Try Node Gateway (Port 8080)
    try {
      const res = await fetch("http://localhost:8080/api/v1/health", { credentials: "include" });
      if (res.ok) {
        activeOrigin = "http://localhost:8080";
        activeMode = "gateway";
        return { ok: true, origin: activeOrigin, mode: "gateway", data: await parseBody(res) };
      }
    } catch { /* Try Python directly */ }

    // 2. Try Python FastAPI (Port 8000)
    try {
      const res = await fetch("http://localhost:8000/health");
      if (res.ok) {
        activeOrigin = "http://localhost:8000";
        activeMode = "fastapi";
        return { ok: true, origin: activeOrigin, mode: "fastapi", data: await parseBody(res) };
      }
    } catch { /* Both offline */ }

    return { ok: false, origin: activeOrigin, mode: "offline", error: "Backend offline" };
  }

  async function refresh() {
    if (activeMode !== "gateway") return null;
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
    if (activeMode === "fastapi") {
      if (!headers.has("X-Operator-Id")) headers.set("X-Operator-Id", "operator-local");
      if (!headers.has("X-Classification-Level")) headers.set("X-Classification-Level", "RESTRICTED");
    }

    const init = { ...options, credentials: "include", headers };
    if (init.body && typeof init.body !== "string") {
      headers.set("Content-Type", "application/json");
      init.body = JSON.stringify(init.body);
    }

    let response;
    try {
      response = await fetch(apiUrl(path), init);
    } catch (networkErr) {
      // Automatic fallback between 8080 and 8000 if network fails
      if (activeMode === "gateway") {
        try {
          const testFastAPI = await fetch("http://localhost:8000/health");
          if (testFastAPI.ok) {
            activeOrigin = "http://localhost:8000";
            activeMode = "fastapi";
            return request(path, options, false);
          }
        } catch {}
      }
      throw networkErr;
    }

    if (response.status === 401 && canRefresh && path !== "/api/v1/auth/refresh" && activeMode === "gateway") {
      try {
        await refresh();
        return request(path, options, false);
      } catch {}
    }

    const payload = await parseBody(response);
    if (!response.ok) throw await readError(response, payload);
    return payload;
  }

  function googleLogin() {
    global.location.assign(apiUrl("/api/v1/auth/google"));
  }

  const taskToRunMap = new Map();

  function generateIdempotencyKey() {
    if (global.crypto?.randomUUID) return global.crypto.randomUUID();
    return `frontend-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }
  const idempotencyKey = generateIdempotencyKey;

  function subscribeToTask(taskId, onProgress, onError) {
    if (activeMode === "fastapi") {
      const runId = taskToRunMap.get(taskId) || taskId;
      const source = new EventSource(`http://localhost:8000/runs/${encodeURIComponent(runId)}/events`);
      source.addEventListener("progress", (msg) => {
        try { onProgress(JSON.parse(msg.data)); } catch (e) { onProgress(msg.data); }
      });
      source.addEventListener("error", (err) => {
        source.close();
        if (onError) onError(err);
      });
      return () => source.close();
    }

    const source = new EventSource(
      apiUrl(`/api/v1/tasks/${encodeURIComponent(taskId)}/events`),
      { withCredentials: true }
    );
    source.addEventListener("progress", (msg) => {
      try { onProgress(JSON.parse(msg.data)); } catch (e) { onProgress(msg.data); }
    });
    source.addEventListener("error", (err) => {
      source.close();
      if (onError) onError(err);
    });
    return () => source.close();
  }

  global.SudarshanAPI = Object.freeze({
    get apiOrigin() { return activeOrigin; },
    get activeMode() { return activeMode; },
    apiUrl,
    checkHealth,
    request,
    refresh,
    googleLogin,
    subscribeToTask,
    generateIdempotencyKey,
    idempotencyKey,
    getCurrentUser: () => {
      if (activeMode === "fastapi") {
        return Promise.resolve({ user: { id: "operator-local", email: "aarav.sharma@sudarshan.ai", name: "Aarav Sharma" } });
      }
      return request("/api/v1/auth/me");
    },
    logout: () => {
      if (activeMode === "fastapi") return Promise.resolve();
      return request("/api/v1/auth/logout", { method: "POST" }, false);
    },
    listCases: () => {
      if (activeMode === "fastapi") return Promise.resolve({ cases: [] });
      return request("/api/v1/cases");
    },
    getCases: () => {
      if (activeMode === "fastapi") return Promise.resolve({ cases: [] });
      return request("/api/v1/cases");
    },
    createCase: (body) => {
      if (activeMode === "fastapi") return Promise.resolve(body);
      return request("/api/v1/cases", { method: "POST", body });
    },
    createTransform: (body, key = generateIdempotencyKey()) => {
      if (activeMode === "fastapi") {
        // Adapt to FastAPI /runs
        return request("/runs", {
          method: "POST",
          headers: {
            "X-Operator-Id": "operator-local",
            "X-Classification-Level": body.classification_level || "RESTRICTED",
          },
          body: {
            query: body.input,
            user_id: "operator-local",
            requested_pipelines: body.output_types,
            case_id: body.case_id || "case-default",
            classification_level: body.classification_level || "RESTRICTED",
            distribution: body.distribution || "Authorized NTRO personnel",
            task_id: body.task_id || `task-${Date.now()}`,
          }
        }).then((res) => {
          if (res.task_id && res.run_id) {
            taskToRunMap.set(res.task_id, res.run_id);
          }
          return {
            task_id: res.task_id || res.run_id,
            run_id: res.run_id,
            status: res.status || "queued",
            output_types: body.output_types,
            result: res.result || res.response || null,
          };
        });
      }

      return request("/api/v1/transform", {
        method: "POST",
        headers: { "Idempotency-Key": key },
        body,
      });
    },
    getTask: (taskId) => {
      if (activeMode === "fastapi") {
        const targetId = taskToRunMap.get(taskId) || taskId;
        return request(`/runs/${encodeURIComponent(targetId)}`).then((res) => ({
          task: {
            task_id: res.task_id || taskId,
            run_id: res.run_id || targetId,
            status: res.status,
            stage: res.stage || null,
            output_types: res.pipelines || (res.pipeline ? [res.pipeline] : []),
            result: res.responses || (res.response ? { [res.response.pipeline || "output"]: res.response } : null),
            error: res.error || null,
          }
        }));
      }
      return request(`/api/v1/tasks/${encodeURIComponent(taskId)}`);
    },
    cancelTask: (taskId) => {
      if (activeMode === "fastapi") return Promise.resolve({ status: "cancelled" });
      return request(`/api/v1/tasks/${encodeURIComponent(taskId)}/cancel`, { method: "POST" });
    },
    getUsage: () => {
      if (activeMode === "fastapi") return Promise.resolve({ usage: {} });
      return request("/api/v1/usage");
    },
  });
}(window));
