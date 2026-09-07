import crypto from "node:crypto";
import fs from "node:fs";
import express from "express";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { authMiddleware, currentUser, googleCallback, logout, refreshSession, startGoogle } from "./auth.js";
import { Case, Task, User } from "./models.js";
import { cancelRun, configureRuntime, getPythonHealth, ingestSource, resumeRun, streamRunEvents } from "./python-client.js";
import { createTransformation, getTaskForUser, listTasksForUser, assertCaseOwnership, safeTask } from "./tasks.js";
import { caseSchema, parse, resumeSchema, transformSchema } from "./validation.js";

const router = express.Router();
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const artifactRoot = path.resolve(repoRoot, "artifacts");

function artifactCandidates(task, artifactKey) {
  const result = task.result && typeof task.result === "object" ? task.result : {};
  const response = result[artifactKey] || result[artifactKey === "presentation" ? "ppt" : artifactKey];
  const output = response?.output || {};
  const artifact = response?.artifact || {};
  const candidates = [];
  if (artifactKey === "video") candidates.push(artifact.video_path, artifact.path);
  if (artifactKey === "presentation") candidates.push(artifact.path);
  if (artifactKey === "infographic") candidates.push(output.artifact_path, artifact.path);
  if (artifactKey === "linkedin_post") candidates.push(output.image?.asset_uri, artifact.path);
  candidates.push(artifact.path, output.artifact_path);
  return candidates.filter((candidate) => typeof candidate === "string" && candidate.trim());
}

function resolveArtifactPath(candidate) {
  if (/^https?:\/\//i.test(candidate)) return null;
  const resolved = path.resolve(repoRoot, candidate);
  if (resolved !== artifactRoot && !resolved.startsWith(`${artifactRoot}${path.sep}`)) return null;
  return resolved;
}

router.get("/auth/google", startGoogle);
router.get("/auth/google/callback", googleCallback);
router.post("/auth/refresh", refreshSession);
router.get("/auth/me", authMiddleware, currentUser);
// Logout must remain available after access-token expiry so the browser can
// always clear its refresh cookie and revoke the server-side token.
router.post("/auth/logout", logout);

router.get("/health", async (req, res, next) => {
  try {
    const python = await getPythonHealth();
    res.json({
      status: "ok",
      database: "connected",
      python_api: python.status || "ok",
      configuration: python.configuration || {},
    });
  } catch (error) {
    next(error);
  }
});

router.use(authMiddleware);

router.post("/config/session", async (req, res, next) => {
  try {
    const apiKey = String(req.body?.openai_api_key || "").trim();
    if (!apiKey) return res.status(422).json({ error: "openai_api_key is required" });
    const result = await configureRuntime({ userId: req.auth.sub, openaiApiKey: apiKey });
    return res.json(result);
  } catch (error) {
    return next(error);
  }
});

router.post("/ingest", async (req, res, next) => {
  try {
    const caseId = String(req.get("X-Case-Id") || "").trim();
    if (!caseId) return res.status(422).json({ error: "case_id is required for upload" });
    await assertCaseOwnership(req.auth.sub, caseId);
    const result = await ingestSource({
      request: req,
      userId: req.auth.sub,
      caseId,
      taskId: String(req.get("X-Task-Id") || "").trim(),
      classificationLevel: String(req.get("X-Classification-Level") || "RESTRICTED").trim(),
    });
    return res.status(201).json(result);
  } catch (error) {
    return next(error);
  }
});

router.get("/tasks/:taskId/artifacts/:artifactKey", async (req, res, next) => {
  try {
    const task = await getTaskForUser(req.auth.sub, req.params.taskId);
    const key = String(req.params.artifactKey || "").trim().toLowerCase();
    const candidate = artifactCandidates(task, key)
      .map(resolveArtifactPath)
      .find((filePath) => filePath && fs.existsSync(filePath));
    if (!candidate) return res.status(404).json({ error: "Artifact is not available for this task" });
    return res.sendFile(candidate);
  } catch (error) {
    return next(error);
  }
});

router.post("/cases", async (req, res, next) => {
  try {
    const body = parse(caseSchema, req.body);
    const ownerId = req.auth.sub;
    const created = await Case.findOneAndUpdate(
      { ownerId, caseId: body.case_id },
      {
        $set: {
          name: body.name,
          classificationLevel: body.classification_level,
          distribution: body.distribution,
        },
        $setOnInsert: { ownerId, caseId: body.case_id },
      },
      { new: true, upsert: true, runValidators: true },
    );
    res.status(201).json({
      case_id: created.caseId,
      name: created.name,
      classification_level: created.classificationLevel,
      distribution: created.distribution,
    });
  } catch (error) {
    next(error);
  }
});

router.get("/cases", async (req, res, next) => {
  try {
    const cases = await Case.find({ ownerId: req.auth.sub }).sort({ updatedAt: -1 }).lean();
    res.json({ cases: cases.map((item) => ({
      case_id: item.caseId,
      name: item.name,
      classification_level: item.classificationLevel,
      distribution: item.distribution,
      created_at: item.createdAt,
      updated_at: item.updatedAt,
    })) });
  } catch (error) {
    next(error);
  }
});

router.post("/transform", async (req, res, next) => {
  try {
    const body = parse(transformSchema, req.body);
    if (body.user_id && body.user_id !== req.auth.sub) {
      return res.status(403).json({ error: "user_id must match the authenticated user" });
    }
    const idempotencyKey = String(req.get("Idempotency-Key") || "").trim().slice(0, 200);
    const wait = ["1", "true", "yes"].includes(String(req.query.wait || "").toLowerCase());
    const result = await createTransformation({ user: await User.findById(req.auth.sub), body, idempotencyKey, wait, res });
    return res.status(result.statusCode).json(result.body);
  } catch (error) {
    return next(error);
  }
});

router.get("/tasks", async (req, res, next) => {
  try {
    const tasks = await listTasksForUser(req.auth.sub);
    res.json({ tasks: tasks.map(safeTask) });
  } catch (error) {
    next(error);
  }
});

router.get("/tasks/:taskId", async (req, res, next) => {
  try {
    const task = await getTaskForUser(req.auth.sub, req.params.taskId);
    res.json({ task: safeTask(task) });
  } catch (error) {
    next(error);
  }
});

router.post("/tasks/:taskId/resume", async (req, res, next) => {
  try {
    const task = await getTaskForUser(req.auth.sub, req.params.taskId);
    if (!task.runId) return res.status(409).json({ error: "Task has not been accepted by the Python API yet" });
    const decision = parse(resumeSchema, req.body);
    const result = await resumeRun({ runId: task.runId, taskId: task.taskId, decision, userId: req.auth.sub });
    const refreshed = await getTaskForUser(req.auth.sub, req.params.taskId);
    res.json({ task: safeTask(refreshed), run: result });
  } catch (error) {
    next(error);
  }
});

router.post("/tasks/:taskId/cancel", async (req, res, next) => {
  try {
    const task = await getTaskForUser(req.auth.sub, req.params.taskId);
    if (!task.runId) return res.status(409).json({ error: "Task has not been accepted by the Python API yet" });
    const result = await cancelRun({ runId: task.runId, taskId: task.taskId, userId: req.auth.sub });
    const refreshed = await getTaskForUser(req.auth.sub, req.params.taskId);
    res.json({ task: safeTask(refreshed), run: result });
  } catch (error) {
    next(error);
  }
});

router.get("/tasks/:taskId/events", async (req, res, next) => {
  try {
    const task = await getTaskForUser(req.auth.sub, req.params.taskId);
    if (!task.runId) return res.status(409).json({ error: "Task has not been accepted by the Python API yet" });
    await streamRunEvents(task.runId, res);
  } catch (error) {
    if (!res.headersSent) next(error);
  }
});

router.get("/usage", async (req, res, next) => {
  try {
    const [aggregate, requests] = await Promise.all([
      Task.aggregate([
        { $match: { userId: req.auth.sub } },
        { $group: { _id: null, input: { $sum: "$inputTokens" }, output: { $sum: "$outputTokens" }, total: { $sum: "$totalTokens" } } },
      ]),
      Task.countDocuments({ userId: req.auth.sub }),
    ]);
    const usage = aggregate[0] || { input: 0, output: 0, total: 0 };
    res.json({ input_tokens: usage.input, output_tokens: usage.output, total_tokens: usage.total, requests });
  } catch (error) {
    next(error);
  }
});

export default router;
