"""Decision preview and confirmation endpoints for Ripple API."""

from functools import lru_cache
from fastapi import APIRouter, Depends, Request

from backend.app.schemas import (
    DecisionConfirmRequest,
    DecisionConfirmResponse,
    DecisionPreviewRequest,
    DecisionPreviewResponse,
)
from backend.app.services.decision_service import DecisionService

router = APIRouter()


@lru_cache()
def get_decision_service() -> DecisionService:
    """Dependency provider for DecisionService."""
    return DecisionService()


@router.post("/decisions/preview", response_model=DecisionPreviewResponse)
async def preview_decision(
    request: DecisionPreviewRequest,
    decision_service: DecisionService = Depends(get_decision_service),
):
    """Extract and preview an engineering decision delta.

    Assigns server-side effective_at timestamp and sets a 15-minute TTL.
    """
    return await decision_service.preview_decision(request)


@router.post("/decisions/confirm", response_model=DecisionConfirmResponse)
async def confirm_decision(
    request: DecisionConfirmRequest,
    http_request: Request,
    decision_service: DecisionService = Depends(get_decision_service),
):
    """Confirm a previewed decision proposal atomically under single-worker mutation lock.

    Persists Source, Decision, and Forecast cutover, updating evidence version.
    Supports idempotency replay via RequestRecord.
    """
    lock = getattr(http_request.app.state, "mutation_lock", None)
    if lock:
        async with lock:
            return await decision_service.confirm_decision(request)
    return await decision_service.confirm_decision(request)
