"""Controlled demonstration reset and synthetic fixture ingestion services."""

import asyncio
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from backend.app.graph.errors import ReviewRequired
from backend.app.schemas import DemoResetResponse
from backend.app.services.graph_client import get_graph_repository
from backend.app.services.preview_store import get_preview_store
from backend.app.settings import get_settings

logger = logging.getLogger("ripple.demo_service")

# Fallback state used strictly in DEV_MOCKS mode when no repository is connected
_mock_dataset_id: str = "ds_demo_20261017"
_mock_revision: int = 1


def set_active_dataset(dataset_id: str, revision: int = 1) -> None:
    """Helper for mock test mode."""
    global _mock_dataset_id, _mock_revision
    _mock_dataset_id = dataset_id
    _mock_revision = revision


def bump_knowledge_revision() -> str:
    """Helper for mock test mode."""
    global _mock_revision
    _mock_revision += 1
    return get_active_evidence_version()


def get_active_revision() -> int:
    """Return active integer revision."""
    version = get_active_evidence_version()
    parts = version.split(":", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return int(parts[1])
    return _mock_revision


def validate_expected_version(expected_version: str) -> None:
    """Validate expected_version against active evidence version."""
    current_version = get_active_evidence_version()
    norm_expected = expected_version.replace(":rev_", ":")
    norm_current = current_version.replace(":rev_", ":")
    if norm_expected != norm_current:
        from backend.app.errors import StaleVersionError
        raise StaleVersionError(
            f"Provided expected_version '{expected_version}' is stale. Active version is '{current_version}'.",
            details={"current_version": current_version},
        )


def get_active_evidence_version() -> str:
    """Return the active evidence version directly from GraphRepository in live mode."""
    repo = get_graph_repository()
    if repo is not None:
        return repo.get_version()
    return f"{_mock_dataset_id}:rev_{_mock_revision}"


def get_active_dataset_id() -> str:
    """Return the active dataset identifier directly from GraphRepository in live mode."""
    version = get_active_evidence_version()
    return version.split(":", 1)[0]


DEMO_GRAPHS = ("ripple_graph", "ripple_test", "ripple_demo")


def require_demo_graph() -> None:
    """Demo-only mutations (reset, dependency toggle) refuse to touch a non-demo graph."""
    graph = get_settings().falkordb_graph
    if graph not in DEMO_GRAPHS:
        raise ReviewRequired(
            f"Refused on non-demo graph '{graph}'. Allowed demo graphs: {', '.join(DEMO_GRAPHS)}."
        )


class DemoService:
    """Service to safely handle synthetic demo reseeding and fixture ingestion."""

    def __init__(self):
        self.fixtures_dir = str(
            Path(__file__).resolve().parents[3] / "fixtures" / "harbor"
        )

    async def reset_demo(self) -> DemoResetResponse:
        """Reseed dedicated synthetic demo graph, reset previews, and obtain fresh dataset identity.
        
        Strict safety:
        - Refuses reset on any non-demo graph name.
        - Seeds the graph BEFORE updating any API state; a failed seed leaves state untouched.
        - Clears transient preview proposals.
        """
        global _mock_dataset_id, _mock_revision
        # Enforce demo scope: refuse resets on production graphs
        require_demo_graph()

        repo = get_graph_repository()
        if repo is not None:
            # Seed graph synchronously off the event loop
            await asyncio.to_thread(repo.seed_demo, self.fixtures_dir)
            new_version = repo.get_version()
            dataset_id = new_version.split(":", 1)[0]
        else:
            # Dev mock fallback
            _mock_dataset_id = f"ds_{uuid.uuid4().hex[:8]}"
            _mock_revision = 1
            new_version = f"{_mock_dataset_id}:rev_{_mock_revision}"
            dataset_id = _mock_dataset_id

        # Clear pending unconfirmed decision previews and mock caches
        get_preview_store().clear()
        from backend.app.services.action_service import clear_actions_store
        from backend.app.services.decision_service import clear_decision_store
        clear_actions_store()
        clear_decision_store()

        logger.info(
            "Demo reset completed successfully. New dataset_id=%s, version=%s",
            dataset_id,
            new_version,
        )
        return DemoResetResponse(
            status="reset",
            dataset_id=dataset_id,
            evidence_version=new_version,
        )

    async def ingest_fixtures(self) -> Dict[str, Any]:
        """Import synthetic fixtures deterministically from the server fixture repository.
        
        Rejects caller-supplied paths to avoid arbitrary filesystem access.
        """
        repo = get_graph_repository()
        if repo is not None:
            await asyncio.to_thread(repo.seed_demo, self.fixtures_dir)
            new_version = repo.get_version()
        else:
            new_version = get_active_evidence_version()

        return {
            "status": "ingested",
            "imported_from": "harbor",
            "evidence_version": new_version,
            "message": "Deterministic synthetic fixture batch ingested successfully.",
        }
