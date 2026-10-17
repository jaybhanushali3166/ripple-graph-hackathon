"""Centralized repository accessor and connection wrapper for FalkorDB."""

import logging
from typing import Any, Optional

from backend.app.errors import GraphUnavailableError
from backend.app.settings import get_settings

logger = logging.getLogger("ripple.graph_client")

# Cached repository instance when running against live database
_live_repo: Optional[Any] = None


def get_graph_repository() -> Optional[Any]:
    """Retrieve the GraphRepository instance, or None if in mock mode or not yet available."""
    global _live_repo
    settings = get_settings()

    if settings.dev_mocks:
        logger.debug("Running in DEV_MOCKS mode; bypassing live GraphRepository.")
        return None

    if _live_repo is not None:
        return _live_repo

    try:
        # Dynamically import Ashwin's repository if available
        from backend.app.graph.repository import GraphRepository  # type: ignore

        _live_repo = GraphRepository(
            host=settings.falkordb_host,
            port=settings.falkordb_port,
            graph_name=settings.falkordb_graph,
        )
        return _live_repo
    except ImportError:
        logger.warning(
            "GraphRepository module not found (backend.app.graph.repository). "
            "Falling back to mock mode or explicit test doubles."
        )
        return None
    except Exception as exc:
        logger.error("Failed to connect to FalkorDB at %s:%s: %s", settings.falkordb_host, settings.falkordb_port, exc)
        raise GraphUnavailableError(
            f"FalkorDB is unreachable at {settings.falkordb_host}:{settings.falkordb_port}",
            details={"host": settings.falkordb_host, "port": settings.falkordb_port, "error": str(exc)},
        ) from exc


def reset_graph_repository_cache() -> None:
    """Clear cached repository instance (useful during testing or reset)."""
    global _live_repo
    _live_repo = None
