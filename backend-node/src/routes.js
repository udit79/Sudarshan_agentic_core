import crypto from "node:crypto";
import express from "express";
import { authMiddleware, currentUser, googleCallback, logout, refreshSession, startGoogle } from "./auth.js";
import { toCaseDocument } from "./case-payload.js";
import { Case, Task, User } from "./models.js";
import { cancelRun, getPythonHealth, resumeRun, streamRunEvents } from "./python-client.js";
import { createTransformation, getTaskForUser, assertCaseOwnership, safeTask } from "./tasks.js";
import { caseSchema, parse, resumeSchema, transformSchema } from "./validation.js";

const router = express.Router();

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
    res.json({ status: "ok", database: "connected", python_api: python.status || "ok" });
  } catch (error) {
    next(error);
  }
});

router.use(authMiddleware);

router.post("/cases", async (req, res, next) => {
  try {
    const body = parse(caseSchema, req.body);
    const ownerId = req.auth.sub;
    // Translate the public snake_case contract to the Mongoose camelCase model.
    const created = await Case.create(toCaseDocument(body, ownerId));
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
