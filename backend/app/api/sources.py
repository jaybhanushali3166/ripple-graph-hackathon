"""Source inspection endpoint for Ripple API."""

from functools import lru_cache
from fastapi import APIRouter, Depends

from backend.app.schemas import SourceResponse
from backend.app.services.source_service import SourceService

router = APIRouter()


@lru_cache()
def get_source_service() -> SourceService:
    """Dependency provider for SourceService."""
    return SourceService()


@router.get("/sources/{source_id}", response_model=SourceResponse)
async def get_source(
    source_id: str,
    source_service: SourceService = Depends(get_source_service),
):
    """Retrieve source document content, metadata, and deterministic content hash.

    Raises 404 EntityNotFoundError if source does not exist.
    """
    return await source_service.get_source(source_id)
