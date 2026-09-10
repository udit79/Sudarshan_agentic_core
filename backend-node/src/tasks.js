import crypto from "node:crypto";
import { Case, Task } from "./models.js";
import { config } from "./config.js";
import { countResultTokens, countTokens } from "./tokens.js";
import { createRun, getRunArtifactManifest, getRunStatus } from "./python-client.js";
import { finalizeQuota, releaseQuota, reserveQuota, quotaHeaders } from "./rate-limit.js";

const TERMINAL = new Set(["succeeded", "partial", "failed", "cancelled", "completed"]);

function inputText(value) {
  if (typeof value === "string") return value.trim();
  return JSON.stringify(value ?? "");
}

export function safeTask(task) {
  return {
    task_id: task.taskId,
    run_id: task.runId || null,
    case_id: task.caseId,
    prompt: task.inputPreview,
    output_types: task.outputTypes,
    status: task.status,
    summary: task.runSummary || null,
    event_cursor: Number(task.eventSequence || 0),
    artifact_manifests: Array.isArray(task.artifactManifests) ? task.artifactManifests : [],
    classification_level: task.classificationLevel || "RESTRICTED",
    distribution: task.distribution || "Authorized NTRO personnel",
    result: task.result,
    error: task.error,
    usage: {
      input_tokens: task.inputTokens,
      output_tokens: task.outputTokens,
      total_tokens: task.totalTokens,
    },
    created_at: task.createdAt,
    updated_at: task.updatedAt,
  };
}

export async function listTasksForUser(userId, limit = 30) {
  return Task.find({ userId })
    .sort({ updatedAt: -1 })
    .limit(limit)
    .lean();
}

function resultFromStatus(status) {
  if (status.responses && typeof status.responses === "object") return status.responses;
  if (status.response) return { [status.response.pipeline || "output"]: status.response };
  return null;
}

function eventCursorFromStatus(status) {
  return (Array.isArray(status.events) ? status.events : [])
    .reduce((cursor, event) => Math.max(cursor, Number(event?.sequence || 0)), 0);
}

export function projectCanonicalStatus(task, status) {
  const summary = status.summary || null;
  return {
    effectiveStatus: summary?.status || status.status || task.status,
    summary,
    eventSequence: Math.max(Number(task.eventSequence || 0), eventCursorFromStatus(status)),
    result: resultFromStatus(status),
  };
}

export function idempotencyRequestMatches(task, { query, outputTypes, classificationLevel, distribution }) {
  const requestedHash = crypto.createHash("sha256").update(inputText(query)).digest("hex");
  return task.inputHash === requestedHash
    && JSON.stringify(task.outputTypes) === JSON.stringify(outputTypes)
    && (task.classificationLevel || "RESTRICTED") === (classificationLevel || "RESTRICTED")
    && (task.distribution || "Authorized NTRO personnel") === (distribution || "Authorized NTRO personnel");
}

export function isTransientPythonError(error) {
  return error?.name === "AbortError"
    || [502, 503, 504].includes(Number(error?.status));
}

async function artifactManifestsForTask(task, status) {
  const pipelines = Array.isArray(task.outputTypes) ? task.outputTypes : [];
  const results = await Promise.all(pipelines.map(async (pipeline) => {
    const artifactKey = pipeline === "ppt" ? "presentation" : pipeline;
    try {
      return await getRunArtifactManifest(
        task.runId,
        artifactKey,
        task.classificationLevel || status.classification_level || "RESTRICTED",
      );
    } catch (error) {
      // A pipeline may have no artifact (or may still expose only a typed
      // result). Missing manifests are not a reason to fail the run.
      if (error?.status === 404) return null;
      throw error;
    }
  }));
  return results.filter(Boolean);
}

async function finalizeTask(task, pythonStatus, result, artifactManifests = []) {
  if (!TERMINAL.has(pythonStatus.status)) return task;
  // A terminal orchestration status can legitimately omit the projection
  // when a worker failed during final serialization. Preserve any partial
  // result already stored on the gateway instead of replacing it with null.
  const finalResult = result ?? task.result ?? null;
  const outputTokens = countResultTokens(finalResult);
  const session = await Task.startSession();
  try {
    await session.withTransaction(async () => {
      const current = await Task.findOne({ _id: task._id, usageFinalized: false }).session(session);
      if (!current) return;
      await finalizeQuota(current.userId, current.inputTokens, current.reservedTokens, outputTokens, session, current.reservedAt);
      current.status = pythonStatus.status;
      current.result = finalResult;
      current.runSummary = pythonStatus.summary || null;
      current.eventSequence = eventCursorFromStatus(pythonStatus);
      current.artifactManifests = artifactManifests;
      current.error = pythonStatus.error || null;
      current.outputTokens = outputTokens;
      current.totalTokens = current.inputTokens + outputTokens;
      current.reservedTokens = 0;
      current.usageFinalized = true;
      await current.save({ session });
    });
  } finally {
    await session.endSession();
  }
  return Task.findById(task._id);
}

export async function refreshTask(task) {
  if (!task.runId || TERMINAL.has(task.status)) return task;
  let status;
  try {
    status = await getRunStatus(task.runId);
  } catch (error) {
    // A reconnect or health blip must not erase the last safe gateway
    // projection. The next task read will retry Python reconciliation.
    if (isTransientPythonError(error)) return task;
    throw error;
  }
  const projection = projectCanonicalStatus(task, status);
  const { effectiveStatus, summary, result } = projection;
  if (TERMINAL.has(effectiveStatus)) {
    const manifests = await artifactManifestsForTask(task, status);
    return finalizeTask(task, { ...status, status: effectiveStatus }, result, manifests);
  }
  task.status = effectiveStatus || task.status;
  task.runSummary = summary;
  task.eventSequence = projection.eventSequence;
  if (result) task.result = result;
  await task.save();
  return task;
}

export async function assertCaseOwnership(userId, caseId) {
  const found = await Case.findOne({ ownerId: userId, caseId }).lean();
  if (!found) {
    const error = new Error("Case does not exist or is not owned by the authenticated user");
    error.status = 404;
    throw error;
  }
  return found;
}

export async function createTransformation({ user, body, idempotencyKey, wait, res }) {
  if (!user) {
    const error = new Error("User no longer exists");
    error.status = 401;
    throw error;
  }
  const userId = String(user._id);
  const caseId = body.case_id.trim();
  await assertCaseOwnership(userId, caseId);
  const query = inputText(body.input);
  if (!query) {
    const error = new Error("input must not be empty");
    error.status = 422;
    throw error;
  }
  const outputTypes = body.output_types;
  const inputTokens = countTokens(query);
  const existing = idempotencyKey
    ? await Task.findOne({ userId, idempotencyKey })
    : null;
  if (existing) {
    if (!idempotencyRequestMatches(existing, {
      query,
      outputTypes,
      classificationLevel: body.classification_level,
      distribution: body.distribution,
    })) {
      const error = new Error("Idempotency-Key was already used for a different transformation request");
      error.status = 409;
      throw error;
    }
    const refreshed = await refreshTask(existing);
    quotaHeaders(res, refreshed);
    return { statusCode: 200, body: safeTask(refreshed) };
  }

  const taskId = body.task_id?.trim() || `task-${crypto.randomUUID()}`;
  const reservedAt = new Date();
  const reservation = await reserveQuota(userId, inputTokens);
  if (!reservation.allowed) {
    const error = new Error("Token or request rate limit exceeded");
    error.status = 429;
    error.retryAfter = 60;
    throw error;
  }
  let task;
  try {
    task = await Task.create({
      userId,
      caseId,
      taskId,
      inputHash: crypto.createHash("sha256").update(query).digest("hex"),
      inputPreview: query.slice(0, 1000),
      outputTypes,
      classificationLevel: body.classification_level,
      distribution: body.distribution,
      status: "queued",
      inputTokens,
      reservedTokens: reservation.reservedTokens,
      reservedAt,
      idempotencyKey: idempotencyKey || "",
    });
    const accepted = await createRun({
      userId,
      caseId,
      taskId,
      query,
      outputTypes,
      classificationLevel: body.classification_level,
      distribution: body.distribution,
      metadata: { gateway_task_id: taskId },
    });
    task.runId = accepted.run_id;
    task.status = accepted.status || "queued";
    await task.save();
  } catch (error) {
    await releaseQuota(userId, inputTokens, reservation.reservedTokens, reservedAt);
    if (task) {
      task.status = "failed";
      task.error = error.message || "Python transformation request failed";
      task.reservedTokens = 0;
      task.totalTokens = task.inputTokens;
      task.usageFinalized = true;
      await task.save().catch(() => {});
    }
    if (error.code === 11000 && idempotencyKey) {
      const duplicate = await Task.findOne({ userId, idempotencyKey });
      if (duplicate) return { statusCode: 200, body: safeTask(duplicate) };
    }
    throw error;
  }

  if (wait) {
    const deadline = Date.now() + config.transformWaitTimeoutMs;
    while (Date.now() < deadline && !TERMINAL.has(task.status)) {
      await new Promise((resolve) => setTimeout(resolve, 250));
      task = await refreshTask(task);
    }
  }
  quotaHeaders(res, task);
  return { statusCode: wait && TERMINAL.has(task.status) ? 200 : 202, body: safeTask(task) };
}

export async function getTaskForUser(userId, taskId) {
  const task = await Task.findOne({ userId, taskId });
  if (!task) {
    const error = new Error("Task not found");
    error.status = 404;
    throw error;
  }
  return refreshTask(task);
}
