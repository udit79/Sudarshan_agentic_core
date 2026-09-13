"""FastAPI production server for the Sudarshan Agentic Core."""

import asyncio
import json
import mimetypes
import os
import tempfile
from contextlib import asynccontextmanager
from uuid import uuid4
from pathlib import Path
import uvicorn
from dotenv import load_dotenv
from fastapi import File, Form, HTTPException, FastAPI, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse

from api.middleware import NTROSecurityMiddleware, AuditMiddleware
from api.artifacts import ArtifactNotFound, ArtifactPreviewUnavailable, ArtifactStore
from api.scheduler import SchedulerConflictError
from integrations.deepseek_harness.application import get_application
from api.sse import event_generator
from ingestion_pipelines import SourceSafetyError, inspect_source
from ingestion_pipelines.extract import SUPPORTED_EXTENSIONS
from pipelines.common.ntro_policy import require_classification, require_classification_access
from pipelines.common.contracts import AdvisoryRequest
from integrations.deepseek_harness.a2a import agent_card, cancel_task as a2a_cancel_task, get_task as a2a_get_task, submit_task as a2a_submit_task

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
ARTIFACT_ROOT = (Path(__file__).resolve().parents[1] / "artifacts").resolve()
ARTIFACT_STORE = ArtifactStore(ARTIFACT_ROOT)


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
    "SUDARSHAN_CORS_ORIGINS", "http://localhost:3000,http://localhost:5173,http://localhost:3080,http://127.0.0.1:3080,http://localhost:3082,http://127.0.0.1:3082"
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


async def _save_upload(
    upload: UploadFile,
    *,
    max_bytes: int,
    classification_level: str = "RESTRICTED",
    user_id: str | None = None,
    case_id: str | None = None,
    task_id: str | None = None,
) -> tuple[str, str]:
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
        inspect_source(
            temp_path,
            source_reference=source_reference,
            max_bytes=max_bytes,
            classification_level=classification_level,
            user_id=user_id,
            case_id=case_id,
            task_id=task_id,
        )
    except SourceSafetyError as exc:
        Path(temp_path).unlink(missing_ok=True)
        raise HTTPException(status_code=415, detail=str(exc)) from exc
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


@app.get("/.well-known/agent-card.json")
async def get_agent_card(request: Request):
    return agent_card(str(request.base_url).rstrip("/"))


@app.post("/a2a/tasks")
async def submit_a2a_task(request: Request):
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError("A2A task body must be an object")
        operator_id = request.headers.get("x-operator-id", "").strip()
        if not operator_id:
            raise HTTPException(status_code=401, detail="X-Operator-Id is required")
        return a2a_submit_task(get_application(), payload, operator_id=operator_id)
    except HTTPException:
        raise
    except (TypeError, ValueError, PermissionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/a2a/tasks/{run_id}")
async def get_a2a_task(run_id: str):
    return a2a_get_task(get_application(), run_id)


@app.post("/a2a/tasks/{run_id}/cancel")
async def cancel_a2a_task(request: Request, run_id: str):
    task_id = request.headers.get("x-task-id", "").strip()
    if not task_id:
        raise HTTPException(status_code=422, detail="X-Task-Id is required")
    try:
        return a2a_cancel_task(get_application(), run_id, task_id=task_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


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


def _manifest_for_run_artifact(run_id: str, artifact_key: str):
    status = get_application().status(run_id)
    if status.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="Run not found")
    artifact_path = _artifact_path_from_status(status, artifact_key.strip().lower())
    if artifact_path is None:
        raise HTTPException(status_code=404, detail="Artifact is not available for this run")
    try:
        return ARTIFACT_STORE.register(
            artifact_path,
            run_id=run_id,
            kind=artifact_key.strip().lower(),
            classification_level=str(status.get("classification_level", "RESTRICTED")),
        )
    except (ArtifactNotFound, PermissionError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _check_artifact_access(request: Request, classification_level: str) -> None:
    """Apply the request clearance check before returning an artifact."""

    try:
        require_classification_access(
            request.headers.get("x-classification-level", "RESTRICTED"),
            classification_level,
        )
    except (PermissionError, ValueError) as exc:
        raise HTTPException(status_code=403, detail="Artifact classification is not accessible") from exc


@app.get("/artifacts/{run_id}/{artifact_key}/manifest")
async def get_run_artifact_manifest(request: Request, run_id: str, artifact_key: str):
    """Register or return the immutable manifest for a run artifact."""

    manifest = _manifest_for_run_artifact(run_id, artifact_key)
    _check_artifact_access(request, manifest.classification_level)
    return manifest.model_dump(mode="json")


@app.get("/artifacts/{artifact_id}/manifest")
async def get_artifact_manifest(request: Request, artifact_id: str):
    try:
        manifest, _ = ARTIFACT_STORE.get(artifact_id)
    except (ArtifactNotFound, PermissionError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=404, detail="Artifact manifest is not available") from exc
    _check_artifact_access(request, manifest.classification_level)
    return manifest.model_dump(mode="json")


@app.get("/artifacts/{artifact_id}/download")
async def download_artifact(request: Request, artifact_id: str):
    try:
        manifest, source = ARTIFACT_STORE.get(artifact_id)
    except (ArtifactNotFound, PermissionError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=404, detail="Artifact is not available") from exc
    _check_artifact_access(request, manifest.classification_level)
    return FileResponse(source, filename=manifest.name)


@app.get("/artifacts/{artifact_id}/preview")
async def preview_artifact(request: Request, artifact_id: str):
    """Return a safe image/media/text preview when one is available."""

    try:
        manifest, preview = ARTIFACT_STORE.preview(artifact_id)
    except (ArtifactNotFound, ArtifactPreviewUnavailable, PermissionError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=404, detail="Artifact preview is not available") from exc
    _check_artifact_access(request, manifest.classification_level)
    media_type = mimetypes.guess_type(preview.name)[0] or "application/octet-stream"
    return FileResponse(preview, media_type=media_type, filename=preview.name)


@app.get("/artifacts/{run_id}/{artifact_key}")
async def serve_artifact(request: Request, run_id: str, artifact_key: str):
    status = get_application().status(run_id)
    if status.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="Run not found")
    artifact_path = _artifact_path_from_status(status, artifact_key.strip().lower())
    if artifact_path is None:
        raise HTTPException(status_code=404, detail="Artifact is not available for this run")
    _check_artifact_access(request, str(status.get("classification_level", "RESTRICTED")))
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
    try:
        temp_path, source_reference = await _save_upload(
            file,
            max_bytes=max_bytes,
            classification_level=classification,
            user_id=resolved_user_id,
            case_id=resolved_case_id,
            task_id=resolved_task_id,
        )
    except HTTPException:
        raise
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


@app.post("/ingestions", status_code=202)
async def submit_ingestion(
    request: Request,
    file: UploadFile = File(...),
    user_id: str | None = Form(None),
    case_id: str | None = Form(None),
    task_id: str | None = Form(None),
    classification_level: str | None = Form(None),
):
    """Admit source extraction and return without waiting for OCR/video work."""

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
    temp_path: str | None = None
    staged_path: Path | None = None
    try:
        temp_path, source_reference = await _save_upload(
            file,
            max_bytes=max_bytes,
            classification_level=classification,
            user_id=resolved_user_id,
            case_id=resolved_case_id,
            task_id=resolved_task_id,
        )
        inspection = inspect_source(
            temp_path,
            source_reference=source_reference,
            max_bytes=max_bytes,
            classification_level=classification,
            user_id=resolved_user_id,
            case_id=resolved_case_id,
            task_id=resolved_task_id,
        )
        staging_root = Path(
            os.getenv(
                "SUDARSHAN_INGESTION_STAGING_DIR",
                str(ARTIFACT_ROOT / ".state" / "ingestion_sources"),
            )
        )
        staging_root.mkdir(parents=True, exist_ok=True)
        staged_path = staging_root / f"{uuid4().hex}{Path(source_reference).suffix.lower()}"
        Path(temp_path).replace(staged_path)
        temp_path = None
        idempotency_key = request.headers.get("idempotency-key", "").strip()
        result = await asyncio.to_thread(
            get_application().submit_ingestion,
            {
                "file_path": str(staged_path),
                "source_reference": inspection.source_reference,
                "source_hash": inspection.source_hash,
                "media_type": inspection.media_type,
                "modality": inspection.modality,
                "user_id": resolved_user_id,
                "case_id": resolved_case_id,
                "task_id": resolved_task_id,
                "classification_level": classification,
                "idempotency_key": idempotency_key,
            },
            operator_id=operator_id,
        )
        if result.get("deduplicated") and staged_path is not None:
            staged_path.unlink(missing_ok=True)
        return result
    except SchedulerConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Source ingestion admission failed") from exc
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)


@app.get("/ingestions/{ingestion_id}")
async def get_ingestion(request: Request, ingestion_id: str):
    """Return safe asynchronous ingestion status and its result receipt."""

    result = await asyncio.to_thread(get_application().ingestion_status, ingestion_id)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="Ingestion not found")
    return result


@app.post("/ingestions/{ingestion_id}/cancel")
async def cancel_ingestion(request: Request, ingestion_id: str, task_id: str = Query(...)):
    """Request cooperative cancellation for queued or running extraction."""

    try:
        result = await asyncio.to_thread(
            get_application().cancel_ingestion,
            ingestion_id,
            task_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="Ingestion not found")
    return result


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

    try:
        queued = await asyncio.to_thread(app_instance.submit, payload, operator_id=operator_id)
    except SchedulerConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (PermissionError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JSONResponse(content=queued, status_code=202)


@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    """Get durable graph/result state."""
    return get_application().status(run_id)


@app.get("/runs/{run_id}/telemetry")
async def get_run_telemetry(run_id: str):
    """Get dashboard-safe aggregate telemetry without prompts or raw memory."""
    return get_application().telemetry(run_id)


@app.get("/runs/{run_id}/wait")
async def wait_run(
    run_id: str,
    timeout_ms: int = Query(default=30_000, ge=0, le=60_000),
    after_sequence: int = Query(default=0, ge=0),
):
    """Bounded wait for completion, user action, or the timeout."""

    try:
        return await asyncio.to_thread(
            get_application().wait,
            run_id,
            timeout_ms=timeout_ms,
            after_sequence=after_sequence,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/runs/{run_id}/events")
async def stream_run_events(run_id: str, after_sequence: int = Query(default=0, ge=0)):
    """SSE stream of ProgressEvent values."""
    return StreamingResponse(
        event_generator(run_id, after_sequence=after_sequence),
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
