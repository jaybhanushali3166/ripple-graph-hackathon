"""Health check endpoint for Ripple API."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def get_health():
    """Return API health status, database type, and version."""
    return {
        "status": "ok",
        "database": "falkordb",
        "version": "0.1.0",
    }
