"""Actions creation and retrieval endpoints for Ripple API."""

from functools import lru_cache
from typing import Optional

from fastapi import APIRouter, Depends, Request

from backend.app.schemas import (
    ActionCreateRequest,
    ActionCreateResponse,
    ActionListResponse,
)
from backend.app.services.action_service import ActionService

router = APIRouter()


@lru_cache()
def get_action_service() -> ActionService:
    """Dependency provider for ActionService."""
    return ActionService()


@router.post("/actions", response_model=ActionCreateResponse)
async def create_action(
    request: ActionCreateRequest,
    http_request: Request,
    action_service: ActionService = Depends(get_action_service),
):
    """Persist a reviewed action draft against a specific evidence version.

    Requires single-worker mutation lock. Idempotent via RequestRecord.
    """
    lock = getattr(http_request.app.state, "mutation_lock", None)
    if lock:
        async with lock:
            return await action_service.create_action(request)
    return await action_service.create_action(request)


@router.get("/actions", response_model=ActionListResponse)
async def list_actions(
    commitment_id: Optional[str] = None,
    action_service: ActionService = Depends(get_action_service),
):
    """Retrieve persisted reviewed actions, preserving original evidence version."""
    return await action_service.list_actions(commitment_id)
