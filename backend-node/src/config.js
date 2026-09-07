import path from "node:path";
import { fileURLToPath } from "node:url";
import dotenv from "dotenv";

const sourceDirectory = path.dirname(fileURLToPath(import.meta.url));
const repositoryEnv = path.resolve(sourceDirectory, "../../.env");
// Load the repository-level environment for every entrypoint, including
// `npm start` launched from backend-node. Process variables still win because
// dotenv does not override values already supplied by the host.
dotenv.config({ path: repositoryEnv });

function required(name, value) {
  if (!value || !String(value).trim()) {
    throw new Error(`${name} must be configured`);
  }
  return String(value).trim();
}

function integer(name, value, fallback, minimum = 0) {
  const raw = String(value ?? fallback).trim();
  if (!/^\d+$/.test(raw)) {
    throw new Error(`${name} must be an integer >= ${minimum}`);
  }
  const parsed = Number(raw);
  if (!Number.isSafeInteger(parsed) || parsed < minimum) {
    throw new Error(`${name} must be an integer >= ${minimum}`);
  }
  return parsed;
}

const nodeEnv = process.env.NODE_ENV || "development";
const isProduction = nodeEnv === "production";

export const config = {
  nodeEnv,
  isProduction,
  port: integer("PORT", process.env.PORT, 8080, 1),
  mongodbUri: required("MONGODB_URI", process.env.MONGODB_URI),
  mongodbDbName: process.env.MONGODB_DB_NAME?.trim() || "sudarshan_gateway",
  frontendUrl: process.env.FRONTEND_URL?.trim() || "http://localhost:3000",
  googleClientId: process.env.GOOGLE_CLIENT_ID?.trim() || "",
  googleClientSecret: process.env.GOOGLE_CLIENT_SECRET?.trim() || "",
  googleCallbackUrl: process.env.GOOGLE_CALLBACK_URL?.trim() || "",
  accessSecret: required("JWT_ACCESS_SECRET", process.env.JWT_ACCESS_SECRET),
  refreshSecret: required("JWT_REFRESH_SECRET", process.env.JWT_REFRESH_SECRET),
  accessTtl: process.env.JWT_ACCESS_TTL || "15m",
  refreshTtl: process.env.JWT_REFRESH_TTL || "30d",
  cookieSecure: process.env.COOKIE_SECURE?.toLowerCase() === "true" || isProduction,
  cookieSameSite: (process.env.COOKIE_SAME_SITE || (isProduction ? "none" : "lax")).toLowerCase(),
  pythonApiBaseUrl: (process.env.PYTHON_API_BASE_URL || "http://localhost:8000").replace(/\/$/, ""),
  pythonApiTimeoutMs: integer("PYTHON_API_TIMEOUT_MS", process.env.PYTHON_API_TIMEOUT_MS, 30000, 1000),
  pythonIngestTimeoutMs: integer("PYTHON_INGEST_TIMEOUT_MS", process.env.PYTHON_INGEST_TIMEOUT_MS, 180000, 1000),
  corsOrigins: (process.env.CORS_ORIGINS || "http://localhost:3000,http://localhost:5173")
    .split(",").map((item) => item.trim()).filter(Boolean),
  tokenLimitPerMinute: integer("TOKEN_LIMIT_PER_MINUTE", process.env.TOKEN_LIMIT_PER_MINUTE, 20000, 1),
  tokenLimitPerDay: integer("TOKEN_LIMIT_PER_DAY", process.env.TOKEN_LIMIT_PER_DAY, 200000, 1),
  requestLimitPerMinute: integer("REQUEST_LIMIT_PER_MINUTE", process.env.REQUEST_LIMIT_PER_MINUTE, 30, 1),
  maxReservedOutputTokens: integer("MAX_RESERVED_OUTPUT_TOKENS", process.env.MAX_RESERVED_OUTPUT_TOKENS, 12000, 0),
  transformWaitTimeoutMs: integer("TRANSFORM_WAIT_TIMEOUT_MS", process.env.TRANSFORM_WAIT_TIMEOUT_MS, 30000, 1000),
};

export function assertProductionConfig() {
  if (!config.isProduction) return;
  for (const [name, value] of [
    ["GOOGLE_CLIENT_ID", config.googleClientId],
    ["GOOGLE_CLIENT_SECRET", config.googleClientSecret],
    ["GOOGLE_CALLBACK_URL", config.googleCallbackUrl],
  ]) {
    required(name, value);
  }
  if (config.accessSecret.length < 32 || config.refreshSecret.length < 32) {
    throw new Error("JWT secrets must be at least 32 characters in production");
  }
  if (config.corsOrigins.includes("*")) {
    throw new Error("Wildcard CORS is not allowed in production");
  }
  if (!["lax", "strict", "none"].includes(config.cookieSameSite.toLowerCase())) {
    throw new Error("COOKIE_SAME_SITE must be lax, strict, or none");
  }
  if (config.cookieSameSite.toLowerCase() === "none" && !config.cookieSecure) {
    throw new Error("SameSite=None cookies require COOKIE_SECURE=true");
  }
}
