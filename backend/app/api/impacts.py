"""Impact query endpoint for Ripple API."""

from functools import lru_cache
from typing import Optional

from fastapi import APIRouter, Depends, Response

from backend.app.schemas import ImpactResponse
from backend.app.services.impact_service import ImpactService
from backend.app.settings import get_settings

router = APIRouter()


@lru_cache()
def get_impact_service() -> ImpactService:
    """Dependency provider for ImpactService."""
    return ImpactService()


@router.get("/impacts", response_model=ImpactResponse)
async def get_impacts(
    as_of: Optional[int] = None,
    response: Response = None,
    impact_service: ImpactService = Depends(get_impact_service),
):
    """Retrieve commitment impact summaries and evidence paths.

    When DEV_MOCKS=True, returns canonical scenarios and sets X-Mock-Mode header.
    Applies R1 owner resolution rules.
    """
    settings = get_settings()
    if settings.dev_mocks and response is not None:
        response.headers["X-Mock-Mode"] = "true"

    return await impact_service.get_impacts(as_of=as_of)
