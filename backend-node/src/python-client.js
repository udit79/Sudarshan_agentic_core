import { config } from "./config.js";

async function request(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), options.timeoutMs || config.pythonApiTimeoutMs);
  try {
    const response = await fetch(`${config.pythonApiBaseUrl}${path}`, {
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      signal: controller.signal,
    });
    const text = await response.text();
    let body = {};
    try { body = text ? JSON.parse(text) : {}; } catch { body = { error: "Python API returned invalid JSON" }; }
    if (!response.ok) {
      const error = new Error(body.detail || body.error || `Python API returned ${response.status}`);
      error.status = response.status;
      throw error;
    }
    return body;
  } finally {
    clearTimeout(timer);
  }
}

export async function createRun({ userId, caseId, taskId, query, outputTypes, classificationLevel, distribution, metadata }) {
  return request("/runs", {
    method: "POST",
    body: JSON.stringify({
      query,
      user_id: userId,
      case_id: caseId,
      task_id: taskId,
      classification_level: classificationLevel,
      distribution,
      requested_pipelines: outputTypes,
      metadata: metadata || {},
    }),
    headers: {
      "X-Operator-Id": userId,
      "X-Case-Id": caseId,
      "X-Classification-Level": classificationLevel,
    },
  });
}

export async function getRunStatus(runId) {
  return request(`/runs/${encodeURIComponent(runId)}`);
}

export async function resumeRun({ runId, taskId, decision, userId }) {
  return request(`/runs/${encodeURIComponent(runId)}/resume`, {
    method: "POST",
    body: JSON.stringify({ ...decision, task_id: taskId }),
    headers: { "X-Operator-Id": userId },
  });
}

export async function cancelRun({ runId, taskId, userId }) {
  return request(`/runs/${encodeURIComponent(runId)}/cancel`, {
    method: "POST",
    body: JSON.stringify({ task_id: taskId }),
    headers: { "X-Operator-Id": userId },
  });
}

export async function getPythonHealth() {
  return request("/health", { timeoutMs: Math.min(config.pythonApiTimeoutMs, 5000) });
}

export async function streamRunEvents(runId, res) {
  const upstream = await fetch(`${config.pythonApiBaseUrl}/runs/${encodeURIComponent(runId)}/events`, {
    headers: { "X-Operator-Id": "gateway" },
    signal: res.req.signal,
  });
  if (!upstream.ok || !upstream.body) {
    const error = new Error(`Python event stream returned ${upstream.status}`);
    error.status = upstream.status;
    throw error;
  }
  res.status(200);
  res.set({ "Content-Type": "text/event-stream", "Cache-Control": "no-cache", Connection: "keep-alive", "X-Accel-Buffering": "no" });
  for await (const chunk of upstream.body) {
    if (res.writableEnded) break;
    res.write(Buffer.from(chunk));
  }
  res.end();
}
