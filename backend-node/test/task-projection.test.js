import test from "node:test";
import assert from "node:assert/strict";
import crypto from "node:crypto";

process.env.MONGODB_URI ||= "mongodb://127.0.0.1:27017/sudarshan_test";
process.env.JWT_ACCESS_SECRET ||= "test-access-secret-test-access-secret";
process.env.JWT_REFRESH_SECRET ||= "test-refresh-secret-test-refresh-secret";

const {
  idempotencyRequestMatches,
  isTransientPythonError,
  projectCanonicalStatus,
  safeTask,
} = await import("../src/tasks.js");

test("safeTask exposes the canonical run projection and artifact cursor", () => {
  const projected = safeTask({
    taskId: "task-1",
    runId: "run-1",
    caseId: "case-1",
    inputPreview: "brief",
    outputTypes: ["presentation"],
    status: "waiting_for_approval",
    runSummary: {
      run_id: "run-1",
      status: "waiting_for_approval",
      stage: "quality_check",
      progress: 90,
    },
    eventSequence: 12,
    artifactManifests: [{ artifact_id: "artifact-1", kind: "presentation" }],
    classificationLevel: "RESTRICTED",
    distribution: "Authorized NTRO personnel",
    error: null,
    inputTokens: 10,
    outputTokens: 0,
    totalTokens: 10,
    createdAt: "2026-01-01T00:00:00.000Z",
    updatedAt: "2026-01-01T00:00:01.000Z",
  });

  assert.equal(projected.summary.status, "waiting_for_approval");
  assert.equal(projected.event_cursor, 12);
  assert.equal(projected.artifact_manifests[0].artifact_id, "artifact-1");
  assert.equal(projected.classification_level, "RESTRICTED");
});

test("partial canonical status preserves the latest result and advances the cursor", () => {
  const projection = projectCanonicalStatus(
    { status: "running", eventSequence: 4 },
    {
      status: "partial",
      summary: { status: "partial", stage: "completed", progress: 100 },
      responses: { advisory: { pipeline: "advisory", status: "succeeded" } },
      events: [{ sequence: 5 }, { sequence: 7 }],
    },
  );

  assert.equal(projection.effectiveStatus, "partial");
  assert.equal(projection.eventSequence, 7);
  assert.equal(projection.result.advisory.status, "succeeded");
});

test("idempotency includes classification and distribution boundaries", () => {
  const query = "brief the case";
  const task = {
    inputHash: crypto.createHash("sha256").update(query).digest("hex"),
    outputTypes: ["advisory"],
    classificationLevel: "RESTRICTED",
    distribution: "Authorized NTRO personnel",
  };

  assert.equal(idempotencyRequestMatches(task, {
    query,
    outputTypes: ["advisory"],
    classificationLevel: "RESTRICTED",
    distribution: "Authorized NTRO personnel",
  }), true);
  assert.equal(idempotencyRequestMatches(task, {
    query,
    outputTypes: ["advisory"],
    classificationLevel: "SECRET",
    distribution: "Authorized NTRO personnel",
  }), false);
});

test("transient Python failures preserve the gateway projection for retry", () => {
  assert.equal(isTransientPythonError({ status: 503 }), true);
  assert.equal(isTransientPythonError({ status: 504 }), true);
  assert.equal(isTransientPythonError({ name: "AbortError" }), true);
  assert.equal(isTransientPythonError({ status: 422 }), false);
});
