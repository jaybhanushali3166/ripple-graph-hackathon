"""Source and forecast history service retrieving provenance directly from GraphRepository."""

import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from backend.app.errors import EntityNotFoundError
from backend.app.graph.errors import NotFound
from backend.app.schemas import (
    ForecastHistoryItem,
    SourceRef,
    SourceResponse,
    WorkItemHistoryResponse,
)
from backend.app.services.demo_service import get_active_evidence_version
from backend.app.services.graph_client import get_graph_repository
from backend.app.settings import get_settings

logger = logging.getLogger("ripple.source_service")

# Cache fixture sources directly from disk for mock mode
_fixture_sources_cache: Optional[Dict[str, Dict[str, Any]]] = None


def _get_mock_fixture_sources() -> Dict[str, Dict[str, Any]]:
    """Load exact fixture source files from fixtures/harbor/sources/."""
    global _fixture_sources_cache
    if _fixture_sources_cache is not None:
        return _fixture_sources_cache

    sources_dir = Path(__file__).resolve().parents[3] / "fixtures" / "harbor" / "sources"
    index_file = sources_dir / "index.json"
    cache = {}

    if index_file.exists():
        index_data = json.loads(index_file.read_text(encoding="utf-8"))
        for entry in index_data:
            source_file = sources_dir / entry["file"]
            if source_file.exists():
                body = source_file.read_text(encoding="utf-8")
                content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
                cache[entry["id"]] = {
                    "id": entry["id"],
                    "type": entry["type"],
                    "title": entry["title"],
                    "body": body,
                    "source_timestamp": 1792195200000,
                    "content_hash": content_hash,
                }
    _fixture_sources_cache = cache
    return _fixture_sources_cache


class SourceService:
    """Service to retrieve source documents and forecast history with zero mock drift."""

    async def get_source(self, source_id: str) -> SourceResponse:
        """Fetch source content and deterministic sha256 hash.
        
        Raises NotFound (404) if source does not exist.
        """
        repo = get_graph_repository()
        if repo is not None:
            raw = await asyncio.to_thread(repo.get_source, source_id)
            return SourceResponse(**raw)

        # Mock fallback using real fixture files
        sources = _get_mock_fixture_sources()
        if source_id not in sources:
            raise EntityNotFoundError(f"source '{source_id}' not found")

        return SourceResponse(**sources[source_id])

    async def get_history(self, work_item_id: str) -> WorkItemHistoryResponse:
        """Fetch accepted forecast history and establishing decisions.
        
        Raises NotFound (404) if work item does not exist.
        """
        repo = get_graph_repository()
        if repo is not None:
            raw = await asyncio.to_thread(repo.get_history, work_item_id)
            return WorkItemHistoryResponse(**raw)

        # Mock fallback
        current_version = get_active_evidence_version()
        if work_item_id == "wi_permissions":
            return WorkItemHistoryResponse(
                evidence_version=current_version,
                forecasts=[
                    ForecastHistoryItem(
                        id="fc_permissions_baseline",
                        available_at=1792607399999,
                        valid_from=1790899200000,
                        valid_to=None,
                        decision_id="DEC-12",
                        citations=[
                            SourceRef(
                                source_id="src_dec12",
                                quote="DEC-12: Approved. The permissions service will be delivered by October 21, 2026. Owner: Priya.",
                            )
                        ],
                    )
                ],
            )

        raise EntityNotFoundError(f"work item '{work_item_id}' not found")
