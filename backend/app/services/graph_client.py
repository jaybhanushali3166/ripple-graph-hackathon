"""Centralized repository accessor and connection wrapper for FalkorDB."""

import logging
from typing import Optional

from backend.app.graph.client import GraphClient
from backend.app.graph.repository import GraphRepository
from backend.app.settings import get_settings

logger = logging.getLogger("ripple.graph_client")

# Cached repository instance
_live_repo: Optional[GraphRepository] = None


def get_graph_repository() -> Optional[GraphRepository]:
    """Retrieve the GraphRepository instance, or None if in mock mode and no test double is set."""
    global _live_repo
    settings = get_settings()

    if settings.dev_mocks:
        logger.debug("Running in DEV_MOCKS mode without injected repository.")
        return None

    if _live_repo is not None:
        return _live_repo

    # Live mode: construct real GraphClient and GraphRepository
    client = GraphClient(
        host=settings.falkordb_host,
        port=settings.falkordb_port,
        graph_name=settings.falkordb_graph,
        username=settings.falkordb_username,
        password=settings.falkordb_password,
        tls=settings.falkordb_tls,
        tls_ca_certs=settings.falkordb_tls_ca_certs,
    )
    _live_repo = GraphRepository(client=client)
    return _live_repo


def set_graph_repository(repo: Optional[GraphRepository]) -> None:
    """Explicitly set or inject a repository instance (for tests or doubles)."""
    global _live_repo
    _live_repo = repo


def reset_graph_repository_cache() -> None:
    """Clear cached repository instance."""
    global _live_repo
    _live_repo = None
