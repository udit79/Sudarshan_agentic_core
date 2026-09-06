"""Production service entry point.

Ingestion is exposed through the authenticated ``POST /ingest`` API. This
module intentionally has no demo or sample-data execution path.
"""

import os

import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "api.server:app",
        host=os.getenv("SUDARSHAN_API_HOST", "0.0.0.0"),
        port=int(os.getenv("SUDARSHAN_API_PORT", "8000")),
        reload=os.getenv("SUDARSHAN_API_RELOAD", "false").lower() in {"1", "true", "yes"},
    )

