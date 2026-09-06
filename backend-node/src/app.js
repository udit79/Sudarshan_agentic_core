import crypto from "node:crypto";
import express from "express";
import cookieParser from "cookie-parser";
import cors from "cors";
import helmet from "helmet";
import pinoHttp from "pino-http";
import pino from "pino";
import routes from "./routes.js";
import { config } from "./config.js";

export const logger = pino({ level: process.env.LOG_LEVEL || "info" });
export const app = express();

app.set("trust proxy", 1);
app.use((req, res, next) => {
  const requestId = req.get("X-Request-Id")?.trim() || crypto.randomUUID();
  req.requestId = requestId;
  res.set("X-Request-Id", requestId);
  next();
});
app.use(pinoHttp({ logger, genReqId: (req) => req.requestId }));
app.use(helmet());
app.use(cors({ origin: config.corsOrigins, credentials: true, methods: ["GET", "POST", "OPTIONS"] }));
app.use(express.json({ limit: "2mb", strict: true }));
app.use(cookieParser());

app.get("/healthz", (req, res) => res.json({ status: "ok" }));
app.get("/readyz", async (req, res) => {
  const ready = app.locals.databaseReady?.() === true && app.locals.databaseInitialized === true;
  res.status(ready ? 200 : 503).json({ status: ready ? "ok" : "not_ready", database: ready ? "connected" : "disconnected" });
});
app.use("/api/v1", routes);

app.use((req, res) => res.status(404).json({ error: "Route not found", request_id: req.requestId }));
app.use((error, req, res, next) => {
  if (res.headersSent) return next(error);
  req.log?.error({ err: error, request_id: req.requestId }, "request failed");
  const status = Number.isInteger(error.status)
    ? error.status
    : (error.type === "entity.too.large"
      ? 413
      : (error instanceof SyntaxError && "body" in error ? 400 : (error.code === 11000 ? 409 : 500)));
  if (status >= 500) return res.status(status).json({ error: "Internal server error", request_id: req.requestId });
  if (error.retryAfter) res.set("Retry-After", String(error.retryAfter));
  const message = error.code === 11000 ? "Resource already exists" : error.message;
  return res.status(status).json({ error: message, request_id: req.requestId });
});

export default app;
