"""Graph view, source index, expertise and demo dependency-toggle endpoints for Ripple API."""

from functools import lru_cache

from fastapi import APIRouter, Depends, Request

from backend.app.schemas import (
    DependencyToggleRequest,
    DependencyToggleResponse,
    ExpertsResponse,
    GraphViewResponse,
    SourceListResponse,
)
from backend.app.services.graph_view_service import GraphViewService

router = APIRouter()


@lru_cache()
def get_graph_view_service() -> GraphViewService:
    """Dependency provider for GraphViewService."""
    return GraphViewService()


@router.get("/graph", response_model=GraphViewResponse)
async def get_graph(service: GraphViewService = Depends(get_graph_view_service)):
    """Customers, commitments and work items with the relationships impact detection walks."""
    return await service.get_graph()


@router.get("/sources", response_model=SourceListResponse)
async def list_sources(service: GraphViewService = Depends(get_graph_view_service)):
    """Titles and types of every stored source, without bodies."""
    return await service.list_sources()


@router.get("/work-items/{work_item_id}/experts", response_model=ExpertsResponse)
async def get_experts(work_item_id: str, service: GraphViewService = Depends(get_graph_view_service)):
    """Who knows a work item: owner, people who discussed it, and the responsible team."""
    return await service.get_experts(work_item_id)


@router.post("/demo/dependency", response_model=DependencyToggleResponse)
async def set_dependency(
    request: DependencyToggleRequest,
    http_request: Request,
    service: GraphViewService = Depends(get_graph_view_service),
):
    """Remove or restore one recorded dependency edge to show the graph decides impact."""
    lock = getattr(http_request.app.state, "mutation_lock", None)
    if lock:
        async with lock:
            return await service.set_dependency(request)
    return await service.set_dependency(request)
