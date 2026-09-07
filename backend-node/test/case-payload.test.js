import test from "node:test";
import assert from "node:assert/strict";
import { toCaseDocument } from "../src/case-payload.js";

test("case API payload maps to the Mongoose document shape", () => {
  assert.deepEqual(toCaseDocument({
    case_id: "case-1",
    name: "Operations",
    classification_level: "RESTRICTED",
    distribution: "Authorized NTRO personnel",
  }, "user-1"), {
    caseId: "case-1",
    ownerId: "user-1",
    name: "Operations",
    classificationLevel: "RESTRICTED",
    distribution: "Authorized NTRO personnel",
  });
});
