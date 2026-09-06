import { mongoose } from "./db.js";

const { Schema } = mongoose;

const timestamps = { createdAt: "createdAt", updatedAt: "updatedAt" };

const userSchema = new Schema({
  googleSub: { type: String, required: true, unique: true, index: true },
  email: { type: String, required: true, lowercase: true, trim: true, index: true },
  emailVerified: { type: Boolean, default: false },
  name: { type: String, required: true, trim: true, maxlength: 200 },
  picture: { type: String, default: "", maxlength: 2000 },
  roles: { type: [String], default: ["user"] },
  lastLoginAt: { type: Date, default: Date.now },
}, { timestamps });

const authStateSchema = new Schema({
  _id: { type: String },
  expiresAt: { type: Date, required: true, index: { expires: 0 } },
  returnTo: { type: String, default: "" },
}, { versionKey: false });

const refreshTokenSchema = new Schema({
  tokenHash: { type: String, required: true, unique: true, index: true },
  userId: { type: String, required: true, index: true },
  jti: { type: String, required: true, unique: true },
  expiresAt: { type: Date, required: true, index: { expires: 0 } },
}, { timestamps: true });

const caseSchema = new Schema({
  caseId: { type: String, required: true, trim: true },
  ownerId: { type: String, required: true, index: true },
  name: { type: String, required: true, trim: true, maxlength: 200 },
  classificationLevel: { type: String, default: "RESTRICTED" },
  distribution: { type: String, default: "Authorized NTRO personnel" },
}, { timestamps });
caseSchema.index({ ownerId: 1, caseId: 1 }, { unique: true });

const taskSchema = new Schema({
  userId: { type: String, required: true, index: true },
  caseId: { type: String, required: true, index: true },
  taskId: { type: String, required: true },
  runId: { type: String, default: "", index: true },
  inputHash: { type: String, required: true },
  inputPreview: { type: String, required: true, maxlength: 1000 },
  outputTypes: { type: [String], required: true },
  status: { type: String, required: true, default: "queued", index: true },
  result: { type: Schema.Types.Mixed, default: null },
  error: { type: String, default: null, maxlength: 2000 },
  inputTokens: { type: Number, required: true, min: 0 },
  reservedTokens: { type: Number, required: true, min: 0 },
  reservedAt: { type: Date, required: true },
  outputTokens: { type: Number, default: 0, min: 0 },
  totalTokens: { type: Number, default: 0, min: 0 },
  usageFinalized: { type: Boolean, default: false },
  idempotencyKey: { type: String, default: "", maxlength: 200 },
}, { timestamps });
taskSchema.index({ userId: 1, taskId: 1 }, { unique: true });
taskSchema.index({ userId: 1, idempotencyKey: 1 }, { unique: true, partialFilterExpression: { idempotencyKey: { $type: "string", $gt: "" } } });

const rateLimitBucketSchema = new Schema({
  _id: { type: String },
  key: { type: String, required: true, index: true },
  windowStart: { type: Date, required: true, index: true },
  requestCount: { type: Number, default: 0, min: 0 },
  inputTokens: { type: Number, default: 0, min: 0 },
  outputTokens: { type: Number, default: 0, min: 0 },
  reservedTokens: { type: Number, default: 0, min: 0 },
  expiresAt: { type: Date, required: true, index: { expires: 0 } },
}, { versionKey: false });

export const User = mongoose.models.User || mongoose.model("User", userSchema);
export const AuthState = mongoose.models.AuthState || mongoose.model("AuthState", authStateSchema);
export const RefreshToken = mongoose.models.RefreshToken || mongoose.model("RefreshToken", refreshTokenSchema);
export const Case = mongoose.models.Case || mongoose.model("Case", caseSchema);
export const Task = mongoose.models.Task || mongoose.model("Task", taskSchema);
export const RateLimitBucket = mongoose.models.RateLimitBucket || mongoose.model("RateLimitBucket", rateLimitBucketSchema);
