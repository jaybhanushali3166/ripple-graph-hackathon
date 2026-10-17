"""Main FastAPI application entrypoint for Ripple API."""

import asyncio
import logging
import os
from typing import Any, Dict

from fastapi import FastAPI, HTTPException as FastAPIHTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.app.ai.agent import StaleEvidenceError as AIStaleEvidenceError
from backend.app.ai.provider import (
    AIProviderError,
    ExtractionValidationError,
    ReviewRequiredError as AIReviewRequiredError,
)
from backend.app.api import api_router
from backend.app.errors import RippleError
from backend.app.graph.errors import (
    FixtureError,
    GraphError,
    GraphUnavailable,
    IdempotencyConflict,
    InconsistentRead,
    NotFound,
    ReviewRequired,
    StaleEvidence,
)

logger = logging.getLogger("ripple.api")

# Single-worker concurrency lock for serialized mutations
mutation_lock = asyncio.Lock()

app = FastAPI(
    title="Ripple API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Store mutation lock on app state for dependency injection/access
app.state.mutation_lock = mutation_lock

# Configure CORS dynamically from environment (supports local Vite, Vercel, and custom domains)
cors_origins_env = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000")
cors_origins = [origin.strip() for origin in cors_origins_env.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins if "*" not in cors_origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Transform validation errors into unified Ripple error envelope."""
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "invalid_input",
                "message": "Request validation failed",
                "details": jsonable_encoder(exc.errors()),
            }
        },
    )


async def unified_http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Transform HTTPExceptions into unified Ripple error envelope."""
    if isinstance(exc.detail, dict):
        code = exc.detail.get("code", "http_error")
        message = exc.detail.get("message", str(exc.detail))
        details = exc.detail.get("details", None)
    else:
        if exc.status_code == 404:
            code = "http_error"
        elif exc.status_code == 400:
            code = "invalid_input"
        elif exc.status_code == 409:
            code = "stale_evidence"
        elif exc.status_code == 410:
            code = "preview_expired"
        elif exc.status_code == 422:
            code = "review_required"
        elif exc.status_code == 502:
            code = "ai_unavailable"
        elif exc.status_code == 503:
            code = "graph_unavailable"
        else:
            code = "http_error"
        message = str(exc.detail)
        details = None

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details,
            }
        },
    )


app.add_exception_handler(StarletteHTTPException, unified_http_exception_handler)
app.add_exception_handler(FastAPIHTTPException, unified_http_exception_handler)


@app.exception_handler(GraphError)
async def graph_error_handler(request: Request, exc: GraphError) -> JSONResponse:
    """Map typed repository errors directly to agreed HTTP status codes and error envelopes."""
    if isinstance(exc, StaleEvidence):
        status_code = 409
        code = "stale_evidence"
    elif isinstance(exc, IdempotencyConflict):
        status_code = 409
        code = "idempotency_conflict"
    elif isinstance(exc, ReviewRequired):
        status_code = 422
        code = "review_required"
    elif isinstance(exc, NotFound):
        status_code = 404
        code = "not_found"
    elif isinstance(exc, (GraphUnavailable, InconsistentRead)):
        status_code = 503
        code = "graph_unavailable"
    elif isinstance(exc, FixtureError):
        status_code = 400
        code = "invalid_fixture"
    else:
        status_code = 500
        code = "internal_error"

    # Contract requirement: Never return raw exception causes or traces
    safe_details = None
    if isinstance(exc.details, dict) and "current_version" in exc.details:
        safe_details = {"current_version": exc.details["current_version"]}

    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": exc.message or str(exc),
                "details": safe_details,
            }
        },
    )


@app.exception_handler(AIProviderError)
async def ai_provider_error_handler(request: Request, exc: AIProviderError) -> JSONResponse:
    """Map AI provider failures to 502 ai_unavailable."""
    return JSONResponse(
        status_code=502,
        content={
            "error": {
                "code": "ai_unavailable",
                "message": str(exc),
                "details": None,
            }
        },
    )


@app.exception_handler(AIReviewRequiredError)
async def ai_review_required_handler(request: Request, exc: AIReviewRequiredError) -> JSONResponse:
    """Map AI extraction review required triggers to 422 review_required."""
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "review_required",
                "message": exc.reason,
                "details": {"field": exc.field} if exc.field else None,
            }
        },
    )


@app.exception_handler(ExtractionValidationError)
async def ai_extraction_validation_handler(request: Request, exc: ExtractionValidationError) -> JSONResponse:
    """Map extraction quote validation failures to 422 review_required."""
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "review_required",
                "message": str(exc),
                "details": None,
            }
        },
    )


@app.exception_handler(AIStaleEvidenceError)
async def ai_stale_evidence_handler(request: Request, exc: AIStaleEvidenceError) -> JSONResponse:
    """Map AI agent stale evidence errors to 409 stale_evidence."""
    return JSONResponse(
        status_code=409,
        content={
            "error": {
                "code": "stale_evidence",
                "message": str(exc),
                "details": {"expected": exc.expected, "current": exc.current},
            }
        },
    )


@app.exception_handler(RippleError)
async def ripple_domain_exception_handler(
    request: Request, exc: RippleError
) -> JSONResponse:
    """Map legacy domain exceptions directly to agreed HTTP status codes and error envelopes."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler ensuring zero internal secrets/stack traces leak in 500s."""
    logger.error("Unhandled server exception: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "internal_error",
                "message": "Internal server error",
                "details": None,
            }
        },
    )


# Mount modular API routes under /api
app.include_router(api_router, prefix="/api")

# Mount frontend static distribution if built (for all-in-one deployment)
frontend_dist = os.getenv(
    "FRONTEND_DIST_DIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")),
)

if os.path.isdir(frontend_dist):
    assets_dir = os.path.join(frontend_dist, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend_spa(full_path: str):
        # Do not intercept API, health check, or documentation routes
        if full_path.startswith("api") or full_path in ("docs", "redoc", "openapi.json"):
            raise FastAPIHTTPException(status_code=404, detail="Not Found")
        file_path = os.path.join(frontend_dist, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        index_file = os.path.join(frontend_dist, "index.html")
        if os.path.isfile(index_file):
            return FileResponse(index_file)
        raise FastAPIHTTPException(status_code=404, detail="Frontend index.html not found")

