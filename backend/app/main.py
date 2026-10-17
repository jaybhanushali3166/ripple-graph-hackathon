"""Main FastAPI application entrypoint for Ripple API."""

import asyncio
import logging
from typing import Any, Dict

from fastapi import FastAPI, HTTPException as FastAPIHTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.app.api import api_router
from backend.app.errors import RippleError

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

# Configure CORS for local Vite dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
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


@app.exception_handler(RippleError)
async def ripple_domain_exception_handler(
    request: Request, exc: RippleError
) -> JSONResponse:
    """Map domain exceptions directly to agreed HTTP status codes and error envelopes."""
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


# Include modular API routers under prefix /api
app.include_router(api_router)
