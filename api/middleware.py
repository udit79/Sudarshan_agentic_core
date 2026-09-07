"""NTRO-specific FastAPI middleware."""

import json
import logging
import time
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from pipelines.common.audit_logger import get_audit_logger
from pipelines.common.ntro_policy import require_classification


class NTROSecurityMiddleware(BaseHTTPMiddleware):
    """Enforces authentication and NTRO policy headers."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Require Operator ID for all state-mutating requests
        if request.method in ("POST", "PUT", "DELETE"):
            operator_id = request.headers.get("x-operator-id", "").strip()
            if not operator_id:
                return Response(
                    content=json.dumps({"error": "Missing X-Operator-Id header"}),
                    status_code=401,
                    media_type="application/json",
                )

        response: Response = await call_next(request)

        # Enforce classification response header
        try:
            classification = require_classification(
                request.headers.get("x-classification-level", "RESTRICTED")
            )
        except ValueError as exc:
            return Response(
                content=json.dumps({"error": str(exc)}),
                status_code=422,
                media_type="application/json",
            )
        response.headers["X-Classification-Level"] = classification
        
        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        return response


class AuditMiddleware(BaseHTTPMiddleware):
    """Logs all API requests to the local tamper-evident audit trail."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        
        response = await call_next(request)
        process_time = time.time() - start_time

        logger = get_audit_logger()
        logger.log(
            operator_id=request.headers.get("x-operator-id", "anonymous"),
            action=f"api_{request.method.lower()}",
            status=str(response.status_code),
            case_id=request.headers.get("x-case-id", ""),
            classification=request.headers.get("x-classification-level", "RESTRICTED"),
            # Do not consume or persist request bodies: uploads are streamed
            # and JSON bodies may contain case-sensitive information.
            detail=(
                f"path={request.url.path}; duration={process_time:.3f}s; "
                f"body_len={request.headers.get('content-length', 'unknown')}"
            )
        )

        return response
