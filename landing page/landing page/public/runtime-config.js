/*
 * Browser-safe runtime defaults. startup.ps1 writes runtime-config.local.js
 * from .env before starting Vite; this file keeps direct `npm run dev`
 * usable when the orchestrator is not running.
 *
 * This file must never contain credentials. It only contains public service
 * origins and is loaded before api.js and login.js.
 */
(function installSudarshanRuntimeConfig(global) {
  global.SUDARSHAN_API_ORIGIN = global.SUDARSHAN_API_ORIGIN || "http://localhost:8080";
  global.SUDARSHAN_FASTAPI_ORIGIN = global.SUDARSHAN_FASTAPI_ORIGIN || "http://localhost:8000";
  global.SUDARSHAN_HARNESS_URL = global.SUDARSHAN_HARNESS_URL || "http://localhost:3080/";
}(window));
