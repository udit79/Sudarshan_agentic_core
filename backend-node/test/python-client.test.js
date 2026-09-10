import test from "node:test";
import assert from "node:assert/strict";

process.env.MONGODB_URI ||= "mongodb://127.0.0.1:27017/sudarshan_test";
process.env.JWT_ACCESS_SECRET ||= "test-access-secret-test-access-secret";
process.env.JWT_REFRESH_SECRET ||= "test-refresh-secret-test-refresh-secret";

const { streamRunEvents } = await import("../src/python-client.js");

test("streamRunEvents forwards the replay cursor and classification", async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = "";
  let requestedHeaders = {};
  const chunks = [];
  try {
    globalThis.fetch = async (url, options) => {
      requestedUrl = String(url);
      requestedHeaders = options.headers;
      return {
        ok: true,
        body: {
          async *[Symbol.asyncIterator]() {
            yield "event: progress\ndata: {}\n\n";
          },
        },
      };
    };

    const response = {
      req: { signal: new AbortController().signal },
      statusCode: 0,
      headers: {},
      status(code) { this.statusCode = code; },
      set(headers) { this.headers = headers; },
      write(chunk) { chunks.push(Buffer.from(chunk).toString()); },
      end() { this.ended = true; },
    };

    await streamRunEvents("run/1", response, {
      afterSequence: 17,
      classificationLevel: "CONFIDENTIAL",
    });

    assert.match(requestedUrl, /\/runs\/run%2F1\/events\?after_sequence=17$/);
    assert.equal(requestedHeaders["X-Classification-Level"], "CONFIDENTIAL");
    assert.equal(response.statusCode, 200);
    assert.equal(response.ended, true);
    assert.equal(chunks.length, 1);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
