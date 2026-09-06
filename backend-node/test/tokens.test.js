import test from "node:test";
import assert from "node:assert/strict";
import { countResultTokens, countTokens } from "../src/tokens.js";

test("token accounting is deterministic for strings and JSON values", () => {
  assert.equal(countTokens(""), 0);
  assert.equal(countTokens({ a: 1 }), countTokens(JSON.stringify({ a: 1 })));
  assert.ok(countTokens("a longer input") > countTokens("a"));
  assert.ok(countResultTokens({ output: "done" }) > 0);
});
