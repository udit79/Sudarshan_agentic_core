"""FastAPI production server for the Sudarshan Agentic Core."""

import asyncio
import os
import tempfile
from contextlib import asynccontextmanager
from uuid import uuid4
from pathlib import Path
import uvicorn
from dotenv import load_dotenv
from fastapi import BackgroundTasks, File, Form, HTTPException, FastAPI, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse

from api.middleware import NTROSecurityMiddleware, AuditMiddleware
from integrations.deepseek_harness.application import get_application
from api.sse import event_generator
from ingestion_pipelines.extract import SUPPORTED_EXTENSIONS
from pipelines.common.ntro_policy import require_classification
from pipelines.common.contracts import AdvisoryRequest

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
ARTIFACT_ROOT = (Path(__file__).resolve().parents[1] / "artifacts").resolve()


@asynccontextmanager
async def lifespan(_application: FastAPI):
    """Fail fast and warm the orchestrator/pipeline registry on service boot."""

    await asyncio.to_thread(lambda: get_application().list_pipelines())
    yield

app = FastAPI(
    title="Sudarshan Agentic Core API",
    description="NTRO Intelligent Advisory Platform Backend",
    version="1.0.0",
    lifespan=lifespan,
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


async def _save_upload(upload: UploadFile, *, max_bytes: int) -> tuple[str, str]:
    """Stream an upload to a private temporary file with a hard size limit."""

    source_reference = Path(upload.filename or "upload").name
    suffix = Path(source_reference).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {suffix or '<none>'}")

    handle = tempfile.NamedTemporaryFile(prefix="sudarshan-ingest-", suffix=suffix, delete=False)
    temp_path = handle.name
    total = 0
    try:
        with handle:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(status_code=413, detail="Uploaded file exceeds the configured size limit")
                handle.write(chunk)
    except Exception:
        Path(temp_path).unlink(missing_ok=True)
        raise
    finally:
        await upload.close()
    return temp_path, source_reference


@app.get("/health")
async def health_check():
    """System health (Cognee, providers, pipelines)."""
    return get_application().health()


@app.get("/pipelines")
async def list_pipelines():
    """Registered pipeline discovery."""
    return {"pipelines": get_application().list_pipelines()}


@app.post("/config/session")
async def configure_session(request: Request):
    """Set a development-only provider key for this running API process."""

    if os.getenv("NODE_ENV", "development").lower() == "production":
        raise HTTPException(status_code=403, detail="Runtime configuration is disabled in production")
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Request body must be valid JSON") from exc
    api_key = str(payload.get("openai_api_key", "")).strip() if isinstance(payload, dict) else ""
    if not api_key or len(api_key) > 500:
        raise HTTPException(status_code=422, detail="openai_api_key is required")
    os.environ["OPENAI_API_KEY"] = api_key
    return {"status": "configured", "provider": "openai", "storage": "process-memory"}


def _artifact_path_from_status(status: dict, artifact_key: str) -> Path | None:
    responses = status.get("responses") or {}
    response = responses.get(artifact_key) or (
        status.get("response") if status.get("pipeline") == artifact_key else None
    ) or {}
    output = response.get("output") or {}
    artifact = response.get("artifact") or {}
    candidates = []
    if artifact_key == "video":
        candidates.extend([artifact.get("video_path"), artifact.get("path")])
    if artifact_key == "presentation":
        candidates.append(artifact.get("path"))
    if artifact_key == "infographic":
        candidates.extend([output.get("artifact_path"), artifact.get("path")])
    if artifact_key == "linkedin_post":
        image = output.get("image") or {}
        candidates.extend([image.get("asset_uri"), artifact.get("path")])
    candidates.extend([artifact.get("path"), output.get("artifact_path")])
    for candidate in candidates:
        if not isinstance(candidate, str) or candidate.startswith(("http://", "https://")):
            continue
        candidate_path = Path(candidate)
        resolved = (ARTIFACT_ROOT.parent / candidate_path).resolve() if not candidate_path.is_absolute() else candidate_path.resolve()
        if resolved == ARTIFACT_ROOT or ARTIFACT_ROOT in resolved.parents:
            if resolved.is_file():
                return resolved
    return None


@app.get("/artifacts/{run_id}/{artifact_key}")
async def serve_artifact(run_id: str, artifact_key: str):
    status = get_application().status(run_id)
    if status.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="Run not found")
    artifact_path = _artifact_path_from_status(status, artifact_key.strip().lower())
    if artifact_path is None:
        raise HTTPException(status_code=404, detail="Artifact is not available for this run")
    return FileResponse(artifact_path)


@app.post("/ingest", status_code=201)
async def ingest_source(
    request: Request,
    file: UploadFile = File(...),
    user_id: str | None = Form(None),
    case_id: str | None = Form(None),
    task_id: str | None = Form(None),
    classification_level: str | None = Form(None),
):
    """Extract a real uploaded source and persist it into case memory."""

    operator_id = request.headers.get("x-operator-id", "").strip()
    resolved_user_id = (user_id or operator_id).strip()
    resolved_case_id = (case_id or request.headers.get("x-case-id", "")).strip()
    if resolved_user_id != operator_id:
        raise HTTPException(status_code=403, detail="user_id must match the authenticated operator")
    if not resolved_case_id:
        raise HTTPException(status_code=422, detail="case_id is required for NTRO ingestion")

    resolved_task_id = (task_id or f"ingest-{uuid4()}").strip()
    classification = require_classification(
        classification_level or request.headers.get("x-classification-level", "RESTRICTED")
    )
    max_bytes = int(os.getenv("SUDARSHAN_MAX_INGEST_BYTES", str(50 * 1024 * 1024)))
    temp_path, source_reference = await _save_upload(file, max_bytes=max_bytes)
    try:
        try:
            return await asyncio.to_thread(
                get_application().ingest_path,
                temp_path,
                source_reference=source_reference,
                operator_id=operator_id,
                user_id=resolved_user_id,
                case_id=resolved_case_id,
                task_id=resolved_task_id,
                classification_level=classification,
            )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail="Source extraction or memory persistence failed",
            ) from exc
    finally:
        Path(temp_path).unlink(missing_ok=True)


@app.post("/runs")
async def create_run(request: Request):
    """Start a new graph execution."""
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Request body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Request body must be a JSON object")

    operator_id = request.headers.get("x-operator-id", "").strip()
    if payload.get("user_id") is None:
        payload["user_id"] = operator_id
    elif str(payload["user_id"]).strip() != operator_id:
        raise HTTPException(status_code=403, detail="user_id must match the authenticated operator")

    case_id = request.headers.get("x-case-id", "").strip()
    if payload.get("case_id") is None:
        payload["case_id"] = case_id
    elif case_id and str(payload["case_id"]).strip() != case_id:
        raise HTTPException(status_code=403, detail="case_id must match the authenticated case")

    classification_header = request.headers.get("x-classification-level")
    if payload.get("classification_level") is None and classification_header:
        payload["classification_level"] = classification_header

    if not payload.get("task_id"):
        payload["task_id"] = f"task-{uuid4()}"

    app_instance = get_application()
    try:
        validated = AdvisoryRequest(**payload)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    metadata = dict(validated.metadata)
    run_id = str(metadata.get("run_id") or f"run-{uuid4()}")
    metadata["run_id"] = run_id
    payload["metadata"] = metadata
    explicit = list(validated.requested_pipelines)
    if not explicit:
        explicit_pipeline = metadata.get("pipeline")
        explicit_pipelines = metadata.get("pipelines")
        if isinstance(explicit_pipeline, str) and explicit_pipeline.strip():
            explicit = [explicit_pipeline.strip().lower()]
        elif isinstance(explicit_pipelines, str) and explicit_pipelines.strip():
            explicit = [explicit_pipelines.strip().lower()]
        elif isinstance(explicit_pipelines, (list, tuple)):
            explicit = [str(item).strip().lower() for item in explicit_pipelines if str(item).strip()]
    unknown = sorted(set(explicit) - set(app_instance.list_pipelines()))
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown pipeline(s): {', '.join(unknown)}")

    background_tasks = BackgroundTasks()
    background_tasks.add_task(asyncio.to_thread, app_instance.run, payload, operator_id=operator_id)
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
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Request body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Request body must be a JSON object")
    task_id = str(payload.get("task_id", "")).strip()
    if not task_id:
        raise HTTPException(status_code=422, detail="task_id is required")
    try:
        result = await asyncio.to_thread(
            get_application().resume,
            run_id,
            task_id,
            payload,
            operator_id=request.headers.get("x-operator-id", "").strip(),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JSONResponse(content=result)


@app.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, request: Request):
    """Frontend cooperative cancellation."""
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Request body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Request body must be a JSON object")
    task_id = str(payload.get("task_id", "")).strip()
    if not task_id:
        raise HTTPException(status_code=422, detail="task_id is required")
    try:
        result = await asyncio.to_thread(
            get_application().cancel,
            run_id,
            task_id,
            operator_id=request.headers.get("x-operator-id", "").strip(),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return JSONResponse(content=result)


if __name__ == "__main__":
    host = os.getenv("SUDARSHAN_API_HOST", "0.0.0.0")
    port = int(os.getenv("SUDARSHAN_API_PORT", "8000"))
    reload_enabled = os.getenv("SUDARSHAN_API_RELOAD", "false").lower() in {"1", "true", "yes"}
    uvicorn.run("api.server:app", host=host, port=port, reload=reload_enabled)
