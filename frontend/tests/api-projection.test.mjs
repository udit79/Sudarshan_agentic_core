import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

const apiSource = readFileSync(new URL("../api.js", import.meta.url), "utf8");

function createApi() {
  const values = new Map();
  const sessionStorage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
  };
  const window = {
    SUDARSHAN_API_ORIGIN: "http://gateway.test",
    sessionStorage,
  };
  const sandbox = { window };
  vm.runInNewContext(apiSource, sandbox, { filename: "frontend/api.js" });
  return { api: window.SudarshanAPI, sessionStorage };
}

test("normalizes gateway and FastAPI run shapes into one projection", () => {
  const { api } = createApi();
  const projection = api.normalizeRunProjection({
    task: {
      task_id: "task-1",
      run_id: "run-1",
      summary: {
        status: "running",
        stage: "rendering",
        progress: 58,
        quality_status: "pending",
        child_count: 3,
      },
      output_types: ["presentation", "infographic"],
      event_cursor: 12,
      approval: { required: true, status: "pending" },
      connector: { provider: "manual", status: "draft_only" },
      humanizer_report: { approved: true, issues: [] },
      schedule: { status: "not_scheduled" },
    },
  });

  assert.equal(projection.task_id, "task-1");
  assert.equal(projection.run_id, "run-1");
  assert.equal(projection.status, "running");
  assert.equal(projection.stage, "rendering");
  assert.equal(projection.progress, 58);
  assert.deepEqual(projection.output_types, ["presentation", "infographic"]);
  assert.equal(projection.event_cursor, 12);
  assert.equal(projection.quality_status, "pending");
  assert.equal(projection.child_count, 3);
  assert.equal(projection.approval.status, "pending");
  assert.equal(projection.connector.provider, "manual");
  assert.equal(projection.humanizer.approved, true);
  assert.equal(projection.schedule.status, "not_scheduled");
});

test("event cursor is persisted and SSE resumes after the newest sequence", () => {
  const sources = [];
  class FakeEventSource {
    constructor(url) {
      this.url = url;
      this.listeners = new Map();
      sources.push(this);
    }

    addEventListener(type, listener) {
      this.listeners.set(type, listener);
    }

    emit(type, payload) {
      this.listeners.get(type)?.({ data: JSON.stringify(payload) });
    }

    close() {}
  }

  const values = new Map();
  const sessionStorage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
  };
  const window = { SUDARSHAN_API_ORIGIN: "http://gateway.test", sessionStorage };
  const sandbox = { window, EventSource: FakeEventSource };
  vm.runInNewContext(apiSource, sandbox, { filename: "frontend/api.js" });

  const received = [];
  const close = window.SudarshanAPI.subscribeToTask("task-2", (payload) => received.push(payload));
  assert.match(sources[0].url, /after_sequence=0$/);
  sources[0].emit("progress", {
    task_id: "task-2",
    sequence: 9,
    status: "running",
    stage: "planning",
    progress: 20,
  });
  close();

  assert.equal(window.SudarshanAPI.getEventCursor("task-2"), 9);
  assert.equal(received[0].event_cursor, 9);

  window.SudarshanAPI.subscribeToTask("task-2", () => {});
  assert.match(sources[1].url, /after_sequence=9$/);
});

test("artifact routes are derived from the active backend mode", () => {
  const { api } = createApi();
  assert.equal(
    api.artifactManifestUrl("task-3", "presentation"),
    "http://gateway.test/api/v1/tasks/task-3/artifacts/presentation/manifest",
  );
  assert.equal(
    api.artifactPreviewUrl("task-3", "presentation"),
    "http://gateway.test/api/v1/tasks/task-3/artifacts/presentation/preview",
  );
});
