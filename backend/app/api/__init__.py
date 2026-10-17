"""Modular API router aggregation for Ripple API."""

from fastapi import APIRouter

from backend.app.api.actions import router as actions_router
from backend.app.api.agent import router as agent_router
from backend.app.api.decisions import router as decisions_router
from backend.app.api.demo import router as demo_router
from backend.app.api.graph import router as graph_router
from backend.app.api.health import router as health_router
from backend.app.api.history import router as history_router
from backend.app.api.impacts import router as impacts_router
from backend.app.api.sources import router as sources_router

api_router = APIRouter()

api_router.include_router(health_router, tags=["health"])
api_router.include_router(impacts_router, tags=["impacts"])
api_router.include_router(sources_router, tags=["sources"])
api_router.include_router(history_router, tags=["history"])
api_router.include_router(decisions_router, tags=["decisions"])
api_router.include_router(agent_router, tags=["agent"])
api_router.include_router(actions_router, tags=["actions"])
api_router.include_router(demo_router, tags=["demo"])
api_router.include_router(graph_router, tags=["graph"])

__all__ = ["api_router"]
