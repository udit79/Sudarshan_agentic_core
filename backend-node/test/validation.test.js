import test from "node:test";
import assert from "node:assert/strict";
import { caseSchema, parse, resumeSchema, transformSchema } from "../src/validation.js";

test("transform validation accepts JSON input and rejects duplicate pipelines", () => {
  const valid = parse(transformSchema, {
    case_id: "case-1",
    input: { objective: "brief" },
    output_types: ["executive_summary", "presentation"],
  });
  assert.deepEqual(valid.output_types, ["executive_summary", "presentation"]);

  assert.throws(
    () => parse(transformSchema, {
      case_id: "case-1",
      input: "brief",
      output_types: ["advisory", "advisory"],
    }),
    (error) => error.status === 422 && error.message.includes("duplicates"),
  );
});

test("transform validation rejects null input, unknown fields, and unsupported pipelines", () => {
  for (const body of [
    { case_id: "case-1", input: null, output_types: ["advisory"] },
    { case_id: "case-1", input: "brief", output_types: ["not-a-pipeline"] },
    { case_id: "case-1", input: "brief", output_types: ["advisory"], extra: true },
  ]) {
    assert.throws(() => parse(transformSchema, body), (error) => error.status === 422);
  }
});

test("transform validation accepts bounded artifact revisions and requires lineage", () => {
  const revision = parse(transformSchema, {
    case_id: "case-1",
    input: "Change slide 4 title but preserve all evidence bindings",
    output_types: ["presentation"],
    operation: "revise",
    parent_artifact_id: "artifact-deck-v1",
    revision_instruction: "Change slide 4 title but preserve all evidence bindings",
    revision_scope: ["slides[4].title"],
  });
  assert.equal(revision.operation, "revise");
  assert.equal(revision.parent_artifact_id, "artifact-deck-v1");
  assert.deepEqual(revision.revision_scope, ["slides[4].title"]);

  assert.throws(
    () => parse(transformSchema, {
      case_id: "case-1",
      input: "Change one scene",
      output_types: ["video"],
      operation: "revise",
      revision_instruction: "Change one scene",
    }),
    (error) => error.status === 422 && error.message.includes("parent_artifact_id"),
  );
});

test("case and resume validation enforce bounded, actionable input", () => {
  assert.equal(parse(caseSchema, { case_id: "case-1", name: "Case" }).classification_level, "RESTRICTED");
  assert.equal(parse(resumeSchema, { answer: "focus on the decision" }).answer, "focus on the decision");
  assert.throws(() => parse(resumeSchema, {}), (error) => error.status === 422);
  assert.throws(() => parse(caseSchema, { case_id: "case-1", name: "" }), (error) => error.status === 422);
});
