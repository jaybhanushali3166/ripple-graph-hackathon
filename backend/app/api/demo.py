"""Demo management and ingestion endpoints for Ripple API."""

from functools import lru_cache
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request

from backend.app.schemas import DemoResetResponse
from backend.app.services.demo_service import DemoService

router = APIRouter()


@lru_cache()
def get_demo_service() -> DemoService:
    """Dependency provider for DemoService."""
    return DemoService()


@router.post("/demo/reset", response_model=DemoResetResponse)
async def reset_demo(
    request: Request,
    demo_service: DemoService = Depends(get_demo_service),
):
    """Reseed dedicated synthetic demo graph and establish fresh dataset identity."""
    lock = getattr(request.app.state, "mutation_lock", None)
    if lock:
        async with lock:
            return await demo_service.reset_demo()
    return await demo_service.reset_demo()


@router.post("/ingest")
async def ingest_fixtures(
    request: Request,
    demo_service: DemoService = Depends(get_demo_service),
):
    """Ingest deterministic synthetic fixtures into FalkorDB from server repository."""
    lock = getattr(request.app.state, "mutation_lock", None)
    if lock:
        async with lock:
            return await demo_service.ingest_fixtures()
    return await demo_service.ingest_fixtures()
