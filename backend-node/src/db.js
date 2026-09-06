import mongoose from "mongoose";
import { config } from "./config.js";

mongoose.set("strictQuery", true);

export async function connectDatabase() {
  await mongoose.connect(config.mongodbUri, {
    dbName: config.mongodbDbName,
    maxPoolSize: 30,
    minPoolSize: 5,
    serverSelectionTimeoutMS: 10000,
    socketTimeoutMS: 45000,
    retryWrites: true,
  });
}

export async function disconnectDatabase() {
  await mongoose.disconnect();
}

export async function initializeDatabase() {
  // Model.init() creates the MongoDB collections and declared indexes. Atlas
  // is the durable source of truth; startup is safe to repeat because MongoDB
  // treats existing indexes as idempotent initialization.
  const { User, AuthState, RefreshToken, Case, Task, RateLimitBucket } = await import("./models.js");
  await Promise.all([
    User.init(),
    AuthState.init(),
    RefreshToken.init(),
    Case.init(),
    Task.init(),
    RateLimitBucket.init(),
  ]);
}

export function databaseReady() {
  return mongoose.connection.readyState === 1;
}

export { mongoose };
