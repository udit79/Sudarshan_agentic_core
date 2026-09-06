import app from "./app.js";
import { assertProductionConfig, config } from "./config.js";
import { connectDatabase, databaseReady, disconnectDatabase, initializeDatabase } from "./db.js";

assertProductionConfig();
await connectDatabase();
await initializeDatabase();
app.locals.databaseReady = databaseReady;
app.locals.databaseInitialized = true;

const server = app.listen(config.port, () => {
  console.log(`Sudarshan Node gateway listening on port ${config.port}`);
});

async function shutdown(signal) {
  console.log(`${signal} received; shutting down gracefully`);
  server.close(async () => {
    await disconnectDatabase();
    process.exit(0);
  });
  setTimeout(() => process.exit(1), 10000).unref();
}

process.once("SIGTERM", () => shutdown("SIGTERM"));
process.once("SIGINT", () => shutdown("SIGINT"));
