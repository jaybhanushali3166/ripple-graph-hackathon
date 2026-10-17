"""Impact analysis service for querying commitment risks directly from GraphRepository."""

import asyncio
import json
import logging
import os
import time
from typing import Optional

from backend.app.schemas import (
    Completeness,
    EntityOwner,
    Impact,
    ImpactResponse,
)
from backend.app.services.graph_client import get_graph_repository
from backend.app.settings import get_settings

logger = logging.getLogger("ripple.impact_service")


def _load_fallback_impacts(as_of: int) -> ImpactResponse:
    """Load canonical scenario impacts from docs/examples/canonical_payloads.json or fallback mock."""
    payloads_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
        "docs",
        "examples",
        "canonical_payloads.json",
    )
    if os.path.exists(payloads_path):
        try:
            with open(payloads_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            from backend.app.services.demo_service import (
                get_active_evidence_version,
                get_active_revision,
            )
            revision = get_active_revision()
            payload = data.get("updated_impacts") if revision >= 2 else data.get("baseline_impacts")
            if payload:
                payload = dict(payload)
                payload["evidence_version"] = get_active_evidence_version()
                payload["as_of"] = as_of
                return ImpactResponse(**payload)
        except Exception as exc:
            logger.warning("Could not read canonical_payloads.json: %s", exc)

    return ImpactResponse(
        evidence_version="ds_demo_001:0",
        as_of=as_of,
        impacts=[
            Impact(
                commitment_id="com_acme_sso",
                customer=EntityOwner(id="cust_acme", name="Acme Corp"),
                title="Single Sign-On Integration",
                due_at=1792693800000,
                status="no_detected_conflict",
                reasons=[],
                blockers=[],
                paths=[],
                engineering_owner=EntityOwner(id="person_lena", name="Lena Chen"),
                account_owner=EntityOwner(id="person_maya", name="Maya Lin"),
                citations=[],
            )
        ],
        completeness=Completeness(complete=True, truncated=False, warnings=[]),
    )


class ImpactService:
    """Service coordinating commitment impact detection against FalkorDB GraphRepository."""

    async def get_impacts(self, as_of: Optional[int] = None) -> ImpactResponse:
        """Fetch impacts for all customer commitments as of a specific epoch ms.
        
        Zero business-rule duplication: GraphRepository computes graph paths,
        blockers, R1 owners, and status precedence. Results pass through directly.
        """
        effective_as_of = as_of if as_of is not None else int(time.time() * 1000)
        repo = get_graph_repository()

        if repo is None:
            logger.debug("Serving impacts from mock provider (DEV_MOCKS=True).")
            return _load_fallback_impacts(effective_as_of)

        # Offload blocking synchronous graph queries off the async event loop
        raw_response = await asyncio.to_thread(repo.list_impacts, effective_as_of)

        # Ensure zero raw database objects leak; validate against Pydantic model
        if isinstance(raw_response, dict):
            return ImpactResponse(**raw_response)
        return raw_response
