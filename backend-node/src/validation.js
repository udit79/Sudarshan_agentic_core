import { z } from "zod";

const pipelineNames = ["advisory", "linkedin_post", "executive_summary", "infographic", "presentation", "ppt", "video"];

export const transformSchema = z.object({
  user_id: z.string().trim().min(1).max(200).optional(),
  case_id: z.string().trim().min(1).max(200),
  task_id: z.string().trim().min(1).max(200).optional(),
  input: z.unknown().refine((value) => value !== undefined && value !== null, "input is required"),
  output_types: z.array(z.enum(pipelineNames)).min(1).max(8).refine(
    (values) => new Set(values).size === values.length,
    "output_types must not contain duplicates",
  ),
  classification_level: z.enum(["UNCLASSIFIED", "RESTRICTED", "CONFIDENTIAL", "SECRET", "TOP SECRET"]).default("RESTRICTED"),
  distribution: z.string().trim().min(1).max(500).default("Authorized NTRO personnel"),
}).strict();

export const resumeSchema = z.object({
  answer: z.string().trim().min(1).max(10000).optional(),
  decision: z.enum(["approved", "rejected", "revise"]).optional(),
  reviewer_id: z.string().trim().min(1).max(200).optional(),
  comment: z.string().trim().max(2000).optional(),
}).strict().refine(
  (value) => value.answer || value.decision || value.comment,
  "answer, decision, or comment is required",
);

export const caseSchema = z.object({
  case_id: z.string().trim().min(1).max(200),
  name: z.string().trim().min(1).max(200),
  classification_level: z.enum(["UNCLASSIFIED", "RESTRICTED", "CONFIDENTIAL", "SECRET", "TOP SECRET"]).default("RESTRICTED"),
  distribution: z.string().trim().min(1).max(500).default("Authorized NTRO personnel"),
}).strict();

export function parse(schema, value) {
  const result = schema.safeParse(value);
  if (!result.success) {
    const error = new Error(result.error.issues.map((issue) => `${issue.path.join(".") || "body"}: ${issue.message}`).join("; "));
    error.status = 422;
    throw error;
  }
  return result.data;
}
