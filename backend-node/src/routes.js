import crypto from "node:crypto";
import { spawn } from "node:child_process";
import fs from "node:fs";
import express from "express";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { authMiddleware, currentUser, googleCallback, logout, refreshSession, startGoogle } from "./auth.js";
import { Case, Task, User } from "./models.js";
import { cancelRun, configureRuntime, getPythonHealth, ingestSource, resumeRun, streamRunEvents } from "./python-client.js";
import { createTransformation, getTaskForUser, listArtifactsForUser, listTasksForUser, assertCaseOwnership, safeTask } from "./tasks.js";
import { caseSchema, parse, resumeSchema, transformSchema } from "./validation.js";

const router = express.Router();
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const artifactRoot = path.resolve(repoRoot, "artifacts");

function artifactCandidates(task, artifactKey) {
  const result = task.result && typeof task.result === "object" ? task.result : {};
  const response = result[artifactKey]
    || result.responses?.[artifactKey]
    || result[artifactKey === "presentation" ? "ppt" : artifactKey]
    || (result.response?.pipeline === artifactKey ? result.response : null)
    || (result.response?.pipeline === "presentation" && artifactKey === "presentation" ? result.response : null)
    || (result.pipeline === artifactKey ? result : null);
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

function infographicResponse(task) {
  const result = task.result && typeof task.result === "object" ? task.result : {};
  return result.infographic
    || result.responses?.infographic
    || (result.response?.pipeline === "infographic" ? result.response : null)
    || (result.pipeline === "infographic" ? result : null)
    || null;
}

function safeSyntaxText(value, limit = 220) {
  return String(value ?? "")
    .replace(/[\r\n]+/g, " ")
    .replace(/["'`]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, limit)
    .replace(/[ ,;:]+$/, "");
}

function rendererSafeInfographicSyntax(output) {
  const original = typeof output?.syntax === "string" ? output.syntax : "";
  const evidence = Array.isArray(output?.evidence) ? output.evidence : [];
  const complexLayout = /^\s*infographic\s*\{/i.test(original) || original.length > 12000;
  if (!complexLayout || !evidence.length) return original;

  const items = [["Brief", safeSyntaxText(output.title || "Sudarshan Infographic")]];
  for (const item of evidence) {
    const id = safeSyntaxText(item.evidence_id || "Evidence", 40);
    const claim = safeSyntaxText(item.claim || "Verified observation", 120);
    let detail = safeSyntaxText(item.evidence_summary || item.claim || "Verified observation");
    if (item.source_reference) detail += ` | Source: ${safeSyntaxText(item.source_reference, 80)}`;
    if (Array.isArray(item.limitations) && item.limitations.length) {
      detail += ` | Gap: ${safeSyntaxText(item.limitations.join("; "), 80)}`;
    }
    items.push([`[${id}] ${claim}`, detail]);
  }
  const caveat = Array.isArray(output?.caveats) ? output.caveats[0] : "";
  if (caveat) items.push(["Caveat", safeSyntaxText(caveat)]);
  return [
    "infographic list-grid-simple",
    "data",
    "  lists",
    ...items.flatMap(([label, desc]) => [
      `    - label ${safeSyntaxText(label)}`,
      `      desc ${safeSyntaxText(desc)}`,
    ]),
  ].join("\n");
}

async function renderInfographicDraft(task) {
  const response = infographicResponse(task);
  const output = response?.output;
  const syntax = rendererSafeInfographicSyntax(output);
  if (!syntax.trim().startsWith("infographic")) return null;

  const rendererScript = path.resolve(repoRoot, "pipelines", "infographic", "antv_renderer", "render.mjs");
  const outputDir = path.resolve(repoRoot, "artifacts", "infographics");
  await fs.promises.mkdir(outputDir, { recursive: true });
  const payload = JSON.stringify({
    syntax,
    outputDir,
    artifactName: `failed-draft-${task.taskId}`,
    width: 1200,
    height: 675,
  });

  return new Promise((resolve) => {
    const child = spawn(process.env.ANTV_NODE_BINARY || "node", [rendererScript], {
      cwd: path.dirname(rendererScript),
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk.toString(); });
    child.stderr.on("data", (chunk) => { stderr += chunk.toString(); });
    const timer = setTimeout(() => {
      child.kill();
      resolve(null);
    }, Number(process.env.ANTV_RENDER_TIMEOUT_SECONDS || 60) * 1000);
    child.once("error", () => {
      clearTimeout(timer);
      resolve(null);
    });
    child.once("close", (code) => {
      clearTimeout(timer);
      if (code !== 0) return resolve(null);
      try {
        const rendered = JSON.parse(stdout);
        const candidate = resolveArtifactPath(rendered.path);
        resolve(candidate && fs.existsSync(candidate) ? candidate : null);
      } catch {
        resolve(null);
      }
    });
    child.stdin.end(payload);
  });
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
    const fallback = !candidate && key === "infographic" ? await renderInfographicDraft(task) : null;
    if (!candidate && !fallback) return res.status(404).json({ error: "Artifact is not available for this task" });
    return res.sendFile(candidate || fallback);
  } catch (error) {
    return next(error);
  }
});

router.get("/tasks/:taskId/artifacts/:artifactKey/manifest", async (req, res, next) => {
  try {
    const task = await getTaskForUser(req.auth.sub, req.params.taskId);
    const key = String(req.params.artifactKey || "").trim().toLowerCase();
    const manifestKey = key === "ppt" ? "presentation" : key;
    const manifest = (task.artifactManifests || []).find(
      (item) => String(item?.kind || "").toLowerCase() === manifestKey,
    );
    if (!manifest) return res.status(404).json({ error: "Artifact manifest is not available for this task" });
    return res.json({
      ...manifest,
      gateway_download_uri: `/api/v1/tasks/${encodeURIComponent(task.taskId)}/artifacts/${encodeURIComponent(key)}`,
      gateway_preview_uri: manifest.preview_uri && /\.(png|jpe?g|gif|webp|svg|mp4|webm|txt|md|json)$/i.test(String(manifest.name || ""))
        ? `/api/v1/tasks/${encodeURIComponent(task.taskId)}/artifacts/${encodeURIComponent(key)}/preview`
        : null,
    });
  } catch (error) {
    return next(error);
  }
});

router.get("/tasks/:taskId/artifacts/:artifactKey/preview", async (req, res, next) => {
  try {
    const task = await getTaskForUser(req.auth.sub, req.params.taskId);
    const key = String(req.params.artifactKey || "").trim().toLowerCase();
    const manifest = (task.artifactManifests || []).find(
      (item) => String(item?.kind || "").toLowerCase() === (key === "ppt" ? "presentation" : key),
    );
    if (!manifest?.preview_uri) return res.status(404).json({ error: "Artifact preview is not available" });
    const candidate = artifactCandidates(task, key === "ppt" ? "presentation" : key)
      .map(resolveArtifactPath)
      .find((filePath) => filePath && fs.existsSync(filePath));
    if (!candidate) return res.status(404).json({ error: "Artifact preview is not available" });
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

router.get("/artifacts", async (req, res, next) => {
  try {
    const artifacts = await listArtifactsForUser(req.auth.sub, {
      caseId: String(req.query.case_id || "").trim(),
      kind: String(req.query.kind || "").trim(),
      limit: req.query.limit,
    });
    res.json({ artifacts });
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
    const rawCursor = Number(req.query.after_sequence ?? req.query.afterSequence ?? 0);
    if (!Number.isSafeInteger(rawCursor) || rawCursor < 0) {
      return res.status(422).json({ error: "after_sequence must be a non-negative integer" });
    }
    await streamRunEvents(task.runId, res, {
      afterSequence: rawCursor,
      classificationLevel: task.classificationLevel || "RESTRICTED",
    });
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
