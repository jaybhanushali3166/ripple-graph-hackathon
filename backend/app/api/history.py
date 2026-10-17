"""Work-item forecast history endpoint for Ripple API."""

from functools import lru_cache
from fastapi import APIRouter, Depends

from backend.app.schemas import WorkItemHistoryResponse
from backend.app.services.source_service import SourceService

router = APIRouter()


@lru_cache()
def get_source_service() -> SourceService:
    """Dependency provider for SourceService."""
    return SourceService()


@router.get("/work-items/{work_item_id}/history", response_model=WorkItemHistoryResponse)
async def get_work_item_history(
    work_item_id: str,
    source_service: SourceService = Depends(get_source_service),
):
    """Retrieve accepted forecast history and establishing decisions for a work item.

    Non-nullable decision_id is enforced on all forecast items.
    Raises 404 EntityNotFoundError if work item does not exist.
    """
    return await source_service.get_history(work_item_id)
