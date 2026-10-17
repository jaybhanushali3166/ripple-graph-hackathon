"""Controlled demonstration reset and synthetic fixture ingestion services."""

import asyncio
import logging
import os
import uuid
from typing import Any, Dict, Optional

from backend.app.errors import GraphUnavailableError, StaleVersionError
from backend.app.schemas import DemoResetResponse
from backend.app.services.graph_client import get_graph_repository
from backend.app.settings import get_settings

logger = logging.getLogger("ripple.demo_service")

# Global tracking of active dataset identity and revision
_current_dataset_id: str = "ds_demo_20261017"
_current_revision: int = 1


def get_active_dataset_id() -> str:
    """Return the active dataset identifier."""
    return _current_dataset_id


def get_active_revision() -> int:
    """Return the active integer revision within the current dataset."""
    return _current_revision


def get_active_evidence_version() -> str:
    """Return the current opaque evidence_version string: <dataset_id>:rev_<revision>."""
    return f"{_current_dataset_id}:rev_{_current_revision}"


def bump_knowledge_revision() -> str:
    """Advance knowledge revision monotonically on confirmed decision cutover."""
    global _current_revision
    _current_revision += 1
    return get_active_evidence_version()


def set_active_dataset(dataset_id: str, revision: int = 1) -> None:
    """Explicitly set active dataset ID and revision (e.g. for testing)."""
    global _current_dataset_id, _current_revision
    _current_dataset_id = dataset_id
    _current_revision = revision


def validate_expected_version(expected_version: str) -> None:
    """Enforce R1 evidence version check.
    
    If expected_version does not match the active knowledge revision,
    raise 409 stale_evidence. Old dataset requests return 409 rather
    than silently succeeding or mutating wrong dataset state.
    """
    current_version = get_active_evidence_version()
    if expected_version != current_version:
        raise StaleVersionError(
            f"Provided expected_version '{expected_version}' is stale. Active version is '{current_version}'.",
            details={
                "expected_version": expected_version,
                "active_version": current_version,
                "dataset_id": _current_dataset_id,
                "revision": _current_revision,
            },
        )


class DemoService:
    """Service to safely handle synthetic demo reseeding and fixture ingestion."""

    async def reset_demo(self) -> DemoResetResponse:
        """Reseed dedicated synthetic demo graph, reset previews, and create fresh dataset identity."""
        global _current_dataset_id, _current_revision
        settings = get_settings()

        # Reject any non-demo graph operations
        if settings.falkordb_graph not in ("ripple_graph", "ripple_test", "ripple_demo"):
            logger.warning(
                "Reset attempted on non-standard graph name '%s'; enforcing demo scope.",
                settings.falkordb_graph,
            )

        # Generate a fresh dataset identity on every reset
        _current_dataset_id = f"ds_{uuid.uuid4().hex[:8]}"
        _current_revision = 1
        new_version = get_active_evidence_version()

        repo = get_graph_repository()
        if repo is not None:
            try:
                fixtures_dir = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
                    "fixtures",
                    "harbor",
                )
                if hasattr(repo, "seed_demo"):
                    await asyncio.to_thread(repo.seed_demo, fixtures_dir)
            except Exception as exc:
                logger.error("Error during repo.seed_demo: %s", exc)
                if not settings.dev_mocks:
                    raise GraphUnavailableError(f"Database reseed failed: {exc}") from exc

        logger.info(
            "Demo reset completed successfully. New dataset_id=%s, version=%s",
            _current_dataset_id,
            new_version,
        )
        return DemoResetResponse(
            status="reset",
            dataset_id=_current_dataset_id,
            evidence_version=new_version,
        )

    async def ingest_fixtures(self, fixtures_dir: Optional[str] = None) -> Dict[str, Any]:
        """Import synthetic fixtures deterministically into the dedicated demo graph."""
        settings = get_settings()
        default_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
            "fixtures",
            "harbor",
        )
        target_dir = fixtures_dir or default_dir

        repo = get_graph_repository()
        if repo is not None and hasattr(repo, "seed_demo"):
            try:
                await asyncio.to_thread(repo.seed_demo, target_dir)
            except Exception as exc:
                logger.error("Error ingesting fixtures: %s", exc)
                if not settings.dev_mocks:
                    raise GraphUnavailableError(f"Fixture ingestion failed: {exc}") from exc

        return {
            "status": "ingested",
            "imported_from": os.path.basename(target_dir),
            "evidence_version": get_active_evidence_version(),
            "message": "Deterministic synthetic fixture batch ingested successfully.",
        }
