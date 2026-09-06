"""FastAPI production server for the Sudarshan Agentic Core."""

import asyncio
import os
from uuid import uuid4
import uvicorn
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse

from api.middleware import NTROSecurityMiddleware, AuditMiddleware
from integrations.deepseek_harness.application import get_application
from api.sse import event_generator

app = FastAPI(
    title="Sudarshan Agentic Core API",
    description="NTRO Intelligent Advisory Platform Backend",
    version="1.0.0",
)

# CORS configuration
origins = [origin.strip() for origin in os.getenv(
    "SUDARSHAN_CORS_ORIGINS", "http://localhost:3000,http://localhost:5173"
).split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# NTRO Custom Middleware
app.add_middleware(NTROSecurityMiddleware)
app.add_middleware(AuditMiddleware)


@app.get("/health")
async def health_check():
    """System health (Cognee, providers, pipelines)."""
    return get_application().health()


@app.get("/pipelines")
async def list_pipelines():
    """Registered pipeline discovery."""
    return {"pipelines": get_application().list_pipelines()}


@app.post("/runs")
async def create_run(request: Request):
    """Start a new graph execution."""
    payload = await request.json()
    
    # Enforce NTRO operator ID from headers if not in payload
    operator_id = request.headers.get("x-operator-id")
    if operator_id and "user_id" not in payload:
        payload["user_id"] = operator_id
    elif operator_id and payload.get("user_id") != operator_id:
        return JSONResponse(
            status_code=403,
            content={"error": "user_id must match the authenticated operator"},
        )
        
    case_id = request.headers.get("x-case-id")
    if case_id and "case_id" not in payload:
        payload["case_id"] = case_id
        
    app_instance = get_application()
    metadata = dict(payload.get("metadata") or {})
    run_id = str(metadata.get("run_id") or f"run-{uuid4()}")
    metadata["run_id"] = run_id
    payload["metadata"] = metadata
    if not payload.get("task_id"):
        payload["task_id"] = f"task-{uuid4()}"
    background_tasks = BackgroundTasks()
    background_tasks.add_task(asyncio.to_thread, app_instance.run, payload)
    response = JSONResponse(content={
        "status": "queued",
        "run_id": run_id,
        "task_id": payload["task_id"],
        "pipeline": None,
        "pipelines": payload.get("requested_pipelines", []),
    }, status_code=202)
    response.background = background_tasks
    return response


@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    """Get durable graph/result state."""
    return get_application().status(run_id)


@app.get("/runs/{run_id}/events")
async def stream_run_events(run_id: str):
    """SSE stream of ProgressEvent values."""
    return StreamingResponse(
        event_generator(run_id), 
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.post("/runs/{run_id}/resume")
async def resume_run(run_id: str, request: Request):
    """Resume a run with clarification or approval decision."""
    payload = await request.json()
    task_id = payload.get("task_id", "unknown")
    result = await asyncio.to_thread(get_application().resume, run_id, task_id, payload)
    return JSONResponse(content=result)


@app.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, request: Request):
    """Frontend cooperative cancellation."""
    payload = await request.json()
    task_id = payload.get("task_id", "unknown")
    result = await asyncio.to_thread(get_application().cancel, run_id, task_id)
    return JSONResponse(content=result)


if __name__ == "__main__":
    host = os.getenv("SUDARSHAN_API_HOST", "0.0.0.0")
    port = int(os.getenv("SUDARSHAN_API_PORT", "8000"))
    reload_enabled = os.getenv("SUDARSHAN_API_RELOAD", "false").lower() in {"1", "true", "yes"}
    uvicorn.run("api.server:app", host=host, port=port, reload=reload_enabled)
