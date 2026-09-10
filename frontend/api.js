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

  async function multipartRequest(path, formData, headers = {}, canRefresh = true) {
    const requestHeaders = new Headers(headers);
    requestHeaders.set("Accept", "application/json");
    const response = await fetch(apiUrl(path), {
      method: "POST",
      credentials: "include",
      headers: requestHeaders,
      body: formData,
    });
    if (response.status === 401 && canRefresh && activeMode === "gateway") {
      try {
        await refresh();
        return multipartRequest(path, formData, headers, false);
      } catch { /* surface the original authentication error below */ }
    }
    const payload = await parseBody(response);
    if (!response.ok) throw await readError(response, payload);
    return payload;
  }

  function googleLogin() {
    global.location.assign(apiUrl("/api/v1/auth/google"));
  }

  const taskToRunMap = new Map();

  function readEventCursor(taskId) {
    const fallback = 0;
    try {
      const value = Number(global.sessionStorage?.getItem(`sudarshan:event-cursor:${taskId}`));
      return Number.isSafeInteger(value) && value >= 0 ? value : fallback;
    } catch {
      return fallback;
    }
  }

  function writeEventCursor(taskId, sequence) {
    const value = Number(sequence || 0);
    if (!Number.isSafeInteger(value) || value < 0) return readEventCursor(taskId);
    const next = Math.max(readEventCursor(taskId), value);
    try { global.sessionStorage?.setItem(`sudarshan:event-cursor:${taskId}`, String(next)); } catch { /* optional */ }
    return next;
  }

  function normalizeRunProjection(payload, fallback = {}) {
    const raw = payload?.task || payload?.run || payload || {};
    const summary = raw.summary || raw.run_summary || raw.runSummary || payload?.summary || null;
    const responseMap = raw.result || raw.responses || payload?.responses || null;
    const singleResponse = raw.response || payload?.response || null;
    const outputTypes = raw.output_types
      || raw.outputTypes
      || summary?.requested_pipelines
      || (summary?.skill_id ? [summary.skill_id] : null)
      || fallback.output_types
      || [];
    const eventCursor = Math.max(
      Number(raw.event_cursor || raw.eventSequence || 0),
      Number(summary?.event_sequence || summary?.eventSequence || 0),
      Number(fallback.event_cursor || 0),
    );
    return {
      ...fallback,
      ...raw,
      task_id: raw.task_id || raw.taskId || fallback.task_id || null,
      run_id: raw.run_id || raw.runId || summary?.run_id || fallback.run_id || null,
      case_id: raw.case_id || raw.caseId || fallback.case_id || null,
      status: summary?.status || raw.status || fallback.status || "queued",
      stage: summary?.stage || raw.stage || fallback.stage || null,
      progress: Number(summary?.progress ?? raw.progress ?? fallback.progress ?? 0),
      message: raw.message || fallback.message || "",
      output_types: Array.isArray(outputTypes) ? outputTypes : [],
      result: responseMap || (singleResponse ? { [singleResponse.pipeline || "output"]: singleResponse } : raw.result || null),
      summary,
      event_cursor: Number.isSafeInteger(eventCursor) ? eventCursor : 0,
      artifact_manifests: raw.artifact_manifests || raw.artifactManifests || [],
      quality_status: summary?.quality_status || raw.quality_status || raw.qualityStatus || "pending",
      requires_action: Boolean(summary?.requires_action ?? raw.requires_action ?? raw.requiresAction ?? false),
      child_count: Number(summary?.child_count ?? raw.child_count ?? 0),
      parent_task_id: raw.parent_task_id || raw.parentTaskId || summary?.parent_task_id || null,
      children: Array.isArray(raw.children) ? raw.children : (Array.isArray(summary?.children) ? summary.children : []),
      quality_report: raw.quality_report || raw.qualityReport || summary?.quality_report || null,
      wait_reason: raw.wait_reason || raw.waitReason || summary?.wait_reason || summary?.waitReason || "",
      error: raw.error || fallback.error || null,
      wait_timed_out: Boolean(raw.wait_timed_out ?? fallback.wait_timed_out ?? false),
    };
  }

  function generateIdempotencyKey() {
    if (global.crypto?.randomUUID) return global.crypto.randomUUID();
    return `frontend-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }
  const idempotencyKey = generateIdempotencyKey;

  function subscribeToTask(taskId, onProgress, onError, options = {}) {
    const initialCursor = Math.max(readEventCursor(taskId), Number(options.afterSequence || 0));
    const cursorQuery = `?after_sequence=${encodeURIComponent(initialCursor)}`;
    const handleProgress = (msg) => {
      try {
        const payload = JSON.parse(msg.data);
        if (payload?.sequence != null) writeEventCursor(taskId, payload.sequence);
        onProgress(normalizeRunProjection(payload, { task_id: taskId, event_cursor: readEventCursor(taskId) }));
      } catch (e) {
        onProgress(msg.data);
      }
    };
    if (activeMode === "fastapi") {
      const runId = taskToRunMap.get(taskId) || taskId;
      const source = new EventSource(`http://localhost:8000/runs/${encodeURIComponent(runId)}/events${cursorQuery}`);
      source.addEventListener("progress", handleProgress);
      source.addEventListener("error", (err) => {
        source.close();
        if (onError) onError(err);
      });
      return () => source.close();
    }

    const source = new EventSource(
      apiUrl(`/api/v1/tasks/${encodeURIComponent(taskId)}/events${cursorQuery}`),
      { withCredentials: true }
    );
    source.addEventListener("progress", handleProgress);
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
    normalizeRunProjection,
    getEventCursor: readEventCursor,
    artifactUrl: (taskId, artifactKey) => activeMode === "fastapi"
      ? `http://localhost:8000/artifacts/${encodeURIComponent(taskId)}/${encodeURIComponent(artifactKey)}`
      : apiUrl(`/api/v1/tasks/${encodeURIComponent(taskId)}/artifacts/${encodeURIComponent(artifactKey)}`),
    artifactManifestUrl: (taskId, artifactKey) => activeMode === "fastapi"
      ? `http://localhost:8000/artifacts/${encodeURIComponent(taskId)}/${encodeURIComponent(artifactKey)}/manifest`
      : apiUrl(`/api/v1/tasks/${encodeURIComponent(taskId)}/artifacts/${encodeURIComponent(artifactKey)}/manifest`),
    artifactPreviewUrl: (taskId, artifactKey) => activeMode === "fastapi"
      ? `http://localhost:8000/artifacts/${encodeURIComponent(taskId)}/${encodeURIComponent(artifactKey)}/preview`
      : apiUrl(`/api/v1/tasks/${encodeURIComponent(taskId)}/artifacts/${encodeURIComponent(artifactKey)}/preview`),
    configureSession: (openaiApiKey) => {
      if (activeMode === "fastapi") {
        return request("/config/session", {
          method: "POST",
          headers: { "X-Operator-Id": "operator-local" },
          body: { openai_api_key: openaiApiKey },
        });
      }
      return request("/api/v1/config/session", {
        method: "POST",
        body: { openai_api_key: openaiApiKey },
      });
    },
    checkHealth,
    request,
    refresh,
    googleLogin,
    subscribeToTask,
    generateIdempotencyKey,
    idempotencyKey,
    getCurrentUser: () => {
      if (activeMode === "fastapi") {
        return Promise.resolve({ user: { id: "operator-local", email: "", name: "Sudarshan Operator" } });
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
    ensureCase: async (caseId, name = "Untitled case") => {
      if (activeMode === "fastapi") return { case_id: caseId, name };
      const existing = await request("/api/v1/cases");
      const found = (existing?.cases || []).find((item) => (item.case_id || item.caseId) === caseId);
      if (found) return found;
      try {
        return await request("/api/v1/cases", { method: "POST", body: { case_id: caseId, name } });
      } catch (error) {
        if (error.status === 409) return { case_id: caseId, name };
        throw error;
      }
    },
    ingestFile: (file, { caseId, taskId, classificationLevel = "RESTRICTED" } = {}) => {
      const form = new FormData();
      form.append("file", file, file.name);
      form.append("case_id", caseId || "");
      form.append("task_id", taskId || `ingest-${Date.now()}`);
      form.append("classification_level", classificationLevel);
      if (activeMode === "fastapi") {
        return multipartRequest("/ingest", form, {
          "X-Operator-Id": "operator-local",
          "X-Case-Id": caseId || "",
          "X-Classification-Level": classificationLevel,
        });
      }
      return multipartRequest("/api/v1/ingest", form, {
        "X-Case-Id": caseId || "",
        "X-Classification-Level": classificationLevel,
        "X-Task-Id": taskId || "",
      });
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
          return normalizeRunProjection(res, {
            task_id: res.task_id || res.run_id,
            run_id: res.run_id,
            status: res.status || "queued",
            output_types: body.output_types,
          });
        });
      }

      return request("/api/v1/transform", {
        method: "POST",
        headers: { "Idempotency-Key": key },
        body,
      }).then((res) => res?.task
        ? { ...res, task: normalizeRunProjection(res.task) }
        : normalizeRunProjection(res));
    },
    getTask: (taskId) => {
      if (activeMode === "fastapi") {
        const targetId = taskToRunMap.get(taskId) || taskId;
        return request(`/runs/${encodeURIComponent(targetId)}`).then(async (res) => {
          const normalized = normalizeRunProjection(res, {
            task_id: res.task_id || taskId,
            run_id: res.run_id || targetId,
            output_types: res.pipelines || (res.pipeline ? [res.pipeline] : []),
          });
          if (["succeeded", "partial", "failed", "cancelled", "completed"].includes(normalized.status)) {
            const manifests = await Promise.all(normalized.output_types.map(async (type) => {
              const key = type === "ppt" ? "presentation" : type;
              try {
                return await request(`/artifacts/${encodeURIComponent(targetId)}/${encodeURIComponent(key)}/manifest`);
              } catch {
                return null;
              }
            }));
            normalized.artifact_manifests = manifests.filter(Boolean);
          }
          return { task: normalized };
        });
      }
      return request(`/api/v1/tasks/${encodeURIComponent(taskId)}`).then((res) => ({
        ...res,
        task: normalizeRunProjection(res?.task || res, { task_id: taskId }),
      }));
    },
    getArtifactManifest: (taskId, artifactKey) => {
      const targetId = activeMode === "fastapi" ? (taskToRunMap.get(taskId) || taskId) : taskId;
      return request(
        activeMode === "fastapi"
          ? `/artifacts/${encodeURIComponent(targetId)}/${encodeURIComponent(artifactKey)}/manifest`
          : `/api/v1/tasks/${encodeURIComponent(targetId)}/artifacts/${encodeURIComponent(artifactKey)}/manifest`,
      );
    },
    listTasks: () => {
      if (activeMode === "fastapi") return Promise.resolve({ tasks: [] });
      return request("/api/v1/tasks").then((res) => ({
        ...res,
        tasks: (res?.tasks || []).map((task) => normalizeRunProjection(task)),
      }));
    },
    cancelTask: (taskId) => {
      if (activeMode === "fastapi") {
        const runId = taskToRunMap.get(taskId) || taskId;
        return request(`/runs/${encodeURIComponent(runId)}/cancel`, {
          method: "POST",
          headers: { "X-Operator-Id": "operator-local" },
          body: { task_id: taskId },
        });
      }
      return request(`/api/v1/tasks/${encodeURIComponent(taskId)}/cancel`, { method: "POST" });
    },
    getUsage: () => {
      if (activeMode === "fastapi") return Promise.resolve({ usage: {} });
      return request("/api/v1/usage");
    },
  });
}(window));
