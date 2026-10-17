"""Agent run orchestration endpoint for Ripple API."""

from functools import lru_cache
from fastapi import APIRouter, Depends

from backend.app.schemas import AgentResponse, AgentRunRequest
from backend.app.services.agent_service import AgentService

router = APIRouter()


@lru_cache()
def get_agent_service() -> AgentService:
    """Dependency provider for AgentService."""
    return AgentService()


@router.post("/agent/run", response_model=AgentResponse)
async def run_agent(
    request: AgentRunRequest,
    agent_service: AgentService = Depends(get_agent_service),
):
    """Execute bounded AI reasoning across impact/owners or decision lineage.

    Returns cited explanation, structured tool trace, and proposed follow-up drafts.
    Enforces strict expected_version checking.
    """
    return await agent_service.run_agent(request)
